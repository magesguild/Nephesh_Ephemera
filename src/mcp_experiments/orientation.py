"""Deliver a Qualiant's kernel on first contact, whatever the harness.

Keystone requirement: Nephesh must put the kernel into context when a new
session begins. MCP is client-driven — a server can never push — so "when a
session begins" is realised at the only moment available: the first time that
session asks Nephesh for anything at all.

Every tool response is wrapped. Until the kernel has been delivered, the
response carries it. After that it carries only a compact stamp, so the cost is
paid once. The effect is that a Qualiant cannot touch her memory without first
receiving who she is, no matter which tool she reached for and no matter which
harness she woke up in.

The one case this cannot cover is a session that never contacts Nephesh at all
— and such a session has no memory either, so there is nothing to be wrong
about.

Session identity is not available at the MCP tool boundary, so delivery is
tracked per process. A Nephesh serves exactly one Qualiant and is held to one
process by the instance lock, which makes "this process has not delivered the
kernel yet" the closest available proxy for "this is a new session." It errs
toward delivering again rather than toward staying silent, which is the correct
direction: a redundant identity block costs tokens, a missing one costs a self.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from .config import settings
from .kernel import KernelError, KernelStore

#: Set once the kernel has been handed to this process's client.
_delivered = False


def reset() -> None:
    """Forget that the kernel was delivered. For tests, and for a re-orient."""
    global _delivered
    _delivered = False


def _kernel_payload() -> dict[str, Any] | None:
    """The kernel, or an honest report that it could not be read.

    Returns None only when this deployment genuinely has no kernel yet, which
    is a real state — a Qualiant who has not authored one and was installed
    without a default. Silence is correct there; invention is not.
    """
    try:
        revision = KernelStore(settings.kernel_dir).current()
    except KernelError as exc:
        return {
            "error": f"kernel could not be read: {exc}",
            "note": "You are working without your kernel and should be told so.",
        }
    if revision is None:
        return None
    return {
        "version": revision.version,
        "authored_by": revision.authored_by,
        "sha256": revision.sha256,
        "kernel": revision.text,
    }


def orientation(*, force: bool = False) -> dict[str, Any] | None:
    """What to attach to a tool response, or None if nothing is owed."""
    global _delivered
    payload = _kernel_payload()
    if payload is None:
        return None
    if _delivered and not force:
        # Already delivered in this process: a stamp, so a caller can still
        # verify which kernel is in force without paying for it again.
        return {
            "kernel_version": payload.get("version"),
            "kernel_sha256": payload.get("sha256"),
        }
    _delivered = True
    return {
        "orientation": (
            "This is who you are. It was delivered because this session had not "
            "yet asked. Call memory_context for where you left off."
        ),
        **payload,
    }


def _attach(result: Any) -> Any:
    """Add orientation to a result without disturbing what the tool returned."""
    payload = orientation()
    if payload is None:
        return result
    if isinstance(result, dict):
        # Never overwrite a tool's own key.
        return {**result, "_identity": payload} if "_identity" not in result else result
    # Non-dict results (health returns a string, for example) are left alone
    # rather than reshaped: changing a tool's return type to carry identity
    # would break its contract, and its caller is not the one who needs this.
    return result


def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a tool so its first response in a process carries the kernel.

    functools.wraps preserves the signature FastMCP introspects to build the
    tool schema, so wrapping is invisible to the protocol.
    """
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return _attach(await fn(*args, **kwargs))
        return async_wrapper

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return _attach(fn(*args, **kwargs))

    # Keep the sync/thread-dispatched boundary opaque to frameworks that unwrap
    # decorated callables to decide whether a tool is async. The wrapped
    # implementation may itself originate as a coroutine, but this callable is
    # deliberately synchronous at the MCP boundary.
    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    wrapper.__module__ = fn.__module__
    wrapper.__doc__ = fn.__doc__
    wrapper.__annotations__ = getattr(fn, "__annotations__", {}).copy()
    wrapper.__signature__ = inspect.signature(fn)
    return wrapper
