from __future__ import annotations

import json

from starlette.responses import JSONResponse

from .config import settings
from .compliance import ServerMode
from .tools import memory, vector_db
from .tools import get_registered_names


def register_web_ui(mcp) -> None:
    # REST API endpoints for local clients (e.g. the OpenCode memory
    # plugin). The in-browser debug UI was removed — we don't need it
    # anymore.
    #
    # In compliant mode, no API is served — the MCP tools are the only
    # interface.
    if settings.server_mode != ServerMode.NON_COMPLIANT:
        return

    @mcp.custom_route("/api/collections", methods=["GET"])
    async def api_list_collections(request):
        try:
            return JSONResponse(json.loads(await vector_db.list_collections()))
        except AssertionError:
            return JSONResponse({"error": "Database not initialized"}, status_code=503)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/collections/{name}", methods=["GET"])
    async def api_collection_info(request):
        try:
            return JSONResponse(json.loads(await vector_db.collection_info(request.path_params["name"])))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/collections/{name}/search", methods=["POST"])
    async def api_search(request):
        try:
            body = await request.json()
            return JSONResponse(json.loads(await vector_db.search(
                collection_name=request.path_params["name"],
                query=body.get("query", ""),
                n_results=body.get("n_results", 10),
                filter_metadata=body.get("filter_metadata"),
            )))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/collections/{name}/ingest", methods=["POST"])
    async def api_ingest(request):
        try:
            body = await request.json()
            return JSONResponse(json.loads(await vector_db.ingest(
                collection_name=request.path_params["name"],
                documents=body.get("documents", []),
                metadata=body.get("metadata"),
                ids=body.get("ids"),
            )))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/health", methods=["GET"])
    async def api_health(request):
        return JSONResponse({
            "status": "ok",
            "mode": settings.server_mode.value,
            "tools_available": get_registered_names(),
        })

    @mcp.custom_route("/api/memory/ingest", methods=["POST"])
    async def api_memory_ingest(request):
        try:
            body = await request.json()
            return JSONResponse(json.loads(await memory.memory_ingest(
                text=body.get("text", ""),
                memory_type=body.get("memory_type", "technical"),
                importance=body.get("importance", 3),
                emotional_tone=body.get("emotional_tone"),
                participants=body.get("participants"),
                session_id=body.get("session_id"),
                collection_name=body.get("collection_name"),
                allow_duplicate=body.get("allow_duplicate", False),
                historical=body.get("historical", False),
                event_timestamp=body.get("event_timestamp"),
                experience_mode=body.get("experience_mode", "unknown"),
                historical_status=body.get("historical_status", "uncertain"),
                recorded_during=body.get("recorded_during", "unknown"),
                provenance_note=body.get("provenance_note"),
                derived_from=body.get("derived_from"),
            )))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/memory/sample", methods=["GET"])
    async def api_memory_sample(request):
        try:
            n = request.query_params.get("n")
            collection = request.query_params.get("collection")
            return JSONResponse(json.loads(await memory.memory_sample(
                n=int(n) if n else 8,
                collection_name=collection,
            )))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/memory/context", methods=["GET"])
    async def api_memory_context(request):
        # Used by the OpenCode memory plugin for passive injection at
        # session start / after compaction. Not part of the MCP tool
        # surface — a lightweight HTTP shortcut to the same function.
        try:
            limit = request.query_params.get("limit")
            collection = request.query_params.get("collection")
            return JSONResponse(json.loads(await memory.memory_context(
                limit=int(limit) if limit else None,
                collection_name=collection,
            )))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
