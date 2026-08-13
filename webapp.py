import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from agent import get_config, run_with_messages, APIError
import agent
import rag

PORT = int(os.environ.get("AI_AGENT_PORT", "8080"))

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store">
<title>AI Services</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg-page: #e5dbc9;
    --bg: #f6f1e7;
    --bg-side: #efe7d8;
    --bg-input: #fffdf8;
    --border: #ddd0b4;
    --text: #2c2620;
    --muted: #8a7f6a;
    --accent: #3f5d45;
    --accent-ink: #fbf8f1;
    --danger: #9c4433;
  }
  html, body { height: 100%; }
  body {
    background: var(--bg-page);
    color: var(--text);
    font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Times New Roman", serif;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
    padding: 24px;
  }
  button { font-family: inherit; cursor: pointer; }

  .app {
    position: relative;
    display: flex;
    width: 100%;
    max-width: 1180px;
    height: 100%;
    max-height: 860px;
    border: 1px solid var(--border);
    box-shadow: 0 12px 40px rgba(44,38,32,0.12);
    background: var(--bg);
    overflow: hidden;
  }

  .menu-btn {
    display: none;
    background: none;
    border: 1px solid var(--border);
    color: var(--text);
    width: 34px; height: 34px;
    font-size: 16px;
    flex-shrink: 0;
  }

  .backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(20,16,10,0.4);
    z-index: 45;
  }
  .backdrop.show { display: block; }

  /* Sidebar */
  aside {
    width: 260px;
    min-width: 260px;
    background: var(--bg-side);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 14px;
  }
  .new-chat {
    background: none;
    color: var(--text);
    border: 1px solid var(--text);
    border-radius: 3px;
    padding: 10px;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: .3px;
  }
  .new-chat:hover { background: var(--text); color: var(--accent-ink); }
  .sidebar-title {
    margin: 22px 4px 8px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  #convo-list { flex: 1; overflow-y: auto; }
  .convo {
    display: block;
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    border-left: 2px solid transparent;
    color: var(--text);
    padding: 9px 10px;
    font-size: 14px;
    margin-bottom: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .convo:hover { border-left-color: var(--border); }
  .convo.active { border-left-color: var(--accent); color: var(--accent); }
  .no-convos { color: var(--muted); font-size: 13px; padding: 4px; }

  main { flex: 1; display: flex; flex-direction: column; min-width: 0; }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 24px;
    border-bottom: 1px solid var(--border);
    min-height: 56px;
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .brand-logo {
    width: 34px; height: 34px; flex-shrink: 0;
    background: var(--accent);
    color: var(--accent-ink); font-weight: 400; font-size: 18px;
    font-style: italic;
    display: flex; align-items: center; justify-content: center;
  }
  .brand-name { font-size: 16px; font-weight: 600; letter-spacing: .2px; }
  .brand-desc {
    font-size: 11px; color: var(--muted);
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    text-transform: uppercase; letter-spacing: 1px;
  }
  .badge {
    background: none;
    border: 1px solid var(--border);
    padding: 5px 12px;
    font-size: 12px;
    color: var(--muted);
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .badge b { color: var(--text); font-weight: 600; }

  #messages { flex: 1; overflow-y: auto; padding: 24px 0 10px; }
  .messages-inner { max-width: 700px; margin: 0 auto; padding: 0 20px; }

  .msg { display: flex; flex-direction: column; margin-bottom: 26px; }
  .msg.user { align-items: flex-end; }
  .msg.ai { align-items: flex-start; }
  .msg .who {
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 10px; text-transform: uppercase; letter-spacing: 1.5px;
    color: var(--muted); margin-bottom: 6px;
  }
  .msg .bubble {
    max-width: 82%;
    line-height: 1.55;
    font-size: 15.5px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .msg.user .bubble {
    background: var(--accent); color: var(--accent-ink);
    padding: 10px 14px;
  }
  .msg.ai .bubble { padding: 0; border-bottom: 1px solid transparent; }
  .msg-actions { margin-top: 8px; }
  .copy-btn {
    background: none;
    border: none;
    color: var(--muted);
    font-size: 11px;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    text-transform: uppercase; letter-spacing: .5px;
    padding: 2px 0;
  }
  .copy-btn:hover { color: var(--accent); }
  .doc-tag {
    color: var(--accent); font-size: 11px; margin-left: 10px;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }

  /* Typing indicator */
  .typing .who { visibility: hidden; }
  .typing .bubble {
    color: var(--muted); font-style: italic; font-size: 15px;
  }
  .typing .bubble::after {
    content: "thinking"; animation: fade 1.4s ease-in-out infinite;
  }
  @keyframes fade { 0%,100% { opacity: .35; } 50% { opacity: .9; } }

  /* Welcome / empty state */
  .welcome { text-align: center; padding-top: 12vh; }
  .welcome .logo {
    width: 52px; height: 52px; margin: 0 auto 20px;
    background: var(--accent);
    display: flex; align-items: center; justify-content: center;
    font-size: 26px; color: var(--accent-ink); font-style: italic; font-weight: 400;
  }
  .welcome h1 { font-size: 26px; margin-bottom: 10px; font-weight: 600; }
  .welcome p {
    color: var(--muted); max-width: 420px; margin: 0 auto 28px; line-height: 1.6;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 14px;
  }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
  .chip {
    background: none;
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 15px;
    font-size: 13px;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .chip:hover { border-color: var(--accent); color: var(--accent); }

  /* Setup notice when no API key */
  .notice {
    background: rgba(156,68,51,0.08);
    border: 1px solid var(--danger);
    color: var(--text);
    padding: 14px 16px;
    margin-bottom: 18px;
    font-size: 13px;
    line-height: 1.6;
    text-align: left;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .notice code {
    background: rgba(44,38,32,0.08);
    padding: 1px 6px; font-size: 12px;
  }

  footer { padding: 12px 20px 22px; }
  .options {
    max-width: 700px; margin: 0 auto 10px;
    display: flex; align-items: center; gap: 10px;
  }
  .options label {
    display: flex; align-items: center; gap: 8px;
    color: var(--muted); font-size: 12px; cursor: pointer;
    background: none; border: 1px solid var(--border);
    padding: 6px 12px; user-select: none;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .options label:hover { color: var(--text); }
  .options label.hidden { display: none; }
  .options label.on { color: var(--accent); border-color: var(--accent); }
  .upload-btn {
    background: none; border: 1px dashed var(--border); color: var(--muted);
    padding: 9px; font-size: 12px; width: 100%;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .upload-btn:hover { color: var(--accent); border-color: var(--accent); }
  .side-count { color: var(--accent); font-weight: 600; }
  .doc-item {
    display: flex; align-items: center; gap: 6px;
    background: var(--bg-input); border: 1px solid var(--border);
    padding: 7px 8px; margin-bottom: 6px; font-size: 12px;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .doc-item .doc-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .doc-item .del {
    background: none; border: none; color: var(--muted); font-size: 14px; line-height: 1;
  }
  .doc-item .del:hover { color: var(--danger); }
  .toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: var(--text); color: var(--bg); padding: 10px 18px;
    font-size: 13px; display: none; z-index: 99;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .toast.err { background: var(--danger); color: #fff; }

  .input-row {
    max-width: 700px; margin: 0 auto;
    display: flex; align-items: flex-end; gap: 10px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    padding: 10px 12px;
  }
  .input-row:focus-within { border-color: var(--accent); }
  textarea {
    flex: 1; background: none; border: none; outline: none;
    color: var(--text); font-size: 15px; font-family: inherit;
    resize: none; max-height: 160px; line-height: 1.4;
  }
  #send {
    background: var(--accent); color: var(--accent-ink); border: none;
    width: 36px; height: 36px; font-size: 16px;
    flex-shrink: 0;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  #send:disabled { opacity: .5; cursor: not-allowed; }

  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-thumb { background: var(--border); }

  /* Tablet */
  @media (max-width: 980px) {
    body { padding: 0; }
    .app { max-width: 100%; max-height: 100%; height: 100%; border: none; box-shadow: none; }
    aside { width: 220px; min-width: 220px; }
  }

  /* Phone */
  @media (max-width: 720px) {
    .menu-btn { display: flex; align-items: center; justify-content: center; }
    aside {
      position: fixed; top: 0; left: 0; bottom: 0; z-index: 50;
      width: 82vw; max-width: 300px;
      box-shadow: 6px 0 24px rgba(20,16,10,0.25);
      transform: translateX(-100%);
      transition: transform .22s ease;
    }
    aside.open { transform: translateX(0); }
    header { padding: 10px 14px; }
    .brand-desc { display: none; }
    .badge { font-size: 11px; padding: 4px 9px; }
    #messages { padding: 16px 0 6px; }
    .messages-inner { padding: 0 14px; }
    .msg .bubble { max-width: 94%; font-size: 15px; }
    .welcome { padding-top: 6vh; }
    .welcome h1 { font-size: 22px; }
    .welcome p { padding: 0 8px; }
    footer { padding: 10px 12px 14px; }
    .options, .input-row { max-width: 100%; }
    textarea { font-size: 16px; }
  }
</style>
</head>
<body>
  <div class="app">
  <div class="backdrop" id="backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar">
    <button class="new-chat" onclick="newChat()">New chat</button>
    <div class="sidebar-title">History</div>
    <div id="convo-list"><div class="no-convos">No chats yet.</div></div>
    <div class="sidebar-title">Documents <span id="doc-count" class="side-count"></span></div>
    <button class="upload-btn" onclick="document.getElementById('file').click()">+ Upload a document</button>
    <input type="file" id="file" multiple accept=".txt,.md,.csv,.json,.log,.docx,.pdf" style="display:none" onchange="uploadFiles(this.files); this.value=''">
    <div id="doc-list"></div>
  </aside>

  <main>
    <header>
      <div class="brand">
        <button class="menu-btn" onclick="toggleSidebar()" aria-label="Menu">&#9776;</button>
        <div class="brand-logo">a.</div>
        <div class="brand-text">
          <div class="brand-name">AI Services</div>
          <div class="brand-desc">Chat &middot; Tools &middot; Documents</div>
        </div>
      </div>
      <div class="badge">Model: <b id="model-badge">loading...</b></div>
    </header>

    <div id="messages">
      <div class="messages-inner" id="msg-inner">
        <div class="welcome" id="welcome">
          <div class="logo">a.</div>
          <h1>Ask away.</h1>
          <p>Chat freely, search the web, or upload your own documents and ask questions about them.</p>
          <div id="setup" style="display:none" class="notice"></div>
          <div class="chips">
            <button class="chip" onclick="ask('Search the web for today\'s news')">Search the web</button>
            <button class="chip" onclick="document.getElementById('file').click()">Upload a document</button>
          </div>
        </div>
      </div>
    </div>

    <footer>
      <div class="options">
        <label id="rag-toggle"><input type="checkbox" id="rag-chk" onchange="saveRag()"> Ask my documents</label>
      </div>
      <div class="input-row">
        <textarea id="input" rows="1" placeholder="Send a message..."></textarea>
        <button id="send" onclick="sendMsg()">&uarr;</button>
      </div>
    </footer>
  </main>
  </div>
  <div class="toast" id="toast"></div>

<script>
const LS_KEY = "aiagent_convos";
let convos = {};
let currentId = null;
let busy = false;

window.addEventListener("error", (e) => {
  try {
    const t = document.getElementById("toast");
    if (t) { t.textContent = "JS error: " + (e.message || e.type); t.className = "toast err"; t.style.display = "block"; }
  } catch (_) {}
});

function load() {
  try { convos = JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch (e) { convos = {}; }
}
function save() { localStorage.setItem(LS_KEY, JSON.stringify(convos)); }

function toggleSidebar() {
  document.getElementById("sidebar").classList.toggle("open");
  document.getElementById("backdrop").classList.toggle("show");
}
function closeSidebar() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("backdrop").classList.remove("show");
}
function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }

function currentMessages() {
  return convos[currentId] ? convos[currentId].messages : [];
}
function titleOf(messages) {
  for (const m of messages) if (m.role === "user") return m.content.slice(0, 40);
  return "New chat";
}

function renderSidebar() {
  const list = document.getElementById("convo-list");
  const ids = Object.keys(convos);
  if (!ids.length) {
    list.innerHTML = '<div class="no-convos">No chats yet.</div>';
    return;
  }
  list.innerHTML = "";
  for (const id of ids) {
    const b = document.createElement("button");
    b.className = "convo" + (id === currentId ? " active" : "");
    b.textContent = titleOf(convos[id].messages);
    b.onclick = () => switchChat(id);
    list.appendChild(b);
  }
}

function newChat() {
  currentId = uid();
  convos[currentId] = { messages: [] };
  save();
  renderSidebar();
  showWelcome();
  document.getElementById("input").focus();
  closeSidebar();
}

function switchChat(id) {
  currentId = id;
  renderSidebar();
  closeSidebar();
  const w = document.getElementById("welcome");
  if (!convos[id] || !convos[id].messages.length) { showWelcome(); }
  else {
    if (w) w.style.display = "none";
    clearMessages();
    const inner = document.getElementById("msg-inner");
    for (const m of convos[id].messages) inner.append(messageNode(m.role, m.content));
    inner.scrollTop = inner.scrollHeight;
  }
}

function clearMessages() {
  const inner = document.getElementById("msg-inner");
  Array.from(inner.children).forEach((c) => { if (c.classList.contains("msg")) c.remove(); });
}

function showWelcome() {
  clearMessages();
  const w = document.getElementById("welcome");
  if (w) w.style.display = "";
}

function messageNode(role, text, note) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = role === "user" ? "you" : "ai services";
  wrap.appendChild(who);
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);
  if (role === "ai") {
    const actions = document.createElement("div");
    actions.className = "msg-actions";
    const copy = document.createElement("button");
    copy.className = "copy-btn";
    copy.textContent = "copy";
    copy.onclick = () => navigator.clipboard.writeText(text);
    actions.appendChild(copy);
    if (note) {
      const tag = document.createElement("span");
      tag.className = "doc-tag";
      tag.textContent = "answered from your documents";
      actions.appendChild(tag);
    }
    wrap.appendChild(actions);
  }
  return wrap;
}

function addMessage(role, text, note) {
  const inner = document.getElementById("msg-inner");
  inner.appendChild(messageNode(role, text, note));
  document.getElementById("messages").scrollTop = document.getElementById("messages").scrollHeight;
}

function setBusy(state) {
  busy = state;
  document.getElementById("send").disabled = state;
  document.getElementById("input").disabled = state;
}

async function sendMsg() {
  const area = document.getElementById("input");
  const text = area.value.trim();
  if (!text || busy) return;
  area.value = "";
  area.style.height = "auto";
  ask(text);
}

async function ask(text) {
  if (!currentId) newChat();
  const userText = text.trim();
  addMessage("user", userText);
  dragToTop();

  const typing = document.createElement("div");
  typing.className = "msg ai typing";
  typing.innerHTML = '<div class="who">ai services</div><div class="bubble"></div>';
  document.getElementById("msg-inner").appendChild(typing);
  document.getElementById("messages").scrollTop = document.getElementById("messages").scrollHeight;
  setBusy(true);

  const history = currentMessages();
  history.push({ role: "user", content: userText });
  save();

  const ctrl = new AbortController();
  const abortTimer = setTimeout(() => ctrl.abort(), 175000);
  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history, use_docs: ragEnabled() }),
      signal: ctrl.signal,
    });
    clearTimeout(abortTimer);
    const data = await res.json();
    typing.remove();
    if (data.no_key) {
      showSetup(data.setup);
      const users = document.querySelectorAll("#msg-inner .msg.user");
      if (users.length) users[users.length - 1].remove();
      history.pop();
      document.getElementById("welcome").style.display = "";
    } else {
      hideSetup();
      addMessage("ai", data.reply, data.used_docs);
      history.push({ role: "assistant", content: data.reply });
      fetchBadge(data.model);
    }
  } catch (e) {
    clearTimeout(abortTimer);
    typing.remove();
    if (e.name === "AbortError") {
      addMessage("ai", "The request took too long. Please try again.");
      history.pop();
    } else {
      addMessage("ai", "Connection error. Is the server still running?");
      history.pop();
    }
  } finally {
    save();
    renderSidebar();
    setBusy(false);
    try { document.getElementById("input").disabled = false; } catch (_) {}
  }
}

function showSetup(text) {
  const s = document.getElementById("setup");
  s.style.display = "block";
  s.innerHTML = text;
}
function hideSetup() { document.getElementById("setup").style.display = "none"; }

async function fetchBadge(model) {
  if (model) document.getElementById("model-badge").textContent = model;
  else {
    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: [] }),
      });
      const d = await res.json();
      document.getElementById("model-badge").textContent = d.model || "unknown";
      if (d.no_key) showSetup(d.setup);
    } catch (e) {
      document.getElementById("model-badge").textContent = "offline";
    }
  }
}

function dragToTop() { const w = document.getElementById("welcome"); if (w) w.style.display = "none"; }

/* ---- Documents (RAG) ---- */
const RAG_KEY = "aiagent_rag";
function ragEnabled() { return document.getElementById("rag-chk").checked; }
function saveRag() { localStorage.setItem(RAG_KEY, ragEnabled() ? "1" : "0"); }
function toast(msg, isErr) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.style.display = "block";
  clearTimeout(t._t);
  t._t = setTimeout(() => t.style.display = "none", 3500);
}

async function uploadFiles(files) {
  const arr = Array.from(files);
  if (!arr.length) return;
  for (const f of arr) {
    const resp = await fetch("/upload?name=" + encodeURIComponent(f.name), {
      method: "POST",
      body: f,
    });
    const res = await resp.json();
    if (res.ok) toast(`Added: ${res.name} (${res.chunks} parts)`);
    else toast(res.error, true);
  }
  refreshDocs();
}

async function refreshDocs() {
  let data;
  try {
    const r = await fetch("/docs", { method: "POST" });
    data = await r.json();
  } catch (e) { return; }
  const docs = data.docs || [];
  document.getElementById("doc-count").textContent = `${docs.length}/${data.max}`;
  const list = document.getElementById("doc-list");
  if (!docs.length) {
    list.innerHTML = '<div class="no-convos">No documents yet.</div>';
  } else {
    list.innerHTML = "";
    for (const d of docs) {
      const item = document.createElement("div");
      item.className = "doc-item";
      const name = document.createElement("span");
      name.className = "doc-name";
      name.textContent = d.name;
      name.title = d.name;
      const del = document.createElement("button");
      del.className = "del";
      del.textContent = "\u00d7";
      del.title = "Remove";
      del.onclick = async () => {
        await fetch("/del", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: d.id }),
        });
        refreshDocs();
      };
      item.appendChild(name);
      item.appendChild(del);
      list.appendChild(item);
    }
  }
  const label = document.getElementById("rag-toggle");
  label.classList.toggle("hidden", !docs.length);
  if (!docs.length) document.getElementById("rag-chk").checked = false;
}

const area = document.getElementById("input");
area.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); }
});
area.addEventListener("input", () => {
  area.style.height = "auto";
  area.style.height = Math.min(area.scrollHeight, 160) + "px";
});

load();
if (!Object.keys(convos).length) newChat(); else switchChat(Object.keys(convos)[Object.keys(convos).length - 1]);
fetchBadge(null);
document.getElementById("rag-chk").checked = localStorage.getItem(RAG_KEY) === "1";
refreshDocs();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, HTML, "text/html; charset=utf-8")
        else:
            self._send(404, "Not found", "text/plain")

    def do_POST(self):
        route = urlparse(self.path).path
        if route == "/chat":
            return self.chat()
        if route == "/upload":
            return self.upload()
        if self.path == "/docs":
            docs, remaining = rag.list_documents()
            return self._send(200, json.dumps({"docs": docs, "max": rag.MAX_DOCS, "remaining": remaining}), "application/json")
        if self.path == "/del":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0))
            ok = rag.remove_document(body.get("id", ""))
            docs, remaining = rag.list_documents()
            return self._send(200, json.dumps({"ok": ok, "docs": docs, "max": rag.MAX_DOCS, "remaining": remaining}), "application/json")
        self._send(404, "Not found", "text/plain")

    def upload(self):
        qs = parse_qs(urlparse(self.path).query)
        name = (qs.get("name") or ["file.txt"])[0]
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length)
        if not data:
            return self._send(400, json.dumps({"ok": False, "error": "Empty file."}), "application/json")
        res = rag.add_document(name, data)
        return self._send(200, json.dumps(res), "application/json")

    def chat(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send(400, json.dumps({"error": "Bad JSON"}), "application/json")
            return

        history = body.get("messages", [])
        use_docs = bool(body.get("use_docs"))
        cfg = get_config()

        if not cfg["api_key"]:
            setup = ("No API key found.<br>"
                     "The easy and free way: <code>export AI_AGENT_PROVIDER=ollama</code> "
                     "(install Ollama first).<br>"
                     "Or use Groq / OpenRouter: <code>export AI_AGENT_KEY=...</code> "
                     "and restart the server.")
            self._send(200, json.dumps({
                "reply": None, "no_key": True, "model": cfg["model"],
                "provider": cfg["provider"], "setup": setup,
            }), "application/json")
            return

        if not history:
            self._send(200, json.dumps({"reply": None, "no_key": False, "model": cfg["model"]}), "application/json")
            return

        messages = [{"role": "system", "content": cfg["system_prompt"]}]

        if use_docs:
            question = history[-1]["content"] if history else ""
            chunks = rag.retrieve(question, top_k=3)
            if chunks:
                excerpts = "\n\n---\n\n".join(f"[{c['name']}] {c['text']}" for c in chunks)
                messages.append({"role": "system", "content":
                    "You are reading the user's documents. Answer using ONLY the excerpts below "
                    "when possible. If the answer is not in there, say: 'That is not in your documents.'\n\n"
                    f"Excerpts:\n{excerpts}"})

        messages += history
        try:
            reply = run_with_messages(messages)
        except agent.APIError as e:
            reply = f"Provider error: {e}"
        except Exception as e:
            reply = f"Unexpected error: {e}"
        self._send(200, json.dumps({
            "reply": reply, "no_key": False, "model": cfg["model"],
            "used_docs": use_docs and bool(chunks),
        }), "application/json")


def main():
    cfg = get_config()
    print(f"AI web UI ready: http://localhost:{PORT}")
    print(f"Provider: {cfg['provider']}  |  Model: {cfg['model']}")
    if not cfg["api_key"]:
        print("Warning: no AI_AGENT_KEY set. Set AI_AGENT_PROVIDER=ollama or export AI_AGENT_KEY=...")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()