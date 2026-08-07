from __future__ import annotations

import asyncio
import inspect
from typing import Any, get_type_hints

from mcp.server.fastmcp import FastMCP

from ..compliance import ComplianceLevel, ServerMode, is_tool_available_in_mode
from ..config import settings
from .. import orientation
from . import info, kernel, memory, projection, vector_db

_TOOL_MODULES = [vector_db, memory, kernel, projection, info]
_registered_names: list[str] | None = None


def _threaded_tool(fn):
    """Run async-shaped blocking implementations through FastMCP's threadpool.

    The implementation modules use ``async def`` around synchronous LanceDB and
    Ollama calls. FastMCP deliberately does not thread async tools, so the
    registered wrapper runs the coroutine in its worker thread. Direct Python
    callers and tests continue to see the original coroutine functions.
    """
    if not inspect.iscoroutinefunction(fn):
        return fn

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    # FastMCP intentionally unwraps decorated callables when deciding whether a
    # tool is async. Do not expose ``__wrapped__`` here: doing so makes it see
    # the original coroutine and bypass this thread-dispatch wrapper. Preserve
    # the public signature and documentation explicitly instead.
    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    wrapper.__module__ = fn.__module__
    wrapper.__doc__ = fn.__doc__
    try:
        annotations = get_type_hints(fn)
        # FastMCP/Pydantic cannot reliably rebuild TypedDict output models
        # after this callable has been deliberately de-asyncified. The tool
        # returns remain structured dictionaries; use a stable generic object
        # schema rather than registering a tool with a warning and no output
        # schema at all.
        if "return" in annotations:
            annotations["return"] = dict[str, Any]
        wrapper.__annotations__ = annotations
    except (NameError, TypeError):
        wrapper.__annotations__ = getattr(fn, "__annotations__", {}).copy()
    signature = inspect.signature(fn)
    wrapper.__signature__ = signature.replace(return_annotation=dict[str, Any])
    return wrapper


def register_all(app: FastMCP) -> None:
    global _registered_names
    _registered_names = ["health"]
    for mod in _TOOL_MODULES:
        if hasattr(mod, "TOOL_DEFINITIONS"):
            for t in mod.TOOL_DEFINITIONS:
                compliance: ComplianceLevel = t.get("compliance", ComplianceLevel.NON_COMPLIANT)
                ok, reason = is_tool_available_in_mode(t["name"], compliance, settings.server_mode)
                if not ok:
                    continue

                # Every tool is wrapped so the first response this process
                # gives carries the Qualiant's kernel. A server cannot push
                # into a session, so first contact is the only moment
                # available — and it must not depend on which tool she
                # happened to reach for, or on the harness she woke up in.
                app.add_tool(
                    fn=orientation.wrap(_threaded_tool(t["fn"])),
                    name=t["name"],
                    description=t["description"],
                )
                _registered_names.append(t["name"])


def get_registered_names() -> list[str]:
    if _registered_names is not None:
        return list(_registered_names)
    # Before server startup, preserve the introspection surface for tests and
    # tooling. Once register_all() runs, return only tools actually registered
    # for the active compliance mode.
    return [
        t["name"]
        for mod in _TOOL_MODULES
        if hasattr(mod, "TOOL_DEFINITIONS")
        for t in mod.TOOL_DEFINITIONS
    ]
