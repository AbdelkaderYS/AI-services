import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

from agent import get_config, run_with_messages, APIError
import agent
import media
import memory
import mcp_client
import rag

PORT = int(os.environ.get("AI_AGENT_PORT", "8080"))

# Optional access lock: set AUTH_PASSWORD to require a one-time login.
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")
AUTH_ENABLED = bool(AUTH_PASSWORD)
SESSION_COOKIE = "gq_session"
SESSION_TOKEN = secrets.token_hex(16) if AUTH_ENABLED else ""
LOGIN_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in - GifteQChat</title>
<style>
  body { margin:0; background:#0d1117; color:#e6edf3; font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
         display:flex; align-items:center; justify-content:center; min-height:100vh; }
  form { background:#161b22; border:1px solid #30363d; border-radius:12px; padding:32px 28px; width:320px; }
  h1 { font-size:20px; margin:0 0 14px; }
  input { width:100%; padding:10px 12px; border-radius:8px; border:1px solid #30363d; background:#0d1117; color:#e6edf3; box-sizing:border-box; }
  button { margin-top:14px; width:100%; padding:10px; border:0; border-radius:8px; background:#6ea8fe; color:#06122b; font-weight:600; cursor:pointer; }
  .err { color:#ff7b72; font-size:13px; min-height:18px; margin-top:8px; }
</style></head>
<body><form method="post" action="/login">
  <h1>Sign in</h1>
  <input type="password" name="password" placeholder="Password" autofocus>
  <button type="submit">Continue</button>
  <div class="err">__ERR__</div>
</form></body></html>"""

ABOUT_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>About - GifteQChat</title>
<style>
  :root { --bg:#0d1117; --panel:#161b22; --text:#e6edf3; --muted:#8b949e; --accent:#6ea8fe; --border:#30363d; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.6 system-ui,Segoe UI,Roboto,sans-serif; }
  .wrap { max-width:780px; margin:0 auto; padding:48px 20px 80px; }
  h1 { font-size:28px; margin:0 0 4px; }
  .tag { color:var(--accent); font-weight:600; letter-spacing:.4px; }
  h2 { font-size:18px; margin:32px 0 8px; border-bottom:1px solid var(--border); padding-bottom:6px; }
  ul { padding-left:20px; } li { margin:6px 0; }
  .pill { display:inline-block; background:var(--panel); border:1px solid var(--border); border-radius:999px; padding:3px 10px; font-size:12px; color:var(--muted); margin:2px 4px 2px 0; }
  a { color:var(--accent); }
  code { background:var(--panel); padding:1px 6px; border-radius:5px; font-size:13px; }
  .back { margin-top:40px; }
</style></head>
<body><div class="wrap">
  <div class="tag">LOCAL-FIRST AI AGENT</div>
  <h1>GifteQChat</h1>
  <p>A lightweight, framework-free AI chat agent that runs in a single Python process.
     No LangChain, no vector database, no cloud dependency required.</p>

  <h2>What it does</h2>
  <ul>
    <li><b>Chat</b> with any OpenAI-compatible provider (Ollama, Groq, OpenRouter, OpenAI).</li>
    <li><b>Web search</b> for current facts.</li>
    <li><b>RAG</b> over your documents : 14+ formats via AnyDoc (docx, pdf, xlsx, pptx, odt, rtf, epub, csv…).</li>
    <li><b>Long-term memory</b> of facts and preferences you share.</li>
    <li><b>Sandboxed Python</b> code interpreter with charts, CPU/RAM-limited.</li>
    <li><b>Sub-agents</b> for research, document analysis, and computation.</li>
    <li><b>MCP tools</b> : bring your own external tools over stdio, with sandbox + read-only guardrails.</li>
  </ul>

  <h2>Why it is different</h2>
  <p>Most agents are either heavy frameworks or opaque SaaS. GifteQChat is:</p>
  <ul>
    <li><b>Auditable</b> : every module is a few hundred readable lines.</li>
    <li><b>Private</b> : runs fully offline on Ollama; no telemetry.</li>
    <li><b>Zero-infra</b> : one process, no Redis/S3/vector store.</li>
    <li><b>Safe by design</b> : HTML-escaped rendering (anti-XSS), isolated code sandbox, path sanitization, MCP failure isolation.</li>
  </ul>

  <h2>Stack</h2>
  <span class="pill">Python stdlib</span><span class="pill">requests</span><span class="pill">pypdf</span>
  <span class="pill">matplotlib</span><span class="pill">firecrawl-anydoc</span><span class="pill">MCP</span>

  <h2>Quick start</h2>
  <p><code>pip install -r requirements.txt</code><br>
     <code>cp .env.example .env</code> (defaults to local Ollama)<br>
     <code>python3 webapp.py</code> → http://localhost:8080</p>

  <div class="back"><a href="/">← Back to chat</a></div>
</div></body></html>"""


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store">
<title>GifteQChat</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
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
  .collapsible-title { cursor: pointer; display: flex; align-items: center; justify-content: space-between; user-select: none; }
  .collapsible-title:hover { color: var(--text); }
  .collapsible-title .chev { font-size: 10px; color: var(--muted); }
  .hidden { display: none !important; }
  .side-footer { margin: 18px 6px 6px; font-size: 12px; }
  .side-footer a { color: var(--muted); text-decoration: none; }
  .side-footer a:hover { color: var(--accent); }
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
  .msg.ai .bubble h3, .msg.ai .bubble h4 { margin: 10px 0 4px; font-size: 14.5px; }
  .msg.ai .bubble h3:first-child, .msg.ai .bubble h4:first-child { margin-top: 0; }
  .msg.ai .bubble code {
    background: rgba(0,0,0,0.06); border-radius: 4px;
    padding: 1px 5px; font-size: 12.5px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  .msg.ai .bubble pre {
    background: #f6f8fa; border: 1px solid var(--border);
    border-radius: var(--radius-md); padding: 10px 12px;
    overflow-x: auto; margin: 8px 0;
    font-size: 12.5px; line-height: 1.5;
  }
  .msg.ai .bubble pre code { background: none; padding: 0; }

  /* Code blocks: a titled frame with a copy button, so code can be lifted out
     verbatim instead of being selected by hand out of the prose. */
  .code-block {
    margin: 8px 0; border: 1px solid var(--border);
    border-radius: var(--radius-md); overflow: hidden;
  }
  .code-bar {
    display: flex; align-items: center; justify-content: space-between;
    gap: 10px; padding: 5px 8px 5px 12px;
    background: #eceff3; border-bottom: 1px solid var(--border);
  }
  .code-lang {
    font-size: 10.5px; font-weight: 600; letter-spacing: .6px;
    text-transform: uppercase; color: var(--muted);
  }
  .code-copy {
    background: none; border: 1px solid var(--border); border-radius: 4px;
    color: var(--muted); font-size: 11px; font-weight: 500; padding: 2px 9px;
  }
  .code-copy:hover { color: var(--accent); border-color: var(--accent); background: var(--bg); }
  .msg.ai .bubble .code-block pre {
    margin: 0; border: none; border-radius: 0;
    white-space: pre; tab-size: 4;
  }
  .chat-img {
    display: block; max-width: 100%; height: auto;
    border-radius: var(--radius-md); margin-top: 8px;
    border: 1px solid var(--border); background: #fff;
  }
  .img-gone {
    display: block; margin-top: 8px;
    color: var(--muted); font-size: 12.5px; font-style: italic;
  }
  .katex-display { margin: 8px 0; overflow-x: auto; overflow-y: hidden; }
  .katex { font-size: 1.05em; }
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
  .doc-row { display: flex; align-items: center; gap: 6px; }
  .mcp-tools { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 5px; }
  .tool-chip {
    font-size: 11px; padding: 2px 7px; border-radius: 999px;
    background: var(--accent-soft); color: var(--accent); border: 1px solid var(--accent);
  }
  .msg-tools { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-top: 6px; padding-top: 5px; border-top: 1px dashed var(--border); }
  .tools-label { font-size: 11px; color: var(--muted); margin-right: 2px; }
  .tool-status { font-size: 11px; color: var(--accent); margin-bottom: 4px; font-style: italic; }
  .mcp-error { font-size: 11px; color: var(--danger); margin-top: 4px; word-break: break-word; }
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
    <input type="file" id="file" multiple accept=".txt,.md,.markdown,.csv,.json,.log,.py,.doc,.docx,.docm,.xls,.xlsx,.xlsm,.xlsb,.ppt,.pptx,.pps,.pot,.pptm,.ppsx,.ppsm,.odt,.ods,.odp,.rtf,.epub,.pdf" style="display:none" onchange="uploadFiles(this.files); this.value=''">
    <div id="doc-list"></div>
    <div class="sidebar-title collapsible-title" id="mcp-title" onclick="toggleMcp()">
      <span>MCP servers <span id="mcp-count" class="side-count"></span></span>
      <span class="chev" id="mcp-chev">&#9656;</span>
    </div>
    <div id="mcp-list" class="collapsible hidden"><div class="no-convos">No servers configured.</div></div>
    <div class="side-footer"><a href="/about" target="_blank">About GifteQChat</a></div>
  </aside>

  <main>
    <header>
      <div class="brand">
        <button class="menu-btn" onclick="toggleSidebar()" aria-label="Menu">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
        </button>
        <div class="brand-logo">G</div>
          <div class="brand-text">
          <div class="brand-name">GifteQChat</div>
          <div class="brand-desc">Chat &middot; Tools &middot; Documents &middot; Memory &middot; Agents</div>
        </div>
      </div>
      <div class="badge"><span class="status-dot"></span>Model: <b id="model-badge">loading...</b></div>
    </header>

    <div id="messages">
      <div class="messages-inner" id="msg-inner">
        <div class="welcome" id="welcome">
          <div class="logo">G</div>
          <h1>Ask away.</h1>
          <p>Chat freely. It searches the web, checks your documents, and remembers what you tell it, automatically.</p>
          <div id="setup" style="display:none" class="notice"></div>
          <div class="chips">
            <button class="chip" onclick="ask('Search the web for today\'s news')">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              Search the web
            </button>
            <button class="chip" onclick="ask('Use run_python to compute the 30 first Fibonacci numbers and their sum')">
              <svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
              Run some Python
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
    for (const m of convos[id].messages) inner.append(messageNode(m.role, m.content, false, m.images));
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

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* Tiny safe Markdown: escape everything first, then re-add trusted tags.
   Code is lifted out before the prose passes run: otherwise the heading and
   list rules, which are line-based over the whole string, rewrite the contents
   of code blocks (a Python `# comment` would turn into an <h3>). */
function mdToHtml(src) {
  let html = escHtml(String(src));
  const stash = [];
  const hold = (h) => "%%MD" + (stash.push(h) - 1) + "%%";

  html = html.replace(/```([a-zA-Z0-9_+-]*)[ \t]*\n?([\s\S]*?)```/g,
    (_, lang, c) => "%%BLK" + (stash.push(
      `<pre><code data-lang="${lang}">${c.replace(/\n$/, "")}</code></pre>`) - 1) + "%%");
  html = html.replace(/`([^`\n]+)`/g, (_, c) => hold(`<code>${c}</code>`));
  html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  html = html.replace(/^### (.*)$/gm, "<h4>$1</h4>");
  html = html.replace(/^(#{1,2}) (.*)$/gm, "<h3>$2</h3>");
  html = html.replace(/^[-*] (.*)$/gm, "&bull; $1");
  // The bubble renders with pre-wrap, so newlines around a block-level frame
  // would show up as blank space: swallow them with the placeholder.
  return html
    .replace(/[ \t]*\n?[ \t]*%%BLK(\d+)%%[ \t]*\n?/g, (_, i) => stash[i])
    .replace(/%%MD(\d+)%%/g, (_, i) => stash[i]);
}

/* Wrap each block of code in a frame with its language and a copy button.
   textContent is copied, so what lands on the clipboard is the code exactly as
   the model wrote it, with no markup and no leading prompt characters. */
function enhanceCodeBlocks(root) {
  root.querySelectorAll("pre > code").forEach((code) => {
    const pre = code.parentElement;
    if (pre.dataset.framed) return;
    pre.dataset.framed = "1";

    const frame = document.createElement("div");
    frame.className = "code-block";
    const bar = document.createElement("div");
    bar.className = "code-bar";
    const lang = document.createElement("span");
    lang.className = "code-lang";
    lang.textContent = code.dataset.lang || "code";
    const btn = document.createElement("button");
    btn.className = "code-copy";
    btn.textContent = "Copy";
    btn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(code.textContent);
        btn.textContent = "Copied";
      } catch (e) {
        btn.textContent = "Press Ctrl+C";
      }
      setTimeout(() => { btn.textContent = "Copy"; }, 1600);
    };
    bar.appendChild(lang);
    bar.appendChild(btn);

    pre.replaceWith(frame);
    frame.appendChild(bar);
    frame.appendChild(pre);
  });
}

const IMG_RE = /\[\[IMG:[0-9a-f]+\]\]/g;

function typesetMath(el) {
  try {
    if (window.renderMathInElement) {
      renderMathInElement(el, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
        ],
        throwOnError: false,
      });
    }
  } catch (e) {}
}

/* Models often wrap images as ![alt](file). Normalize before rendering: a
   markdown ref to a sandbox-local file can never load in the browser, so it is
   either redundant (the real image rides along as a token) or a dead link. */
function normalizeImages(src, images) {
  const out = String(src).replace(/!\[[^\]]*\]\(\s*(\[\[IMG:[0-9a-f]+\]\])\s*\)/g, "$1");
  const deadRef = /!\[[^\]]*\]\((?!https?:\/\/|\/|data:)[^)]*\)/g;
  return (images && images.length)
    ? out.replace(deadRef, "")
    : out.replace(deadRef, "\n_(the image could not be generated)_\n");
}

function toolLabel(name) {
  let n = String(name).replace(/^mcp_[^_]+_/, "").replace(/_/g, " ");
  return n;
}

function messageNode(role, text, note, images, tools) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = role === "user" ? "You" : "GifteQChat";
  wrap.appendChild(who);
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "user") {
    bubble.textContent = text;
  } else {
    const clean = normalizeImages(text, images);
    const parts = clean.split(IMG_RE);
    const matches = clean.match(IMG_RE) || [];
    parts.forEach((part, i) => {
      if (part) {
        const seg = document.createElement("span");
        seg.style.display = "block";
        seg.innerHTML = mdToHtml(part);
        bubble.appendChild(seg);
      }
      const tok = matches[i];
      if (!tok) return;
      const info = (images || []).find((x) => x.token === tok);
      if (!info) return; // stale token from an old chat: drop it
      const img = document.createElement("img");
      img.src = info.url;
      img.alt = "chart generated by the agent";
      img.className = "chat-img";
      /* Images live in the server's memory, so tokens from a chat that predates
         the last restart no longer resolve. Say so instead of showing a broken
         image icon. */
      img.onerror = () => {
        const gone = document.createElement("span");
        gone.className = "img-gone";
        gone.textContent = "(image from an earlier session is no longer available)";
        img.replaceWith(gone);
      };
      bubble.appendChild(img);
    });
    enhanceCodeBlocks(bubble);
    typesetMath(bubble);
  }
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
  if (role === "ai" && tools && tools.length) {
    const used = document.createElement("div");
    used.className = "msg-tools";
    const label = document.createElement("span");
    label.className = "tools-label";
    label.textContent = "tools:";
    used.appendChild(label);
    for (const t of tools) {
      const chip = document.createElement("span");
      chip.className = "tool-chip";
      chip.textContent = toolLabel(t);
      chip.title = t;
      used.appendChild(chip);
    }
    wrap.appendChild(used);
  }
  return wrap;
}

function addMessage(role, text, note, images, tools) {
  const inner = document.getElementById("msg-inner");
  inner.appendChild(messageNode(role, text, note, images, tools));
  document.getElementById("messages").scrollTop = document.getElementById("messages").scrollHeight;
}

function setBusy(state) {
  busy = state;
  document.getElementById("send").disabled = state;
  document.getElementById("input").disabled = state;
}

function toggleMcp() {
  const list = document.getElementById("mcp-list");
  list.classList.toggle("hidden");
  document.getElementById("mcp-chev").innerHTML = list.classList.contains("hidden") ? "&#9656;" : "&#9662;";
}

async function refreshMcp() {
  let data;
  try {
    const r = await fetch("/mcp", { method: "POST" });
    data = await r.json();
  } catch (e) { return; }
  const servers = data.servers || [];
  // Keep the section collapsed by default; just surface how many are connected.
  document.getElementById("mcp-count").textContent = servers.length ? `(${servers.length})` : "";
  const list = document.getElementById("mcp-list");
  if (!servers.length) {
    list.innerHTML = '<div class="no-convos">No servers configured.</div>';
    return;
  }
  list.innerHTML = "";
  for (const s of servers) {
    const item = document.createElement("div");
    item.className = "doc-item";
    const row = document.createElement("div");
    row.className = "doc-row";
    const dot = document.createElement("span");
    dot.className = "status-dot";
    dot.style.background = s.ok ? "var(--success)" : "var(--danger)";
    const name = document.createElement("span");
    name.className = "doc-name";
    name.textContent = s.server_name ? s.server_name : s.name;
    name.title = s.ok ? "" : s.error;
    row.appendChild(dot);
    row.appendChild(name);
    item.appendChild(row);
    if (s.ok && s.tools && s.tools.length) {
      const tools = document.createElement("div");
      tools.className = "mcp-tools";
      for (const t of s.tools) {
        const chip = document.createElement("span");
        chip.className = "tool-chip";
        chip.textContent = t.replace(/^mcp_[^_]+_/, "");
        chip.title = t;
        tools.appendChild(chip);
      }
      item.appendChild(tools);
    } else if (!s.ok) {
      const err = document.createElement("div");
      err.className = "mcp-error";
      err.textContent = s.error;
      item.appendChild(err);
    }
    list.appendChild(item);
  }
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
  typing.innerHTML = '<div class="who">GifteQChat</div><div class="bubble"><span></span><span></span><span></span></div>';
  document.getElementById("msg-inner").appendChild(typing);
  document.getElementById("messages").scrollTop = document.getElementById("messages").scrollHeight;
  setBusy(true);

  const history = currentMessages();
  history.push({ role: "user", content: userText });
  save();

  const payload = { messages: history.map((m) => ({ role: m.role, content: m.content })) };
  try {
    const ok = await streamChat(payload, typing);
    if (!ok) await fallbackChat(payload, typing);
  } catch (e) {
    await fallbackChat(payload, typing);
  } finally {
    save();
    renderSidebar();
    setBusy(false);
    try { document.getElementById("input").disabled = false; } catch (_) {}
  }
}

function scrollBottom() {
  const m = document.getElementById("messages");
  m.scrollTop = m.scrollHeight;
}

/* Hide a 'thinking' model's <think> reasoning and any raw tool-call markup it
   leaks into the stream (e.g. <tool_code>...). The real answer is shown; the
   thinking/tools are processed server-side, not as visible prose. */
function stripLeak(raw) {
  let s = raw || "";
  const t = s.indexOf("<think>");
  if (t !== -1) {
    const c = s.indexOf("</think>", t);
    if (c === -1) return s.slice(0, t);   // thinking in progress: hide it live
    s = s.slice(0, t) + s.slice(c + "</think>".length);
  }
  s = s.replace(/<tool_code>[\s\S]*?<\/tool_code>/g, "")
       .replace(/<function_calls>[\s\S]*?<\/function_calls>/g, "")
       .replace(/<invoke[\s\S]*?<\/invoke>/g, "")
       .replace(/<tool_call>[\s\S]*?<\/tool_call>/g, "");
  return s;
}

async function streamChat(payload, typing) {
  const bubble = typing.querySelector(".bubble");
  bubble.innerHTML = "";
  const status = document.createElement("div");
  status.className = "tool-status";
  const textEl = document.createElement("div");
  bubble.appendChild(status);
  bubble.appendChild(textEl);
  let acc = "";
  try {
    const res = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("status " + res.status);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const data = JSON.parse(line.slice(6));
        if (data.type === "token") {
          acc += data.text;
          textEl.innerHTML = mdToHtml(stripLeak(acc));
          enhanceCodeBlocks(textEl);
          typesetMath(textEl);
          scrollBottom();
        } else if (data.type === "tool") {
          status.textContent = "Using " + toolLabel(data.name) + "…";
        } else if (data.type === "done") {
          finalizeStream(typing, data);
          return true;
        } else if (data.type === "error") {
          throw new Error(data.text);
        }
      }
    }
    return true;
  } catch (e) {
    return false;
  }
}

function finalizeStream(typing, data) {
  typing.remove();
  if (data.no_key) {
    showSetup(data.setup);
    const users = document.querySelectorAll("#msg-inner .msg.user");
    if (users.length) users[users.length - 1].remove();
    currentMessages().pop();
    document.getElementById("welcome").style.display = "";
    return;
  }
  hideSetup();
  addMessage("ai", data.reply, data.used_docs, data.images, data.tools_used);
  currentMessages().push({ role: "assistant", content: data.reply, images: data.images || [] });
  fetchBadge(data.model);
}

async function fallbackChat(payload, typing) {
  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    typing.remove();
    if (data.no_key) {
      showSetup(data.setup);
      const users = document.querySelectorAll("#msg-inner .msg.user");
      if (users.length) users[users.length - 1].remove();
      currentMessages().pop();
      document.getElementById("welcome").style.display = "";
    } else {
      hideSetup();
      addMessage("ai", data.reply, data.used_docs, data.images, data.tools_used);
      currentMessages().push({ role: "assistant", content: data.reply, images: data.images || [] });
      fetchBadge(data.model);
    }
  } catch (e) {
    typing.remove();
    addMessage("ai", "Connection error. Is the server still running?");
    currentMessages().pop();
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
refreshMcp();

/* KaTeX loads with defer, i.e. after this script: typeset history once ready. */
window.addEventListener("load", () => {
  document.querySelectorAll("#msg-inner .msg.ai .bubble").forEach(typesetMath);
});
</script>
</body>
</html>
"""


def _clean_reply(text):
    """Strip reasoning (`<think>`) and raw tool-call markup (`<tool_code>`, etc.)
    that some 'thinking' models leak into the visible text. Code fences are left
    intact; only the specific known tags are removed."""
    if not text:
        return text
    s = text
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL)
    for tag in ("tool_code", "function_calls", "tool_call", "invoke"):
        s = re.sub(r"<" + tag + r"[^>]*>.*?</" + tag + r">", "", s, flags=re.DOTALL)
    # Drop any trailing, not-yet-closed block (e.g. mid-stream thinking).
    s = re.sub(r"<think>.*$", "", s, flags=re.DOTALL)
    s = re.sub(r"<tool_code>.*$", "", s, flags=re.DOTALL)
    s = re.sub(r"<function_calls>.*$", "", s, flags=re.DOTALL)
    return s.strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _authed(self):
        if not AUTH_ENABLED:
            return True
        cookie = self.headers.get("Cookie", "")
        return (SESSION_COOKIE + "=" + SESSION_TOKEN) in cookie

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        route = urlparse(self.path).path
        # Gate everything except the login page, the public about page and images.
        if AUTH_ENABLED and not self._authed() and route not in ("/login", "/about") and not route.startswith("/image/"):
            return self._send(200, LOGIN_HTML.replace("__ERR__", ""), "text/html; charset=utf-8")
        if route == "/login":
            return self._send(200, LOGIN_HTML.replace("__ERR__", ""), "text/html; charset=utf-8")
        if self.path in ("/", "/index.html"):
            self._send(200, HTML, "text/html; charset=utf-8")
        elif route.startswith("/image/"):
            data, mime = media.get(unquote(route[len("/image/"):]))
            if not data:
                return self._send(404, "Not found", "text/plain")
            raw = self.wfile
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, max-age=3600")
            self.end_headers()
            raw.write(data)
        elif route == "/about":
            self._send(200, ABOUT_HTML, "text/html; charset=utf-8")
        else:
            self._send(404, "Not found", "text/plain")

    def do_POST(self):
        route = urlparse(self.path).path

        if route == "/login":
            try:
                body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)).decode("utf-8")
                pw = parse_qs(body).get("password", [""])[0]
            except Exception:
                pw = ""
            if pw == AUTH_PASSWORD:
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"{SESSION_COOKIE}={SESSION_TOKEN}; Path=/; HttpOnly; SameSite=Lax")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send(200, LOGIN_HTML.replace("__ERR__", "Incorrect password."), "text/html; charset=utf-8")
            return

        if AUTH_ENABLED and not self._authed():
            self._send(401, json.dumps({"error": "unauthorized"}), "application/json")
            return

        if route == "/chat":
            return self.chat()
        if route == "/chat/stream":
            return self.stream_chat()
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
        if self.path == "/mcp":
            return self._send(200, json.dumps({"servers": mcp_client.status()}), "application/json")
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

        # Never forward client bookkeeping (image tokens...) to the provider:
        # chat-completions only accepts role/content here.
        history = [
            {"role": str(m.get("role", "user")), "content": str(m.get("content") or "")}
            for m in body.get("messages", [])
            if isinstance(m, dict)
        ]
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
        reply = _clean_reply(reply)
        # Deterministic display: append any chart the tools produced, whether or
        # not the model copied the [[IMG:...]] marker into its prose.
        for tok in agent.pop_images():
            if tok not in reply:
                reply += "\n\n" + tok
        tokens = re.findall(r"\[\[IMG:[0-9a-f]+\]\]", reply)
        images = [{"token": t, "url": "/image/" + quote(t.strip("[]"), safe="")} for t in tokens]
        self._send(200, json.dumps({
            "reply": reply, "images": images, "no_key": False, "model": cfg["model"],
            "used_docs": "search_documents" in tool_trace,
            "tools_used": tool_trace,
        }), "application/json")


    def stream_chat(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send(400, json.dumps({"error": "Bad JSON"}), "application/json")
            return
        history = [
            {"role": str(m.get("role", "user")), "content": str(m.get("content") or "")}
            for m in body.get("messages", [])
            if isinstance(m, dict)
        ]
        cfg = get_config()

        def _sse(payload):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode("utf-8"))
            self.wfile.flush()

        if not cfg["api_key"]:
            setup = ("No API key found.<br>"
                     "The easy and free way: <code>export AI_AGENT_PROVIDER=ollama</code> "
                     "(install Ollama first).<br>"
                     "Or use Groq / OpenRouter: <code>export AI_AGENT_KEY=...</code> "
                     "and restart the server.")
            _sse({"type": "done", "no_key": True, "reply": None,
                  "model": cfg["model"], "setup": setup})
            return
        if not history:
            _sse({"type": "done", "no_key": False, "reply": None, "model": cfg["model"]})
            return

        messages = [{"role": "system", "content": cfg["system_prompt"]}] + history
        tool_trace = []
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        full = []
        try:
            for ev in agent.stream_run_with_messages(messages, tool_trace=tool_trace):
                if ev[0] == "token":
                    full.append(ev[1])
                    self.wfile.write(("data: " + json.dumps({"type": "token", "text": ev[1]}) + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                elif ev[0] == "tool":
                    self.wfile.write(("data: " + json.dumps({"type": "tool", "name": ev[1]}) + "\n\n").encode("utf-8"))
                    self.wfile.flush()
            reply = "".join(full)
            reply = _clean_reply(reply)
            for tok in agent.pop_images():
                if tok not in reply:
                    reply += "\n\n" + tok
            tokens = re.findall(r"\[\[IMG:[0-9a-f]+\]\]", reply)
            images = [{"token": t, "url": "/image/" + quote(t.strip("[]"), safe="")} for t in tokens]
            self.wfile.write(("data: " + json.dumps({
                "type": "done", "reply": reply, "images": images,
                "model": cfg["model"], "used_docs": "search_documents" in tool_trace,
                "tools_used": tool_trace,
            }) + "\n\n").encode("utf-8"))
            self.wfile.flush()
        except agent.APIError as e:
            self.wfile.write(("data: " + json.dumps({"type": "error", "text": "Provider error: " + str(e)}) + "\n\n").encode("utf-8"))
        except Exception as e:
            self.wfile.write(("data: " + json.dumps({"type": "error", "text": "Unexpected error: " + str(e)}) + "\n\n").encode("utf-8"))

def main():
    cfg = get_config()
    print(f"GifteQChat ready: http://localhost:{PORT}")
    print(f"Provider: {cfg['provider']}  |  Model: {cfg['model']}")
    if not cfg["api_key"]:
        print("Warning: no AI_AGENT_KEY set. Set AI_AGENT_PROVIDER=ollama or export AI_AGENT_KEY=...")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()