import io
import json
import os
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import memory
import mcp_client
import rag
import sandbox
from agent import SUBAGENTS, _tools_for_roles, call_tool, delegate_task, get_config, get_tools, APIError

# never let the test suite connect to a real data/mcp.json
mcp_client.CONFIG_PATH = os.path.join(tempfile.gettempdir(), "ai-services-no-mcp.json")
mcp_client.reset()


def check(name, cond, extra=""):
    if cond:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name} {extra}")
        raise SystemExit(1)


# --- RAG ---
with tempfile.TemporaryDirectory() as tmp:
    rag.DATA_DIR = tmp
    rag.STORE_PATH = os.path.join(tmp, "documents.json")
    rag.DOCS = []
    rag._load()

    text = (b"The Eiffel Tower is in Paris, France. It was built in 1889 and is 330 meters tall.\n"
            b"The Sagrada Familia is a church in Barcelona, Spain. It started in 1882.\n"
            b"The Statue of Liberty is in New York, USA.\n")
    r = rag.add_document("../Evil/../landmarks.txt", text)
    check("upload txt ok", r["ok"], str(r))

    check("name sanitized", r["name"] == "landmarks.txt", r["name"])

    hits = rag.retrieve("How tall is the Eiffel Tower?", top_k=2)
    check("retrieval finds doc", len(hits) > 0, str(hits))
    check("retrieval top text contains 'Eiffel'", "Eiffel" in hits[0]["text"])

    # a PDF extracted as one dense block (no blank lines) must still get split;
    # otherwise a single chunk can carry the whole document and blow past a
    # provider's per-request token limit
    dense_doc = rag.add_document("dense.txt", ("word " * 5000).encode())
    check("dense single-paragraph doc gets split", dense_doc["ok"] and dense_doc["chunks"] > 1, str(dense_doc))
    rag.remove_document(dense_doc["id"])

    r2 = rag.add_document("landmarks.txt", b"New content about the Pyramids of Giza in Egypt, built around 2560 BC.")
    check("dedupe replaces same name", r2["ok"] and len(rag.list_documents()[0]) == 1, str(r2))
    check("old content gone", rag.retrieve("Eiffel") == [], str(rag.retrieve("Eiffel")))

    corrupted = rag.add_document("broken.docx", b"not-a-real-docx")
    check("corrupt docx handled", not corrupted["ok"], str(corrupted))

    bad = rag.add_document("evil.exe", b"hello")
    check("unsupported ext handled", not bad["ok"], str(bad))

    empty = rag.add_document("empty.txt", b"")
    check("empty file handled", not empty["ok"], str(empty))

    # persistence
    import importlib
    importlib.reload(rag)
    rag.DATA_DIR = tmp
    rag.STORE_PATH = os.path.join(tmp, "documents.json")
    rag.DOCS = []
    rag._load()
    docs, _ = rag.list_documents()
    check("docs persist on reload", len(docs) == 1, str(docs))

    # max docs
    for i in range(2, 8):
        rag.add_document(f"doc{i}.txt", f"Unique content for document number {i} here.".encode())
    docs, remaining = rag.list_documents()
    check("max docs respected", len(docs) == rag.MAX_DOCS, f"{len(docs)}/{rag.MAX_DOCS}")

    removed = rag.remove_document(docs[0]["id"])
    check("remove works", removed)

# --- AGENT ---
t = call_tool("web_search", {"query": "test"})
check("web_search graceful when missing", "error" in t, str(t))

check("unknown tool", "error" in call_tool("nope", {}))

# --- SANDBOX (code interpreter) ---
r = sandbox.run_python("print(21 * 2)")
check("run_python executes and returns stdout", r.get("exit_code") == 0 and "42" in r["stdout"], str(r))

project_cwd = os.getcwd()
r = sandbox.run_python("import os; print(os.getcwd())")
check("run_python runs outside the project dir",
      r.get("exit_code") == 0 and os.path.realpath(r["stdout"].strip()) != os.path.realpath(project_cwd), str(r))

r = sandbox.run_python("x = 1 / 0")
check("run_python surfaces tracebacks", r.get("exit_code") != 0 and "ZeroDivisionError" in r["stderr"], str(r))

check("run_python rejects empty code", "error" in sandbox.run_python("   "), str(sandbox.run_python("")))

r = sandbox.run_python("while True: pass", timeout=2)
check("run_python kills runaway code", r.get("timed_out") is True, str(r))

t = call_tool("run_python", {"code": "print(sum(range(11)))"})
check("call_tool routes run_python", t.get("exit_code") == 0 and "55" in t["stdout"], str(t))

# --- MEDIA (charts produced by run_python) ---
import media

r = sandbox.run_python(
    "import matplotlib\n"
    "matplotlib.use('Agg')\n"
    "import matplotlib.pyplot as plt\n"
    "x = [i / 10 for i in range(-30, 31)]\n"
    "plt.plot(x, [v * v for v in x])\n"
    "plt.savefig('quadratic.png')\n"
    "print('saved')\n",
    timeout=60,
)
check("matplotlib chart runs in sandbox", r.get("exit_code") == 0 and "saved" in r.get("stdout", ""), str(r)[:400])
check("sandbox collects the produced image", len(r.get("images", [])) == 1, str(r)[:400])

token = r["images"][0]
data, mime = media.get(token)
check("image token resolves to png bytes", data is not None and mime == "image/png" and data[:4] == b"\x89PNG", str(mime))
check("tool result carries no raw bytes", "base64" not in json.dumps(sandbox.run_python("print('x')")))

check("media rejects garbage b64", media.store_b64("x.png", "!!!not-b64!!!") is None)
check("media rejects oversized images", media.store_b64("x.png", "QUFB" * 300000) is None)

ok_token = media.store_b64("tiny.png", "iVBORw0KGgo=")
check("media stores valid b64", ok_token and media.get(ok_token)[1] == "image/png", str(ok_token))
media.clear()

# deterministic image pipeline: tool -> buffer -> pop, even if model forgets token
import agent
code = ("import matplotlib; matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([0, 1]); plt.savefig('t.png')\n")
r = agent.call_tool("run_python", {"code": code})
produced = agent.pop_images()
check("produced images land in pop_images", len(produced) == 1 and produced[0] == r["images"][0], str(produced))
check("pop_images drains", agent.pop_images() == [])
agent.pop_images()  # leave clean state for later sections

# --- SUB-AGENTS ---
t = delegate_task("wizard", "do magic")
check("delegate rejects unknown role", "error" in t, str(t))

t = delegate_task("researcher", "")
check("delegate rejects empty task", "error" in t, str(t))

for role, spec in SUBAGENTS.items():
    names = [tool["function"]["name"] for tool in _tools_for_roles(spec["allow"])]
    check(f"{role} allow-list respected", set(names) == set(spec["allow"]), str(names))
    check(f"{role} cannot delegate", "delegate_task" not in names, str(names))

all_names = [t["function"]["name"] for t in get_tools()]
check("orchestrator gets every built-in tool",
      {"web_search", "search_documents", "remember", "recall_memory", "run_python", "delegate_task"} <= set(all_names),
      str(all_names))
no_delegate = [t["function"]["name"] for t in get_tools(include_delegate=False)]
check("include_delegate=False drops delegation only", "delegate_task" not in no_delegate and "run_python" in no_delegate,
      str(no_delegate))

# --- MCP CLIENT (fake stdio server, end to end) ---
FAKE_SERVER = textwrap.dedent("""
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in msg or "method" not in msg:
            continue
        method, mid = msg["method"], msg["id"]
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fake-mcp", "version": "0.0.1"}}
        elif method == "tools/list":
            result = {"tools": [{
                "name": "echo",
                "description": "Echo the given text back.",
                "inputSchema": {"type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"]},
            }]}
        elif method == "tools/call":
            text = msg["params"].get("arguments", {}).get("text", "")
            result = {"content": [{"type": "text", "text": "echo:" + text}]}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": mid,
                              "error": {"code": -32601, "message": "unknown method"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}), flush=True)
""")

mcp_client.reset()
with tempfile.TemporaryDirectory() as tmp:
    server_path = os.path.join(tmp, "fake_mcp_server.py")
    with open(server_path, "w", encoding="utf-8") as f:
        f.write(FAKE_SERVER)

    mcp_client.configure({"test": {"command": sys.executable, "args": [server_path],
                                   "env": {"PYTHONUNBUFFERED": "1"}}})
    st = mcp_client.status()
    check("mcp server connects", len(st) == 1 and st[0]["ok"], str(st))

    specs = mcp_client.tool_specs()
    check("mcp tool discovered with openai-safe name",
          any(s["function"]["name"] == "mcp_test_echo" for s in specs), str([s["function"]["name"] for s in specs]))

    t = mcp_client.route_call("mcp_test_echo", {"text": "hello"})
    check("mcp tool round-trip", t.get("content") == "echo:hello", str(t))

    check("unknown mcp tool errors", "error" in mcp_client.route_call("mcp_nope_x", {}))

    t = call_tool("mcp_test_echo", {"text": "via agent"})
    check("agent routes mcp tools", t.get("content") == "echo:via agent", str(t))

    all_names = [s["function"]["name"] for s in get_tools()]
    check("mcp tools appear in get_tools", "mcp_test_echo" in all_names, str(all_names))

    mcp_client.shutdown()

st = mcp_client.status()
check("shutdown marks servers down", not any(s["ok"] for s in st), str(st))
mcp_client.reset()

# --- DOCUMENTS ---

t = call_tool("search_documents", {"query": "document number 3"})
check("search_documents finds a remaining doc", "results" in t and any("number 3" in r["excerpt"] for r in t["results"]), str(t))

t = call_tool("search_documents", {"query": ""})
check("search_documents requires a query", "error" in t, str(t))

# --- MEMORY ---
with tempfile.TemporaryDirectory() as tmp:
    memory.DATA_DIR = tmp
    memory.STORE_PATH = os.path.join(tmp, "memory.json")
    memory.MEMORIES = []

    t = call_tool("remember", {"information": "The user is vegetarian."})
    check("remember tool saves", t.get("result") == "Noted.", str(t))

    t = call_tool("recall_memory", {"query": "vegetarian"})
    check("recall_memory finds saved fact", "results" in t and any("vegetarian" in r["memory"] for r in t["results"]), str(t))

    t = call_tool("recall_memory", {"query": "something with no keyword overlap at all"})
    check("recall_memory falls back to recent when no match", "results" in t, str(t))

    empty = call_tool("remember", {"information": ""})
    check("remember rejects empty fact", "error" in empty, str(empty))

    removed = memory.forget(memory.MEMORIES[0]["id"])
    check("forget removes a memory", removed and not memory.MEMORIES, str(memory.MEMORIES))

# --- FRONTEND WIRING ---
# The image pipeline is correct end to end on the server, yet charts still went
# missing because the browser dropped the images payload on the way to the
# renderer. These guard that plumbing, which has no other test coverage.
import webapp

UI = webapp.HTML
check("addMessage forwards images to messageNode",
      "function addMessage(role, text, note, images)" in UI
      and "messageNode(role, text, note, images)" in UI)
check("chat response images reach the renderer",
      'addMessage("ai", data.reply, data.used_docs, data.images)' in UI)
check("images are kept in the stored conversation",
      "images: data.images || []" in UI)
check("reloading a chat re-renders its images",
      "messageNode(m.role, m.content, false, m.images)" in UI)
check("only role/content are sent to the model",
      "history.map((m) => ({ role: m.role, content: m.content }))" in UI)
check("a token that no longer resolves degrades to a note", "img.onerror" in UI)

# server-side: client bookkeeping must never reach the provider payload
handler = webapp.Handler.__new__(webapp.Handler)
sent = {}
handler._send = lambda code, body, ctype: sent.update(json.loads(body))
handler.headers = {"Content-Length": "0"}


class _FakeRfile:
    def __init__(self, raw):
        self.raw = raw

    def read(self, n):
        return self.raw


captured = {}


def _fake_run(messages, tool_trace=None):
    captured["messages"] = messages
    return "ok"


payload = json.dumps({"messages": [
    {"role": "user", "content": "hi", "images": [{"token": "[[IMG:dead]]"}], "junk": 1},
]}).encode()
handler.rfile = _FakeRfile(payload)
handler.headers = {"Content-Length": str(len(payload))}
_real_run, webapp.run_with_messages = webapp.run_with_messages, _fake_run
try:
    handler.chat()
finally:
    webapp.run_with_messages = _real_run

user_msgs = [m for m in captured.get("messages", []) if m["role"] == "user"]
check("server strips non-schema message fields",
      user_msgs and set(user_msgs[0]) == {"role", "content"}, str(user_msgs))

os.environ["AI_AGENT_MODEL"] = "qwen/qwen3.6-27b"
check("model override from env", get_config()["model"] == "qwen/qwen3.6-27b")
os.environ.pop("AI_AGENT_MODEL", None)

try:
    raise APIError("boom")
except APIError:
    check("APIError importable", True)

print("\nAll tests passed.")