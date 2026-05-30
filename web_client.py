"""
Optimus-3 Web Client
====================

A single-port Flask app that provides a browser UI for the Optimus-3 GUI server
(gui_server.py / FastAPI on :9500) and reverse-proxies everything to it:

  * REST endpoints  ->  proxied under  /api/*   to  http://SERVER_HOST:SERVER_PORT/*
  * Live POV frames ->  proxied WebSocket  /ws/obs  <->  ws://SERVER_HOST:SERVER_PORT/ws/obs

Because the browser talks ONLY to this Flask app, you only need to forward a
single port over SSH. In VS Code, open the "Ports" panel and forward CLIENT_PORT
(default 7860), then open the forwarded URL in your browser.

Run:
    python web_client.py
    # or: CLIENT_PORT=7860 SERVER_HOST=127.0.0.1 SERVER_PORT=9500 python web_client.py
"""

import os

import requests
import simple_websocket
from flask import Flask, Response, jsonify, request
from flask_sock import Sock


SERVER_HOST = os.environ.get("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "9500"))
CLIENT_PORT = int(os.environ.get("CLIENT_PORT", "7860"))
SERVER_BASE = f"http://{SERVER_HOST}:{SERVER_PORT}"
SERVER_WS = f"ws://{SERVER_HOST}:{SERVER_PORT}/ws/obs"

app = Flask(__name__)
sock = Sock(app)

# Keep proxied requests snappy; model calls (planning/action) can be slow.
PROXY_TIMEOUT = (5, 600)  # (connect, read) seconds


# --------------------------------------------------------------------------- #
# REST reverse proxy:  /api/<path>  ->  SERVER_BASE/<path>
# --------------------------------------------------------------------------- #
@app.route("/api/<path:subpath>", methods=["GET", "POST"])
def api_proxy(subpath):
    url = f"{SERVER_BASE}/{subpath}"
    try:
        if request.method == "POST":
            resp = requests.post(
                url,
                json=request.get_json(silent=True),
                params=request.args,
                timeout=PROXY_TIMEOUT,
            )
        else:
            resp = requests.get(url, params=request.args, timeout=PROXY_TIMEOUT)
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "detail": f"Cannot reach Optimus-3 server at {SERVER_BASE}. Is gui_server.py running?"}), 502
    except requests.exceptions.ReadTimeout:
        return jsonify({"status": "error", "detail": "Server timed out (the model may still be loading / running)."}), 504

    excluded = {"content-encoding", "transfer-encoding", "connection", "content-length"}
    headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
    return Response(resp.content, status=resp.status_code, headers=headers)


# --------------------------------------------------------------------------- #
# WebSocket reverse proxy:  browser <-> this app <-> upstream /ws/obs
# The upstream server pushes base64-PNG frames; we relay each frame to the
# browser. We don't need to send anything upstream.
# --------------------------------------------------------------------------- #
@sock.route("/ws/obs")
def ws_obs(ws):
    try:
        upstream = simple_websocket.Client(SERVER_WS)
    except Exception as e:
        try:
            ws.send(f"__ERROR__ cannot connect to upstream websocket: {e}")
        except Exception:
            pass
        return

    try:
        while True:
            frame = upstream.receive(timeout=30)
            if frame is None:
                # No frame within timeout; send a ping-ish noop to keep the
                # browser socket alive and detect disconnects.
                try:
                    ws.send("")
                except Exception:
                    break
                continue
            ws.send(frame)
    except (simple_websocket.ConnectionClosed, Exception):
        pass
    finally:
        try:
            upstream.close()
        except Exception:
            pass


@app.route("/")
def index():
    return INDEX_HTML


# --------------------------------------------------------------------------- #
# Single-page UI
# --------------------------------------------------------------------------- #
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Optimus-3 Web Client</title>
<style>
  :root { --bg:#0f1419; --panel:#1a2129; --panel2:#222b35; --txt:#e6edf3; --muted:#8b98a5;
          --accent:#3fb950; --accent2:#388bfd; --warn:#d29922; --danger:#f85149; --border:#30363d; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         background:var(--bg); color:var(--txt); height:100vh; display:flex; flex-direction:column; }
  header { padding:10px 16px; background:var(--panel); border-bottom:1px solid var(--border);
           display:flex; align-items:center; gap:12px; }
  header h1 { font-size:16px; margin:0; font-weight:600; letter-spacing:.3px; }
  .badge { font-size:12px; padding:3px 8px; border-radius:999px; background:var(--panel2); color:var(--muted); }
  #serverDot { width:9px; height:9px; border-radius:50%; background:var(--danger); display:inline-block; margin-right:6px; }
  #serverDot.ok { background:var(--accent); }
  main { flex:1; display:flex; min-height:0; }
  .left { flex:1.2; display:flex; flex-direction:column; padding:14px; gap:10px; min-width:0; }
  .right { flex:1; display:flex; flex-direction:column; border-left:1px solid var(--border); min-width:340px; }
  .view-wrap { flex:1; background:#000; border:1px solid var(--border); border-radius:8px;
               display:flex; align-items:center; justify-content:center; overflow:hidden; min-height:0; }
  #view { max-width:100%; max-height:100%; image-rendering:pixelated; }
  .view-placeholder { color:var(--muted); font-size:14px; text-align:center; padding:20px; }
  .controls { display:flex; flex-wrap:wrap; gap:8px; }
  button { background:var(--panel2); color:var(--txt); border:1px solid var(--border); border-radius:6px;
           padding:8px 12px; font-size:13px; cursor:pointer; transition:.12s; }
  button:hover:not(:disabled) { border-color:var(--accent2); }
  button:disabled { opacity:.5; cursor:not-allowed; }
  select { background:var(--panel2); color:var(--txt); border:1px solid var(--border); border-radius:6px;
           padding:7px 8px; font-size:12.5px; cursor:pointer; }
  select:disabled { opacity:.5; cursor:not-allowed; }
  button.primary { background:var(--accent2); border-color:var(--accent2); color:#fff; }
  button.go { background:var(--accent); border-color:var(--accent); color:#04210c; font-weight:600; }
  button.warn { background:var(--warn); border-color:var(--warn); color:#241a02; }
  button.danger { background:transparent; border-color:var(--danger); color:var(--danger); }
  .row { display:flex; gap:8px; align-items:center; }
  .log { flex:1; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:10px; }
  .msg { padding:9px 12px; border-radius:8px; font-size:13.5px; line-height:1.45; white-space:pre-wrap; word-break:break-word; }
  .msg .who { font-size:11px; color:var(--muted); margin-bottom:3px; text-transform:uppercase; letter-spacing:.5px; }
  .msg.user { background:#1f3a5f; align-self:flex-end; max-width:88%; }
  .msg.bot  { background:var(--panel2); align-self:flex-start; max-width:92%; }
  .msg.sys  { background:transparent; color:var(--muted); font-style:italic; align-self:center; font-size:12px; }
  .msg.tag  { font-size:11px; }
  .msg.think { background:#161b22; border-left:3px solid var(--accent2); color:var(--muted);
               font-style:italic; align-self:flex-start; max-width:92%; font-size:12.5px; }
  .inputbar { padding:12px; border-top:1px solid var(--border); display:flex; flex-direction:column; gap:8px; }
  .tasks { display:flex; flex-wrap:wrap; gap:6px; }
  .tasks label { font-size:12.5px; display:flex; align-items:center; gap:4px; background:var(--panel2);
                 padding:5px 9px; border-radius:6px; border:1px solid var(--border); cursor:pointer; }
  .tasks input { accent-color:var(--accent2); }
  textarea { width:100%; resize:none; background:var(--bg); color:var(--txt); border:1px solid var(--border);
             border-radius:6px; padding:9px; font-size:14px; font-family:inherit; }
  .hint { font-size:11.5px; color:var(--muted); }
  .spin { display:inline-block; width:12px; height:12px; border:2px solid var(--muted); border-top-color:transparent;
          border-radius:50%; animation:s 0.8s linear infinite; vertical-align:middle; }
  @keyframes s { to { transform:rotate(360deg); } }
</style>
</head>
<body>
<header>
  <h1>🟢 Optimus-3</h1>
  <span class="badge"><span id="serverDot"></span><span id="serverTxt">connecting…</span></span>
  <span class="badge" id="streamTxt">stream: off</span>
  <span class="badge" id="fpsTxt" title="Frames received from the server per second">0 fps</span>
  <span style="flex:1"></span>
  <select id="resSel" title="Render resolution — higher is sharper but lowers fps (changing it reboots the world, ~40s)">
    <option value="640x360">640×360 · ~27 fps</option>
    <option value="960x540">960×540 · ~20 fps</option>
    <option value="1280x720" selected>1280×720 HD · ~14 fps</option>
    <option value="1920x1080">1920×1080 FHD</option>
  </select>
  <button id="btnReset" class="danger" title="Reset the Minecraft environment (random respawn)">🔄 Reset</button>
  <button id="btnPause" class="warn">⏸️ Pause</button>
  <button id="btnResume">▶️ Resume</button>
</header>
<main>
  <div class="left">
    <div class="view-wrap">
      <canvas id="view" style="display:none"></canvas>
      <div id="viewPh" class="view-placeholder">Waiting for the first frame from the agent…<br/>
        <span class="hint">(the server boots Minecraft + loads the model on first start — this can take a couple of minutes)</span></div>
    </div>
    <div class="controls">
      <button id="btnAction" class="go" title="Execute one action step of the current plan">🖱️ Action (step)</button>
      <button id="btnAuto" title="Repeatedly run Action until the task reports success">⏩ Auto-run</button>
      <span class="hint">Action rule: run <b>Planning</b> first, then click Action (or Auto-run).</span>
    </div>
  </div>
  <div class="right">
    <div class="log" id="log"></div>
    <div class="inputbar">
      <div class="tasks" id="tasks">
        <label><input type="radio" name="task" value="planning" checked>🧠 Planning</label>
        <label><input type="radio" name="task" value="captioning">🖼️ Captioning</label>
        <label><input type="radio" name="task" value="embodied_qa">❓ EQA</label>
        <label><input type="radio" name="task" value="grounding">🎯 Grounding</label>
        <label style="margin-left:auto" title="Show the model's <think> reasoning"><input type="checkbox" id="showThink">💭 Show thinking</label>
      </div>
      <textarea id="input" rows="2" placeholder="e.g. get a diamond sword   /   describe this view   /   how many trees   /   locate the cow"></textarea>
      <div class="row">
        <button id="btnSend" class="primary" style="flex:1">Send</button>
        <span class="hint">Enter = send · Shift+Enter = newline</span>
      </div>
    </div>
  </div>
</main>

<script>
const $ = s => document.querySelector(s);
const logEl = $('#log');
let busy = false, autoRunning = false;

function addMsg(text, cls, who) {
  const m = document.createElement('div');
  m.className = 'msg ' + cls;
  if (who) { const w = document.createElement('div'); w.className='who'; w.textContent=who; m.appendChild(w); }
  const t = document.createElement('div'); t.textContent = text; m.appendChild(t);
  logEl.appendChild(m); logEl.scrollTop = logEl.scrollHeight;
  return m;
}
function setBusy(b) {
  busy = b;
  ['#btnSend','#btnAction','#btnAuto','#btnReset','#btnPause','#btnResume'].forEach(s=>{
    if (s !== '#btnAuto') $(s).disabled = b;
  });
}

async function api(path, opts) {
  const r = await fetch('/api/' + path, opts);
  let data; try { data = await r.json(); } catch(e){ data = {}; }
  if (!r.ok) throw new Error(data.detail || ('HTTP ' + r.status));
  return data;
}
function post(path, body) {
  return api(path, {method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify(body||{})});
}

// ---- live stream over the proxied websocket ----
function connectStream() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/obs`);
  ws.onopen = () => { $('#streamTxt').textContent = 'stream: live'; };
  ws.onclose = () => { $('#streamTxt').textContent = 'stream: off'; setTimeout(connectStream, 2000); };
  ws.onerror = () => { try { ws.close(); } catch(e){} };
  ws.onmessage = ev => {
    if (!ev.data || ev.data.startsWith('__ERROR__')) return;
    showFrame(ev.data);
  };
}

// Render frames to a canvas (double-buffered: the canvas keeps the previous
// frame until the next is decoded, so there is no blank-flash flicker that a
// plain <img> src-swap causes). Frames are coalesced — if several arrive while
// one is decoding, only the most recent is painted.
let _ctx = null, _drawing = false, _nextB64 = null;
function showFrame(b64) {
  markFrame();                 // count every frame received from the server
  _nextB64 = b64;
  if (!_drawing) _paint();
}

// ---- received-frames-per-second counter (rolling 1s window) ----
let _frameTimes = [];
function markFrame() { _frameTimes.push(performance.now()); }
setInterval(() => {
  const now = performance.now();
  while (_frameTimes.length && now - _frameTimes[0] > 1000) _frameTimes.shift();
  $('#fpsTxt').textContent = _frameTimes.length + ' fps';
}, 250);
function _paint() {
  if (_nextB64 == null) return;
  const b64 = _nextB64; _nextB64 = null; _drawing = true;
  const im = new Image();
  im.onload = () => {
    const cv = $('#view');
    if (cv.width !== im.naturalWidth) {
      cv.width = im.naturalWidth; cv.height = im.naturalHeight;
      // keep the resolution dropdown in sync with the actual server resolution
      const rs = document.getElementById('resSel');
      const v = im.naturalWidth + 'x' + im.naturalHeight;
      if (rs && [...rs.options].some(o => o.value === v)) { rs.value = v; rs.dataset.cur = v; }
    }
    if (!_ctx) _ctx = cv.getContext('2d');
    _ctx.drawImage(im, 0, 0);
    if (cv.style.display === 'none') { cv.style.display = 'block'; $('#viewPh').style.display = 'none'; }
    _drawing = false;
    if (_nextB64 != null) _paint();   // paint the latest queued frame, if any
  };
  im.onerror = () => { _drawing = false; };
  im.src = 'data:image/jpeg;base64,' + b64;
}

// The server only streams frames during actions/resets. Poll get_obs at a low
// rate so the view stays current while idle. Skipped during Auto-run, where the
// WebSocket already delivers frames far faster.
async function idlePoll() {
  if (!autoRunning) {
    try {
      const d = await api('get_obs');
      if (d && d.observation) showFrame(d.observation);
    } catch (e) { /* server down; health poll reports it */ }
  }
  setTimeout(idlePoll, 1000);
}

// ---- server health poll ----
async function pollHealth() {
  try {
    await api('status');
    $('#serverDot').classList.add('ok');
    $('#serverTxt').textContent = 'server: online';
  } catch(e) {
    $('#serverDot').classList.remove('ok');
    $('#serverTxt').textContent = 'server: offline';
  }
  setTimeout(pollHealth, 3000);
}

// The model emits raw "<think> reasoning </think> <answer> result </answer>"
// text and the server returns it verbatim. Show just the answer (or the text
// after the reasoning), stripped of tags, for a readable result. Does NOT
// affect execution — sub-tasks are parsed server-side from the answer.
function cleanResponse(text) {
  if (!text) return text;

  // PLANNING: the good plan is the first monotonically-increasing run of
  // "step N:" lines, which appears BEFORE </think>. The <answer> section is
  // often a degenerate repeat ("step 11:" over and over), so DON'T use it here —
  // scan the whole raw text and stop at the first reset/repeat.
  if (/step\s*\d+\s*:/i.test(text)) {
    const out = []; let last = 0, started = false;
    for (const ln of text.split('\n')) {
      const s = ln.trim();
      const m = s.match(/^step\s*(\d+)\s*:/i);
      if (m) {
        const n = parseInt(m[1], 10);
        if (n <= last) break;                 // numbering reset/repeat → tail junk
        last = n; started = true; out.push(s);
      } else if (!started && s && !/<\/?(think|answer)>/.test(s)) {
        out.push(s);                           // intro line(s) before the steps
      }
    }
    const cleaned = out.join('\n').trim();
    if (cleaned) return cleaned;
  }

  // NON-PLAN tasks (captioning / EQA / grounding): the clean result is the
  // <answer> section; fall back to text after </think>, then strip tags.
  let t = text;
  const a = t.lastIndexOf('<answer>');
  if (a !== -1) {
    t = t.slice(a + '<answer>'.length);
    const c = t.indexOf('</answer>');
    if (c !== -1) t = t.slice(0, c);
  } else {
    const k = t.lastIndexOf('</think>');
    if (k !== -1) t = t.slice(k + '</think>'.length);
  }
  t = t.replace(/<\/?(think|answer)>/g, '').trim();
  return t || text.trim();
}

function currentTask() { return document.querySelector('input[name=task]:checked').value; }
function showThinking() { const e = $('#showThink'); return e && e.checked; }
const TASK_LABEL = {planning:'Planning', captioning:'Captioning', embodied_qa:'Embodied QA', grounding:'Grounding', action:'Action'};

async function send() {
  if (busy) return;
  const text = $('#input').value.trim();
  const task = currentTask();
  if (!text) { addMsg('Type an instruction first.', 'sys'); return; }
  addMsg(text, 'user', TASK_LABEL[task]);
  $('#input').value = '';
  setBusy(true);
  const pending = addMsg('working… ', 'bot', 'Optimus-3');
  pending.querySelector('div:last-child').innerHTML = 'working… <span class="spin"></span>';
  try {
    const data = await post('send_text', {text, task});
    if (showThinking() && data.thinking) {
      const tm = addMsg(data.thinking, 'think', '💭 Thinking');
      logEl.insertBefore(tm, pending);   // place reasoning above the answer
    }
    pending.querySelector('div:last-child').textContent = cleanResponse(data.response) || '(no response)';
  } catch(e) {
    pending.querySelector('div:last-child').textContent = '⚠️ ' + e.message;
    pending.classList.remove('bot'); pending.classList.add('sys');
  } finally { setBusy(false); }
}

// Steps per Auto-run request. 1 = smooth one-step-per-request (best on a
// low-latency LAN/web connection). Raise it (e.g. 12) only over high-latency
// links like SSH, where batching amortizes round-trip latency at the cost of
// a bursty/uneven frame rate.
const AUTO_BATCH = 1;
async function actionStep(silent) {
  if (!silent) { if (busy) return null; setBusy(true); }
  try {
    const data = await post('send_text', {text:'', task:'action', steps: silent ? AUTO_BATCH : 1});
    const r = (data.response || '').trim();
    if (!silent) addMsg(r || '(step done)', 'bot tag', 'Action');
    return r;
  } catch(e) {
    addMsg('⚠️ ' + e.message, 'sys');
    return '__error__';
  } finally { if (!silent) setBusy(false); }
}

async function autoRun() {
  if (autoRunning) { autoRunning = false; return; }       // toggle off; loop exits
  autoRunning = true;
  // Lock the other controls once (not per step) to avoid flicker.
  ['#btnSend','#btnAction','#btnReset'].forEach(s => $(s).disabled = true);
  addMsg('Auto-run started. Executing the plan…', 'sys');
  let steps = 0, last = null, ended = 'stopped';
  while (autoRunning) {
    const r = await actionStep(true);
    steps++;
    // Log only when the current sub-task changes — not every step.
    if (r && r !== last && r !== 'success' && r !== '__error__' && r !== 'paused') {
      last = r;
      addMsg('▶ ' + r, 'bot tag', 'Sub-task');
    }
    if (steps % 5 === 0 || steps === 1) $('#btnAuto').textContent = `⏹️ Stop · ${steps}`;
    if (r === 'success') { ended = 'completed (success) ✅'; break; }
    if (r === '__error__') { ended = 'aborted on error'; break; }
    if (r === 'paused') { ended = 'paused'; break; }
    await new Promise(res => setTimeout(res, 0));          // yield only; no throttle
  }
  autoRunning = false;
  $('#btnAuto').textContent = '⏩ Auto-run';
  ['#btnSend','#btnAction','#btnReset'].forEach(s => $(s).disabled = false);
  addMsg(`Auto-run ${ended} after ${steps} step(s).`, 'sys');
}

$('#btnSend').onclick = send;
$('#btnAction').onclick = actionStep;
$('#btnAuto').onclick = autoRun;
$('#btnPause').onclick = async () => { try { await post('pause'); addMsg('Paused.', 'sys'); } catch(e){ addMsg('⚠️ '+e.message,'sys'); } };
$('#btnResume').onclick = async () => { try { await post('resume'); addMsg('Resumed.', 'sys'); } catch(e){ addMsg('⚠️ '+e.message,'sys'); } };
$('#btnReset').onclick = async () => {
  if (!confirm('Reset the Minecraft environment? The agent will respawn at a random location.')) return;
  setBusy(true);
  const p = addMsg('resetting environment… ', 'sys');
  try { await post('reset', {device:'cuda:0'}); p.textContent = 'Environment reset.'; }
  catch(e){ p.textContent = '⚠️ ' + e.message; }
  finally { setBusy(false); }
};
// Resolution selector — changing it recreates the env at the new render size.
const resSel = $('#resSel');
resSel.dataset.cur = resSel.value;
resSel.onchange = async () => {
  const [w, h] = resSel.value.split('x').map(Number);
  if (!confirm(`Switch render resolution to ${w}×${h}?\nThis reboots the Minecraft world (the agent respawns) and takes ~40s.`)) {
    resSel.value = resSel.dataset.cur; return;
  }
  setBusy(true); resSel.disabled = true;
  const p = addMsg(`Switching to ${w}×${h}… rebooting world (~40s)`, 'sys');
  try {
    await post('reset', {device: 'cuda:0', width: w, height: h});
    resSel.dataset.cur = resSel.value;
    p.textContent = `Resolution set to ${w}×${h}.`;
  } catch (e) {
    p.textContent = '⚠️ ' + e.message; resSel.value = resSel.dataset.cur;
  } finally { setBusy(false); resSel.disabled = false; }
};

$('#input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

// greeting
(async () => {
  try { const d = await api('initial_text'); addMsg(d.text.trim(), 'bot', 'Optimus-3'); }
  catch(e) { addMsg('Welcome to the Optimus-3 web client. Waiting for the server…', 'sys'); }
})();
connectStream();
pollHealth();
idlePoll();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print(f"Optimus-3 web client -> proxying {SERVER_BASE}")
    print(f"Open http://localhost:{CLIENT_PORT}  (forward port {CLIENT_PORT} in the VS Code 'Ports' panel)")
    app.run(host="0.0.0.0", port=CLIENT_PORT, threaded=True)
