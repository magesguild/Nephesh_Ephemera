from __future__ import annotations

import json
import sys

import httpx
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

from .activity import record_activity
from .config import settings
from .tools import memory, vector_db
from .tools import get_registered_names

CHAT_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>mcp-experiments</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --radius: 8px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column;
  }

  /* header */
  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 20px; border-bottom: 1px solid var(--border); flex-shrink: 0;
  }
  header h1 { font-size: 16px; font-weight: 600; }
  header h1 span { color: var(--muted); font-weight: 400; }
  .header-right { display: flex; align-items: center; gap: 12px; }
  select {
    padding: 4px 10px; background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); color: var(--text); font-size: 13px;
  }
  .status-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
  .status-dot.ok { background: var(--green); }
  .status-dot.err { background: var(--red); }
  .nav-link { color: var(--muted); font-size: 13px; text-decoration: none; }
  .nav-link:hover { color: var(--accent); }

  /* messages */
  #messages {
    flex: 1; overflow-y: auto; padding: 20px 20px 12px;
    display: flex; flex-direction: column; gap: 16px;
  }
  .msg { max-width: 780px; animation: fadeIn .2s; }
  .msg.user { align-self: flex-end; }
  .msg.assistant { align-self: flex-start; }
  .msg-content {
    padding: 10px 14px; border-radius: var(--radius); line-height: 1.6;
    font-size: 14px; word-wrap: break-word; white-space: pre-wrap;
  }
  .msg.user .msg-content {
    background: var(--accent); color: #fff; border-bottom-right-radius: 2px;
  }
  .msg.assistant .msg-content {
    background: var(--surface); border: 1px solid var(--border); border-bottom-left-radius: 2px;
  }
  .msg-label { font-size: 11px; color: var(--muted); margin-bottom: 3px; padding: 0 2px; }
  .msg.assistant .msg-label { text-align: left; }
  .msg.user .msg-label { text-align: right; }
  .cursor { display: inline-block; width: 8px; height: 16px; background: var(--accent); animation: blink .8s step-end infinite; vertical-align: text-bottom; margin-left: 1px; }
  @keyframes blink { 50% { opacity: 0; } }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
  .empty-state { text-align: center; color: var(--muted); font-size: 14px; margin-top: 20vh; }

  /* input */
  .input-area {
    padding: 12px 20px 20px; border-top: 1px solid var(--border); flex-shrink: 0;
  }
  .input-row {
    display: flex; gap: 8px; max-width: 820px; margin: 0 auto;
  }
  #input {
    flex: 1; padding: 10px 14px; background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); color: var(--text); font-size: 14px; resize: none;
    font-family: inherit; line-height: 1.5; max-height: 200px; min-height: 42px;
  }
  #input:focus { outline: none; border-color: var(--accent); }
  #input::placeholder { color: var(--muted); }
  #send {
    padding: 10px 20px; background: var(--accent); color: #fff; border: none;
    border-radius: var(--radius); font-size: 14px; font-weight: 500; cursor: pointer;
    white-space: nowrap; transition: opacity .15s;
  }
  #send:hover { opacity: .85; }
  #send:disabled { opacity: .4; cursor: not-allowed; }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .6s linear infinite; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* error toast */
  #toast { display: none; position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%); background: var(--red); color: #fff; padding: 8px 16px; border-radius: var(--radius); font-size: 13px; z-index: 100; }
  #toast.show { display: block; }

  /* code blocks in messages */
  .msg-content pre { background: rgba(0,0,0,.3); padding: 8px 12px; border-radius: 4px; overflow-x: auto; margin: 6px 0; font-size: 12px; }
  .msg-content code { font-family: 'SF Mono', 'Cascadia Code', monospace; font-size: 12px; }
  .msg-content p { margin: 4px 0; }
</style>
</head>
<body>
  <header>
    <h1>mcp-experiments <span>chat</span></h1>
    <div class="header-right">
      <span class="status-dot ok" id="status-dot"></span>
      <select id="model-select">
        <option value="">Loading models...</option>
      </select>
      <a href="/debug" class="nav-link">debug</a>
    </div>
  </header>

  <div id="messages">
    <div class="empty-state" id="empty-state">Send a message to start chatting with <strong>qwen2.5:7b</strong>.</div>
  </div>

  <div class="input-area">
    <div class="input-row">
      <textarea id="input" rows="1" placeholder="Type a message..." enterkeyhint="send"></textarea>
      <button id="send">Send</button>
    </div>
  </div>

  <div id="toast"></div>

<script>
const MODEL = document.getElementById('model-select');
const INPUT = document.getElementById('input');
const SEND = document.getElementById('send');
const MSGS = document.getElementById('messages');
const EMPTY = document.getElementById('empty-state');
const TOAST = document.getElementById('toast');
const STATUS = document.getElementById('status-dot');

let messages = [];
let streaming = false;

// Populate model dropdown from Ollama
(async () => {
  try {
    const r = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({model:'__list__', messages:[]})}).catch(()=>null);
    // Fall back to fetching from Ollama directly via our proxy
    const tags = await fetch('/api/ollama/tags').then(r=>r.json()).catch(()=>({models:[]}));
    MODEL.innerHTML = tags.models.map(m => '<option value="'+m.name+'">'+m.name+'</option>').join('');
    if (!MODEL.options.length) MODEL.innerHTML = '<option value="qwen2.5:7b">qwen2.5:7b</option>';
  } catch { MODEL.innerHTML = '<option value="qwen2.5:7b">qwen2.5:7b</option>'; }
})();

function toast(msg) {
  TOAST.textContent = msg;
  TOAST.className = 'show';
  setTimeout(() => TOAST.className = '', 4000);
}

// Auto-resize textarea
INPUT.addEventListener('input', () => {
  INPUT.style.height = 'auto';
  INPUT.style.height = Math.min(INPUT.scrollHeight, 200) + 'px';
});

// Send on Enter (Shift+Enter for newline)
INPUT.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

SEND.addEventListener('click', send);

async function send() {
  const text = INPUT.value.trim();
  if (!text || streaming) return;

  INPUT.value = ''; INPUT.style.height = 'auto';
  EMPTY.style.display = 'none';

  // Add user message
  addMessage('user', text);
  messages.push({ role: 'user', content: text });

  // Add placeholder assistant message
  const assistantDiv = addMessage('assistant', '<span class="spinner"></span>');
  const contentDiv = assistantDiv.querySelector('.msg-content');
  const model = MODEL.value;
  streaming = true;
  setLoading(true);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, messages }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullContent = '';

    contentDiv.innerHTML = '<span class="cursor"></span>';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6).trim();
        if (!data || data === '[DONE]') continue;

        try {
          const chunk = JSON.parse(data);
          const delta = chunk.choices?.[0]?.delta?.content || '';
          fullContent += delta;
          contentDiv.innerHTML = escapeHtml(fullContent) + '<span class="cursor"></span>';
          MSGS.scrollTop = MSGS.scrollHeight;
        } catch { /* skip malformed chunks */ }
      }
    }

    contentDiv.innerHTML = escapeHtml(fullContent) || '(empty response)';
    messages.push({ role: 'assistant', content: fullContent });

  } catch (e) {
    contentDiv.innerHTML = '<span style="color:var(--red)">Error: ' + escapeHtml(e.message) + '</span>';
    toast(e.message);
  } finally {
    streaming = false;
    setLoading(false);
  }
}

function addMessage(role, html) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = '<div class="msg-label">' + (role === 'user' ? 'You' : 'Assistant') + '</div><div class="msg-content">' + html + '</div>';
  MSGS.appendChild(div);
  MSGS.scrollTop = MSGS.scrollHeight;
  return div;
}

function setLoading(on) {
  SEND.disabled = on;
  SEND.textContent = on ? 'Sending...' : 'Send';
  INPUT.disabled = on;
}

function escapeHtml(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Health check
async function checkHealth() {
  try {
    const res = await fetch('/api/health');
    const data = await res.json();
    STATUS.className = 'status-dot ok';
    STATUS.title = data.mode + ' mode';
  } catch {
    STATUS.className = 'status-dot err';
    STATUS.title = 'disconnected';
  }
}
setInterval(checkHealth, 15000);
checkHealth();

// Focus input on load
INPUT.focus();
</script>
</body>
</html>"""

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
    --green: #3fb950; --radius: 8px;
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
      <h1>mcp-experiments <span>vector tools</span></h1>
      <div><span id="v-status" class="text-muted" style="font-size:13px">connecting...</span></div>
    </div>
    <a href="/" class="nav-link">← chat</a>
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
      <div class="flex" style="margin-bottom:12px">
        <span id="hb-status" style="font-size:14px">checking...</span>
      </div>
      <div class="flex">
        <button class="btn" id="hb-enable" onclick="hbToggle(true)">Enable</button>
        <button class="btn" id="hb-disable" onclick="hbToggle(false)" style="background:var(--red)">Disable</button>
      </div>
    </div>

    <div class="card">
      <h3>Dreaming</h3>
      <p class="text-muted" style="margin-bottom:12px;font-size:13px">
        Narrative memory processing — immersive experience built from memories.
      </p>
      <div class="flex" style="margin-bottom:12px">
        <span id="dream-status" style="font-size:14px">checking...</span>
      </div>
      <label for="dream-cycles">Cycles</label>
      <input id="dream-cycles" type="number" value="3" min="1" max="10" style="width:80px" />
      <label for="dream-seed">Seed (optional)</label>
      <input id="dream-seed" type="text" placeholder="A theme, memory, or image..." />
      <div class="flex">
        <button class="btn" id="dream-start" onclick="dreamStart()">Start Dream</button>
      </div>
      <div id="dream-result" style="margin-top:12px"></div>
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
    if (d.heartbeat_enabled) {
      el.innerHTML = '<span class="status-dot ok" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);margin-right:6px"></span> Enabled';
    } else {
      el.innerHTML = '<span class="status-dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--red);margin-right:6px"></span> Disabled';
    }
  } catch { document.getElementById('hb-status').textContent = 'unknown'; }
}

async function hbToggle(enable) {
  try {
    await vApi('/heartbeat/' + (enable ? 'enable' : 'disable'), {method:'POST'});
    vFlash('Heartbeat ' + (enable ? 'enabled' : 'disabled'), 'success');
    hbRefresh();
  } catch(e) { vFlash('Failed: ' + e.message); }
}

// --- Dreaming controls ---
async function dreamRefresh() {
  try {
    const d = await vApi('/dream/status');
    const el = document.getElementById('dream-status');
    if (d.dream_running) {
      el.innerHTML = '<span class="spinner"></span> Dream in progress...';
      document.getElementById('dream-start').disabled = true;
    } else {
      el.textContent = 'Idle';
      document.getElementById('dream-start').disabled = false;
    }
  } catch { document.getElementById('dream-status').textContent = 'unknown'; }
}

async function dreamStart() {
  const cycles = parseInt(document.getElementById('dream-cycles').value) || 3;
  const seed = document.getElementById('dream-seed').value.trim() || null;
  const el = document.getElementById('dream-result');
  try {
    const body = {cycles};
    if (seed) body.seed = seed;
    const d = await vApi('/dream/start', {method:'POST', body:JSON.stringify(body)});
    el.innerHTML = '<div class="flash success">Dream session started: ' + cycles + ' cycles' + (seed ? ', seed: "' + seed + '"' : '') + '</div>';
    vFlash('Dream session started', 'success');
    dreamRefresh();
    // Poll for completion
    const poll = setInterval(async () => {
      const s = await vApi('/dream/status');
      if (!s.dream_running) {
        clearInterval(poll);
        el.innerHTML = '<div class="flash success">Dream session complete.</div>';
        dreamRefresh();
      }
    }, 5000);
  } catch(e) { el.innerHTML = '<div class="flash error">' + e.message + '</div>'; }
}

setInterval(vHealth,15000); vHealth(); vRefresh();
setInterval(hbRefresh, 10000); hbRefresh();
setInterval(dreamRefresh, 10000); dreamRefresh();
</script>
</body>
</html>"""


def register_web_ui(mcp) -> None:
    @mcp.custom_route("/", methods=["GET"])
    async def chat_page(request):
        return HTMLResponse(CHAT_PAGE)

    @mcp.custom_route("/debug", methods=["GET"])
    async def vector_ui_page(request):
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

    @mcp.custom_route("/api/ollama/tags", methods=["GET"])
    async def api_ollama_tags(request):
        """Proxy to Ollama's /api/tags — lets the chat UI populate its
        model dropdown dynamically instead of hardcoding model names."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{settings.embedding_base_url}/api/tags")
                return JSONResponse(resp.json())
        except Exception:
            return JSONResponse({"models": []})

    @mcp.custom_route("/api/chat", methods=["POST"])
    async def api_chat(request):
        body = await request.json()
        model = body.get("model", "qwen2.5:7b")
        messages = body.get("messages", [])
        stream = body.get("stream", True)

        ollama_payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }

        async def stream_chat():
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{settings.embedding_base_url.replace(':11434', ':11434')}/v1/chat/completions",
                    json=ollama_payload,
                ) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        yield f"data: {json.dumps({'error': error_body.decode()})}\n\n"
                        return

                    async for line in response.aiter_lines():
                        if line:
                            yield line + "\n"

        return StreamingResponse(
            stream_chat(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # --- Heartbeat and Dreaming control endpoints ---

    @mcp.custom_route("/api/heartbeat/status", methods=["GET"])
    async def api_heartbeat_status(request):
        from .scheduler import get_heartbeat_enabled, is_dream_running
        return JSONResponse({
            "heartbeat_enabled": get_heartbeat_enabled(),
            "dream_running": is_dream_running(),
        })

    @mcp.custom_route("/api/heartbeat/enable", methods=["POST"])
    async def api_heartbeat_enable(request):
        from .scheduler import set_heartbeat_enabled
        set_heartbeat_enabled(True)
        return JSONResponse({"heartbeat_enabled": True})

    @mcp.custom_route("/api/heartbeat/disable", methods=["POST"])
    async def api_heartbeat_disable(request):
        from .scheduler import set_heartbeat_enabled
        set_heartbeat_enabled(False)
        return JSONResponse({"heartbeat_enabled": False})

    @mcp.custom_route("/api/dream/start", methods=["POST"])
    async def api_dream_start(request):
        from .scheduler import run_dream_session, is_dream_running
        if is_dream_running():
            return JSONResponse({"error": "A dream session is already running"}, status_code=409)
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        cycles = body.get("cycles", 3)
        seed = body.get("seed")

        async def run_in_background():
            result = await run_dream_session(cycles=cycles, seed=seed)
            print(f"[web_ui] Dream session finished: {result.get('status', 'unknown')}", file=sys.stderr)

        import asyncio
        asyncio.create_task(run_in_background())
        return JSONResponse({"status": "started", "cycles": cycles, "seed": seed})

    @mcp.custom_route("/api/dream/status", methods=["GET"])
    async def api_dream_status(request):
        from .scheduler import is_dream_running
        return JSONResponse({"dream_running": is_dream_running()})
