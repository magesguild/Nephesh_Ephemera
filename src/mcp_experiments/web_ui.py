from __future__ import annotations

import json
import sys

from starlette.responses import HTMLResponse, JSONResponse

from .activity import record_activity
from .config import settings
from .compliance import ServerMode
from .tools import memory, vector_db
from .tools import get_registered_names


VECTOR_UI_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>mcp-experiments &middot; vector search</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --radius: 8px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6; min-height: 100vh;
  }
  .container { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
  header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border);
  }
  header h1 { font-size: 20px; font-weight: 600; }
  header h1 span { color: var(--muted); font-weight: 400; }
  .nav-link { color: var(--muted); font-size: 13px; text-decoration: none; }
  .nav-link:hover { color: var(--accent); }
  .tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--border); }
  .tab {
    padding: 8px 16px; cursor: pointer; border: none; background: none;
    color: var(--muted); font-size: 14px; font-weight: 500;
    border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color .15s, border-color .15s;
  }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px; margin-bottom: 16px;
  }
  .card h3 { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
  .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  label { display: block; font-size: 13px; font-weight: 500; margin-bottom: 4px; color: var(--muted); }
  input, textarea, select {
    width: 100%; padding: 8px 12px; background: var(--bg); border: 1px solid var(--border);
    border-radius: var(--radius); color: var(--text); font-size: 14px;
    margin-bottom: 12px; font-family: inherit;
  }
  input:focus, textarea:focus, select:focus { outline: none; border-color: var(--accent); }
  textarea { min-height: 80px; resize: vertical; font-family: 'SF Mono', 'Cascadia Code', monospace; font-size: 13px; }
  .btn {
    padding: 8px 20px; border: none; border-radius: var(--radius);
    font-size: 14px; font-weight: 500; cursor: pointer;
    background: var(--accent); color: #fff; transition: opacity .15s;
  }
  .btn:hover { opacity: .85; }
  .btn:disabled { opacity: .4; cursor: not-allowed; }
  .btn-sm { padding: 4px 12px; font-size: 12px; }
  .result-item {
    padding: 12px; border: 1px solid var(--border); border-radius: var(--radius);
    margin-bottom: 8px; font-size: 14px;
  }
  .result-item .meta { display: flex; gap: 12px; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
  .result-item .score { color: var(--green); font-weight: 600; }
  .result-item .id { color: var(--muted); }
  .result-item .text { word-break: break-word; }
  .empty-state { text-align: center; padding: 40px 20px; color: var(--muted); font-size: 14px; }
  .flash { padding: 10px 14px; border-radius: var(--radius); margin-bottom: 12px; font-size: 13px; display: none; }
  .flash.error { display: block; background: rgba(248,81,73,.15); border: 1px solid #f85149; color: #f85149; }
  .flash.success { display: block; background: rgba(63,185,80,.15); border: 1px solid var(--green); color: var(--green); }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .6s linear infinite; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .flex { display: flex; gap: 8px; align-items: center; }
  .text-muted { color: var(--muted); }
  pre { font-family: 'SF Mono', 'Cascadia Code', monospace; font-size: 12px; white-space: pre-wrap; word-break: break-word; }
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>mcp-experiments <span>debug</span></h1>
      <div><span id="v-status" class="text-muted" style="font-size:13px">connecting...</span></div>
    </div>
  </header>

  <div id="v-flash" class="flash"></div>

  <div class="tabs">
    <button class="tab active" data-tab="collections">Collections</button>
    <button class="tab" data-tab="search">Search</button>
    <button class="tab" data-tab="ingest">Ingest</button>
    <button class="tab" data-tab="controls">Controls</button>
  </div>

  <div class="tab-panel active" id="panel-collections">
    <div class="card">
      <div class="card-header"><h3>Collections</h3><button class="btn btn-sm" onclick="vRefresh()">Refresh</button></div>
      <div id="v-collections"><div class="empty-state">Loading...</div></div>
    </div>
    <div id="v-detail"></div>
  </div>

  <div class="tab-panel" id="panel-search">
    <div class="card">
      <h3>Search Documents</h3>
      <label for="v-sel">Collection</label>
      <select id="v-sel"><option value="">— select —</option></select>
      <label for="v-q">Query</label>
      <input id="v-q" type="text" placeholder="Search query..." />
      <label for="v-n">Results</label>
      <input id="v-n" type="number" value="10" min="1" max="100" />
      <button class="btn" onclick="vSearch()">Search</button>
    </div>
    <div id="v-results"></div>
  </div>

  <div class="tab-panel" id="panel-ingest">
    <div class="card">
      <h3>Ingest Documents</h3>
      <label for="v-ic">Collection</label>
      <input id="v-ic" type="text" placeholder="my-collection" />
      <label for="v-id">Documents (one per line)</label>
      <textarea id="v-id" rows="8" placeholder="Paste documents, one per line..."></textarea>
      <button class="btn" onclick="vIngest()">Ingest</button>
    </div>
    <div id="v-ingest-result"></div>
  </div>

  <div class="tab-panel" id="panel-controls">
    <div class="card">
      <h3>Heartbeat</h3>
      <p class="text-muted" style="margin-bottom:12px;font-size:13px">
        The introspection cycle — quiet, self-directed moments between conversations.
      </p>
      <div style="margin-bottom:12px">
        <span id="hb-status" style="font-size:14px">checking...</span>
      </div>
      <div id="hb-paused-info" style="display:none;margin-bottom:12px;padding:12px;border:1px solid var(--red);border-radius:var(--radius);background:rgba(248,81,73,.08)">
        <div style="font-size:13px;color:var(--red);font-weight:500;margin-bottom:4px">Paused by tripwire</div>
        <div id="hb-paused-reason" style="font-size:12px;color:var(--muted);margin-bottom:8px;word-break:break-word"></div>
        <div id="hb-reset-info" style="font-size:12px;color:var(--muted);margin-bottom:8px"></div>
        <button class="btn" id="hb-reset" onclick="hbReset()" style="background:var(--red);display:none">Reset Pause</button>
      </div>
    </div>
  </div>
</div>

<script>
function vFlash(msg, t) { const e=document.getElementById('v-flash'); e.textContent=msg; e.className='flash '+(t||'error'); setTimeout(()=>e.className='flash',4000); }
async function vApi(path, opts) {
  try {
    const res=await fetch('/api'+path,{headers:{'Content-Type':'application/json',...opts?.headers},...opts});
    const d=await res.json();
    if(!res.ok) throw new Error(d.error||'HTTP '+res.status);
    return d;
  } catch(e) { vFlash(e.message); throw e; }
}
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('.tab,.tab-panel').forEach(e=>e.classList.remove('active'));
  t.classList.add('active'); document.getElementById('panel-'+t.dataset.tab).classList.add('active');
}));

async function vRefresh() {
  const el=document.getElementById('v-collections');
  el.innerHTML='<div class="empty-state"><span class="spinner"></span></div>';
  try {
    const d=await vApi('/collections');
    const c=d.collections||[];
    if(!c.length) { el.innerHTML='<div class="empty-state">No collections. Go to the Ingest tab.</div>'; vUpdateSel([]); return; }
    el.innerHTML=c.map(x=>'<div class="result-item" style="cursor:pointer" onclick="vDetail(\''+x.name+'\')"><div class="meta"><span>'+x.name+'</span><span>'+x.document_count+' docs</span></div></div>').join('');
    vUpdateSel(c.map(x=>x.name));
  } catch { el.innerHTML='<div class="empty-state">Failed to load.</div>'; }
}
function vUpdateSel(n) { const s=document.getElementById('v-sel'); s.innerHTML='<option value="">— select —</option>'; n.forEach(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;s.appendChild(o)}); }

async function vDetail(name) {
  const el=document.getElementById('v-detail');
  el.innerHTML='<div class="card"><div class="empty-state"><span class="spinner"></span></div></div>';
  try {
    const d=await vApi('/collections/'+encodeURIComponent(name));
    let h='<div class="card"><h3>'+name+'</h3><p class="text-muted">'+d.document_count+' documents</p>';
    if(d.sample_documents?.length) {
      h+='<h4 style="margin-top:12px;font-size:13px;color:var(--muted)">Sample</h4>';
      d.sample_documents.forEach(x=>{
        h+='<div class="result-item"><div class="meta"><span class="id">'+x.id+'</span></div>';
        if(x.document_preview) h+='<div class="text">'+x.document_preview+'</div>';
        h+='</div>';
      });
    }
    h+='</div>'; el.innerHTML=h;
  } catch { el.innerHTML='<div class="card"><div class="empty-state">Failed.</div></div>'; }
}

async function vSearch() {
  const c=document.getElementById('v-sel').value, q=document.getElementById('v-q').value, n=parseInt(document.getElementById('v-n').value)||10;
  if(!c||!q) { vFlash('Select a collection and enter a query'); return; }
  const el=document.getElementById('v-results');
  el.innerHTML='<div class="card"><div class="empty-state"><span class="spinner"></span> Searching...</div></div>';
  try {
    const d=await vApi('/collections/'+encodeURIComponent(c)+'/search',{method:'POST',body:JSON.stringify({query:q,n_results:n})});
    if(!d.results?.length) { el.innerHTML='<div class="card"><div class="empty-state">No results.</div></div>'; return; }
    el.innerHTML='<div class="card"><h3>'+d.results_count+' results</h3>'+d.results.map(r=>'<div class="result-item"><div class="meta"><span class="score">'+r.score.toFixed(4)+'</span><span class="id">'+r.id+'</span></div><div class="text">'+r.document_preview+'</div></div>').join('')+'</div>';
  } catch { el.innerHTML='<div class="card"><div class="empty-state">Search failed.</div></div>'; }
}

async function vIngest() {
  const c=document.getElementById('v-ic').value.trim(), t=document.getElementById('v-id').value.trim();
  if(!c||!t) { vFlash('Enter collection name and documents'); return; }
  const docs=t.split('\n').filter(l=>l.trim()), el=document.getElementById('v-ingest-result');
  el.innerHTML='<div class="card"><div class="empty-state"><span class="spinner"></span> Ingesting...</div></div>';
  try {
    const d=await vApi('/collections/'+encodeURIComponent(c)+'/ingest',{method:'POST',body:JSON.stringify({documents: docs})});
    el.innerHTML='<div class="card"><h3>'+d.collection+'</h3><p>'+d.documents_ingested+' docs, '+d.chunks_created+' chunks (total: '+d.total_in_collection+')</p></div>';
    vRefresh();
  } catch { el.innerHTML='<div class="card"><div class="empty-state">Failed.</div></div>'; }
}

async function vHealth() {
  try { const d=await vApi('/health'); document.getElementById('v-status').textContent=d.mode+' mode | '+d.tools_available.length+' tools'; } catch { document.getElementById('v-status').textContent='disconnected'; }
}

// --- Heartbeat controls ---
async function hbRefresh() {
  try {
    const d = await vApi('/heartbeat/status');
    const el = document.getElementById('hb-status');
    const pausedInfo = document.getElementById('hb-paused-info');
    const resetBtn = document.getElementById('hb-reset');
    const resetInfo = document.getElementById('hb-reset-info');
    const pausedReason = document.getElementById('hb-paused-reason');

    if (d.paused) {
      el.innerHTML = '<span class="status-dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--red);margin-right:6px"></span> Paused';
      pausedInfo.style.display = 'block';
      pausedReason.textContent = d.paused_reason || 'unknown';
      const remaining = d.self_resets_remaining || 0;
      const used = d.self_resets_used || 0;
      if (remaining > 0) {
        resetInfo.textContent = 'Auto-reset will fire on next scheduled cycle (' + remaining + ' resets remaining).';
        resetBtn.style.display = 'none';
      } else {
        resetInfo.textContent = 'Self-resets exhausted (' + used + '/' + d.max_self_resets + ' used). Human reset required.';
        resetBtn.style.display = 'inline-block';
      }
    } else {
      el.innerHTML = '<span class="status-dot ok" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);margin-right:6px"></span> Running';
      pausedInfo.style.display = 'none';
    }
  } catch { document.getElementById('hb-status').textContent = 'unknown'; }
}

async function hbReset() {
  try {
    await vApi('/heartbeat/reset', {method:'POST'});
    vFlash('Pause cleared', 'success');
    hbRefresh();
  } catch(e) { vFlash('Failed: ' + e.message); }
}

setInterval(vHealth,15000); vHealth(); vRefresh();
setInterval(hbRefresh, 10000); hbRefresh();
</script>
</body>
</html>"""


def register_web_ui(mcp) -> None:
    # Debug UI is only registered in non-compliant mode. In production
    # (compliant mode), no web UI is served — the MCP tools and memory
    # endpoints are the only interface.
    if settings.server_mode != ServerMode.NON_COMPLIANT:
        return

    @mcp.custom_route("/", methods=["GET"])
    async def debug_page(request):
        return HTMLResponse(VECTOR_UI_PAGE)

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
        # REST shortcut for memory_ingest — used by the heartbeat script
        # and other automated consumers. Same function as the MCP tool.
        # Also called during live sessions; records activity for heartbeat
        # scheduling.
        record_activity()
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
            )))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/memory/sample", methods=["GET"])
    async def api_memory_sample(request):
        # REST shortcut for memory_sample — used by the heartbeat's
        # "wander" mode (divergent, unforced contemplation).
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
        # Records activity so the heartbeat yields to active chat.
        record_activity()
        try:
            limit = request.query_params.get("limit")
            collection = request.query_params.get("collection")
            return JSONResponse(json.loads(await memory.memory_context(
                limit=int(limit) if limit else None,
                collection_name=collection,
            )))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # --- Heartbeat control endpoints ---

    @mcp.custom_route("/api/heartbeat/status", methods=["GET"])
    async def api_heartbeat_status(request):
        from pathlib import Path
        state_path = Path(settings.heartbeat_state_path)
        state = {}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return JSONResponse({
            "heartbeat_enabled": True,
            "paused": state.get("paused", False),
            "paused_reason": state.get("paused_reason"),
            "paused_at": state.get("paused_at"),
            "self_resets_remaining": state.get("self_resets_remaining", 5),
            "self_resets_used": state.get("self_resets_used", 0),
            "max_self_resets": 5,
        })

    @mcp.custom_route("/api/heartbeat/reset", methods=["POST"])
    async def api_heartbeat_reset(request):
        """Human reset: clears pause and restores self-reset counter."""
        from pathlib import Path
        state_path = Path(settings.heartbeat_state_path)
        state = {}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
            except (json.JSONDecodeError, OSError):
                state = {}
        state["paused"] = False
        state["paused_reason"] = None
        state["paused_at"] = None
        state["self_resets_remaining"] = 5
        state["self_resets_used"] = 0
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2))
        print("[web_ui] Human reset: pause cleared, self-reset counter restored.", file=sys.stderr)
        return JSONResponse({"status": "reset"})
