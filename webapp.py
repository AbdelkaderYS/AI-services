import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from agent import get_config, run_with_messages, APIError
import agent
import memory
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
    --bg-page: #eef0f3;
    --bg: #ffffff;
    --bg-side: #fafbfc;
    --bg-input: #f4f5f7;
    --border: #e4e7eb;
    --text: #16181d;
    --muted: #6b7280;
    --accent: #4f46e5;
    --accent-hover: #4338ca;
    --accent-soft: #eef2ff;
    --accent-ink: #ffffff;
    --danger: #dc2626;
    --danger-soft: #fef2f2;
    --success: #16a34a;
    --radius-sm: 6px;
    --radius-md: 8px;
    --radius-lg: 12px;
  }
  html, body { height: 100%; }
  body {
    background: var(--bg-page);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
    padding: 24px;
  }
  button { font-family: inherit; cursor: pointer; }
  .icon { flex-shrink: 0; display: inline-flex; }

  .app {
    position: relative;
    display: flex;
    width: 100%;
    max-width: 1180px;
    height: 100%;
    max-height: 860px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: 0 1px 2px rgba(16,24,40,0.04), 0 8px 24px rgba(16,24,40,0.08);
    background: var(--bg);
    overflow: hidden;
  }

  .menu-btn {
    display: none;
    background: none;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    width: 34px; height: 34px;
    align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  .menu-btn:hover { background: var(--bg-input); }

  .backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(16,24,40,0.4);
    z-index: 45;
  }
  .backdrop.show { display: block; }

  /* Sidebar */
  aside {
    width: 264px;
    min-width: 264px;
    background: var(--bg-side);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 16px;
  }
  .new-chat {
    display: flex; align-items: center; justify-content: center; gap: 7px;
    background: var(--accent);
    color: var(--accent-ink);
    border: none;
    border-radius: var(--radius-md);
    padding: 10px;
    font-size: 13.5px;
    font-weight: 600;
    box-shadow: 0 1px 2px rgba(79,70,229,0.25);
  }
  .new-chat:hover { background: var(--accent-hover); }
  .sidebar-title {
    margin: 22px 6px 8px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .6px;
    color: var(--muted);
  }
  #convo-list { flex: 1; overflow-y: auto; }
  .convo-row {
    display: flex; align-items: center;
    border-radius: var(--radius-sm);
    margin-bottom: 2px;
  }
  .convo-row:hover { background: var(--bg-input); }
  .convo-row.active { background: var(--accent-soft); }
  .convo-row.active .convo { color: var(--accent-hover); font-weight: 600; }
  .convo {
    flex: 1; min-width: 0;
    display: block;
    text-align: left;
    background: none;
    border: none;
    color: var(--text);
    padding: 8px 10px;
    font-size: 13.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .convo-del {
    display: flex; align-items: center; justify-content: center;
    background: none; border: none; color: var(--muted);
    padding: 6px 8px; flex-shrink: 0; border-radius: var(--radius-sm);
  }
  .convo-del:hover { color: var(--danger); background: var(--danger-soft); }
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
    width: 32px; height: 32px; flex-shrink: 0;
    background: var(--accent);
    border-radius: var(--radius-sm);
    color: var(--accent-ink); font-weight: 700; font-size: 14px;
    display: flex; align-items: center; justify-content: center;
    letter-spacing: -.5px;
  }
  .brand-name { font-size: 14.5px; font-weight: 600; letter-spacing: -.1px; }
  .brand-desc { font-size: 11.5px; color: var(--muted); }
  .badge {
    display: flex; align-items: center; gap: 7px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 5px 12px 5px 10px;
    font-size: 12px;
    color: var(--muted);
  }
  .badge b { color: var(--text); font-weight: 600; }
  .status-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--success); flex-shrink: 0;
  }

  #messages { flex: 1; overflow-y: auto; padding: 24px 0 10px; }
  .messages-inner { max-width: 720px; margin: 0 auto; padding: 0 20px; }

  .msg { display: flex; flex-direction: column; margin-bottom: 18px; }
  .msg.user { align-items: flex-end; }
  .msg.ai { align-items: flex-start; }
  .msg .who {
    font-size: 11.5px; font-weight: 600;
    color: var(--muted); margin-bottom: 5px; padding: 0 2px;
  }
  .msg .bubble {
    max-width: 80%;
    line-height: 1.55;
    font-size: 14.5px;
    white-space: pre-wrap;
    word-break: break-word;
    border-radius: var(--radius-lg);
    padding: 10px 14px;
  }
  .msg.user .bubble {
    background: var(--accent); color: var(--accent-ink);
    border-bottom-right-radius: 4px;
  }
  .msg.ai .bubble {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-bottom-left-radius: 4px;
  }
  .msg-actions { margin-top: 6px; padding: 0 2px; }
  .copy-btn {
    background: none;
    border: none;
    color: var(--muted);
    font-size: 11.5px;
    font-weight: 500;
    padding: 2px 0;
  }
  .copy-btn:hover { color: var(--accent); }
  .doc-tag { color: var(--accent); font-size: 11.5px; margin-left: 10px; font-weight: 500; }

  /* Typing indicator */
  .typing .who { visibility: hidden; }
  .typing .bubble {
    color: var(--muted); font-size: 14px;
    display: flex; align-items: center; gap: 4px;
    padding: 12px 14px;
  }
  .typing .bubble span {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--muted); animation: bounce 1.2s infinite;
  }
  .typing .bubble span:nth-child(2) { animation-delay: .15s; }
  .typing .bubble span:nth-child(3) { animation-delay: .3s; }
  @keyframes bounce { 0%,60%,100% { transform: translateY(0); opacity: .5; } 30% { transform: translateY(-4px); opacity: 1; } }

  /* Welcome / empty state */
  .welcome { text-align: center; padding-top: 11vh; }
  .welcome .logo {
    width: 48px; height: 48px; margin: 0 auto 18px;
    background: var(--accent);
    border-radius: var(--radius-md);
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; color: var(--accent-ink); font-weight: 700;
    letter-spacing: -.5px;
    box-shadow: 0 4px 12px rgba(79,70,229,0.25);
  }
  .welcome h1 { font-size: 22px; margin-bottom: 8px; font-weight: 600; letter-spacing: -.2px; }
  .welcome p {
    color: var(--muted); max-width: 420px; margin: 0 auto 26px; line-height: 1.55;
    font-size: 14px;
  }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
  .chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    color: var(--text);
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 500;
  }
  .chip:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }

  /* Setup notice when no API key */
  .notice {
    background: var(--danger-soft);
    border: 1px solid #fecaca;
    border-left: 3px solid var(--danger);
    border-radius: var(--radius-md);
    color: var(--text);
    padding: 14px 16px;
    margin-bottom: 18px;
    font-size: 13px;
    line-height: 1.6;
    text-align: left;
  }
  .notice code {
    background: rgba(0,0,0,0.06);
    border-radius: 4px;
    padding: 1px 6px; font-size: 12px;
  }

  footer { padding: 12px 20px 22px; }
  .upload-btn {
    display: flex; align-items: center; justify-content: center; gap: 7px;
    background: var(--bg); border: 1px dashed var(--border); color: var(--muted);
    border-radius: var(--radius-md);
    padding: 9px; font-size: 12.5px; font-weight: 500; width: 100%;
  }
  .upload-btn:hover { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
  .side-count { color: var(--accent); font-weight: 600; }
  .doc-item {
    display: flex; align-items: center; gap: 6px;
    background: var(--bg); border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 7px 8px; margin-bottom: 5px; font-size: 12.5px;
  }
  .doc-item .doc-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .doc-item .del {
    display: flex; align-items: center; justify-content: center;
    background: none; border: none; color: var(--muted); border-radius: var(--radius-sm); padding: 4px;
  }
  .doc-item .del:hover { color: var(--danger); background: var(--danger-soft); }
  .toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: var(--text); color: #fff; padding: 10px 18px;
    border-radius: var(--radius-md);
    font-size: 13px; font-weight: 500; display: none; z-index: 99;
    box-shadow: 0 4px 16px rgba(16,24,40,0.2);
  }
  .toast.err { background: var(--danger); }

  .input-row {
    max-width: 720px; margin: 0 auto;
    display: flex; align-items: flex-end; gap: 10px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 10px 10px 10px 14px;
    transition: box-shadow .15s ease, border-color .15s ease;
  }
  .input-row:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  textarea {
    flex: 1; background: none; border: none; outline: none;
    color: var(--text); font-size: 14.5px; font-family: inherit;
    resize: none; max-height: 160px; line-height: 1.4;
  }
  #send {
    display: flex; align-items: center; justify-content: center;
    background: var(--accent); color: var(--accent-ink); border: none;
    width: 34px; height: 34px; border-radius: 50%;
    flex-shrink: 0;
  }
  #send:hover:not(:disabled) { background: var(--accent-hover); }
  #send:disabled { opacity: .4; cursor: not-allowed; }

  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: #d5d9df; border-radius: 4px; }

  /* Tablet */
  @media (max-width: 980px) {
    body { padding: 0; }
    .app { max-width: 100%; max-height: 100%; height: 100%; border: none; border-radius: 0; box-shadow: none; }
    aside { width: 224px; min-width: 224px; }
  }

  /* Phone */
  @media (max-width: 720px) {
    .menu-btn { display: flex; }
    aside {
      position: fixed; top: 0; left: 0; bottom: 0; z-index: 50;
      width: 82vw; max-width: 300px;
      box-shadow: 6px 0 24px rgba(16,24,40,0.25);
      transform: translateX(-100%);
      transition: transform .22s ease;
    }
    aside.open { transform: translateX(0); }
    header { padding: 10px 14px; }
    .brand-desc { display: none; }
    .badge { font-size: 11px; padding: 4px 10px 4px 8px; }
    #messages { padding: 16px 0 6px; }
    .messages-inner { padding: 0 14px; }
    .msg .bubble { max-width: 92%; font-size: 14.5px; }
    .welcome { padding-top: 6vh; }
    .welcome h1 { font-size: 20px; }
    .welcome p { padding: 0 8px; }
    footer { padding: 10px 12px 14px; }
    .input-row { max-width: 100%; }
    textarea { font-size: 16px; }
  }
</style>
</head>
<body>
  <div class="app">
  <div class="backdrop" id="backdrop" onclick="closeSidebar()"></div>
  <aside id="sidebar">
    <button class="new-chat" onclick="newChat()">
      <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      New chat
    </button>
    <div class="sidebar-title">History</div>
    <div id="convo-list"><div class="no-convos">No chats yet.</div></div>
    <div class="sidebar-title">Documents <span id="doc-count" class="side-count"></span></div>
    <button class="upload-btn" onclick="document.getElementById('file').click()">
      <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
      Upload a document
    </button>
    <input type="file" id="file" multiple accept=".txt,.md,.csv,.json,.log,.docx,.pdf" style="display:none" onchange="uploadFiles(this.files); this.value=''">
    <div id="doc-list"></div>
    <div class="sidebar-title">Memories</div>
    <div id="memory-list"><div class="no-convos">Nothing remembered yet.</div></div>
  </aside>

  <main>
    <header>
      <div class="brand">
        <button class="menu-btn" onclick="toggleSidebar()" aria-label="Menu">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
        </button>
        <div class="brand-logo">A</div>
        <div class="brand-text">
          <div class="brand-name">AI Services</div>
          <div class="brand-desc">Chat &middot; Tools &middot; Documents &middot; Memory</div>
        </div>
      </div>
      <div class="badge"><span class="status-dot"></span>Model: <b id="model-badge">loading...</b></div>
    </header>

    <div id="messages">
      <div class="messages-inner" id="msg-inner">
        <div class="welcome" id="welcome">
          <div class="logo">A</div>
          <h1>Ask away.</h1>
          <p>Chat freely &mdash; it searches the web, checks your documents, and remembers what you tell it, automatically.</p>
          <div id="setup" style="display:none" class="notice"></div>
          <div class="chips">
            <button class="chip" onclick="ask('Search the web for today\'s news')">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              Search the web
            </button>
            <button class="chip" onclick="document.getElementById('file').click()">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              Upload a document
            </button>
          </div>
        </div>
      </div>
    </div>

    <footer>
      <div class="input-row">
        <textarea id="input" rows="1" placeholder="Send a message..."></textarea>
        <button id="send" onclick="sendMsg()" aria-label="Send">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
        </button>
      </div>
    </footer>
  </main>
  </div>
  <div class="toast" id="toast"></div>

<script>
const LS_KEY = "aiagent_convos";
const TRASH_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>';
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
    const row = document.createElement("div");
    row.className = "convo-row" + (id === currentId ? " active" : "");
    const b = document.createElement("button");
    b.className = "convo";
    b.textContent = titleOf(convos[id].messages);
    b.onclick = () => switchChat(id);
    const del = document.createElement("button");
    del.className = "convo-del";
    del.innerHTML = TRASH_ICON;
    del.title = "Delete chat";
    del.onclick = (e) => { e.stopPropagation(); deleteChat(id); };
    row.appendChild(b);
    row.appendChild(del);
    list.appendChild(row);
  }
}

function deleteChat(id) {
  delete convos[id];
  save();
  if (id !== currentId) { renderSidebar(); return; }
  const remaining = Object.keys(convos);
  if (remaining.length) {
    switchChat(remaining[remaining.length - 1]);
  } else {
    currentId = null;
    renderSidebar();
    showWelcome();
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
  who.textContent = role === "user" ? "You" : "AI Services";
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
  typing.innerHTML = '<div class="who">AI Services</div><div class="bubble"><span></span><span></span><span></span></div>';
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
      body: JSON.stringify({ messages: history }),
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
    refreshMemories();
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
      del.innerHTML = TRASH_ICON;
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
}

async function refreshMemories() {
  let data;
  try {
    const r = await fetch("/memories", { method: "POST" });
    data = await r.json();
  } catch (e) { return; }
  const mems = data.memories || [];
  const list = document.getElementById("memory-list");
  if (!mems.length) {
    list.innerHTML = '<div class="no-convos">Nothing remembered yet.</div>';
  } else {
    list.innerHTML = "";
    for (const m of mems) {
      const item = document.createElement("div");
      item.className = "doc-item";
      const text = document.createElement("span");
      text.className = "doc-name";
      text.textContent = m.text;
      text.title = m.text;
      const del = document.createElement("button");
      del.className = "del";
      del.innerHTML = TRASH_ICON;
      del.title = "Forget";
      del.onclick = async () => {
        await fetch("/memories/del", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: m.id }),
        });
        refreshMemories();
      };
      item.appendChild(text);
      item.appendChild(del);
      list.appendChild(item);
    }
  }
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
refreshDocs();
refreshMemories();
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
        if self.path == "/memories":
            return self._send(200, json.dumps({"memories": memory.list_memories()}), "application/json")
        if self.path == "/memories/del":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0))
            ok = memory.forget(body.get("id", ""))
            return self._send(200, json.dumps({"ok": ok, "memories": memory.list_memories()}), "application/json")
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

        messages = [{"role": "system", "content": cfg["system_prompt"]}] + history
        tool_trace = []
        try:
            reply = run_with_messages(messages, tool_trace=tool_trace)
        except agent.APIError as e:
            reply = f"Provider error: {e}"
        except Exception as e:
            reply = f"Unexpected error: {e}"
        self._send(200, json.dumps({
            "reply": reply, "no_key": False, "model": cfg["model"],
            "used_docs": "search_documents" in tool_trace,
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