import json
import os
import threading
import time

import requests

import memory
import mcp_client
import rag
import sandbox


def load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)


load_env()

DEFAULT_CONFIG = {
    "provider": "ollama",  # groq | openrouter | ollama | openai
    "model": "llama3.2",
    "base_url": "http://localhost:11434/v1",
    "api_key": os.environ.get("AI_AGENT_KEY", "ollama"),
    "max_steps": 8,
    "system_prompt": (
        "You are GifteQChat, a helpful assistant with access to tools. "
        "Use web_search for current events or anything that requires the internet. "
        "Use search_documents whenever the question could be about the user's uploaded documents; "
        "answer only from what the tool returns, and say so plainly if nothing relevant is found. "
        "Never invent document content. "
        "Use run_python to compute anything mathematical or data-related, test logic, or process text; "
        "write complete standalone scripts that print their results. To show a chart or plot, save it as a "
        "PNG file with matplotlib (plt.savefig('plot.png')); it will be displayed automatically. "
        "Report only what tools actually returned: never claim a file was created or a computation "
        "succeeded unless the tool result confirms it; if code fails, say so and fix it. "
        "Use remember when the user tells you something worth keeping for later (preferences, facts about them). "
        "Use recall_memory when a question might be answered by something saved earlier. "
        "For complex multi-part requests, delegate parts to specialist sub-agents with delegate_task: "
        "'researcher' for web research, 'doc_analyst' for questions about the user's documents, "
        "'analyst' for calculations or code execution. Give each one a clear, self-contained task; "
        "then combine their reports into your final answer. "
        "Answer directly when no tool is needed. Be concise. "
        "Never use Markdown tables; present comparisons or structured information "
        "as bullet lists, numbered lists, or short prose instead. "
        "When a file tool reports an absolute path, include that full path in your "
        "reply so the user knows exactly where the file lives."
    ),
    "temperature": 0.3,
    "max_retries": 3,
    "timeout": 90,
}

CONFIGS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "qwen/qwen3.6-27b"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "deepseek/deepseek-chat:free"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "llama3.2", "api_key": "ollama"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}

RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}
class APIError(Exception):
    pass


def get_config():
    cfg = dict(DEFAULT_CONFIG)
    provider = os.environ.get("AI_AGENT_PROVIDER", "ollama")
    cfg["provider"] = provider
    if provider in CONFIGS:
        cfg.update(CONFIGS[provider])
        cfg["api_key"] = os.environ.get("AI_AGENT_KEY", cfg.get("api_key", ""))
    key = os.environ.get("AI_AGENT_KEY", "")
    if key:
        cfg["api_key"] = key
    model = os.environ.get("AI_AGENT_MODEL", "").strip()
    if model:
        cfg["model"] = model
    return cfg


BASE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for a query",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Search the user's uploaded documents for relevant passages. "
                "Use for any question that could be about a document the user uploaded."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Save an important fact about the user or their preferences for future conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "information": {
                        "type": "string",
                        "description": "The fact to remember, as a short standalone sentence.",
                    }
                },
                "required": ["information"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Search previously saved facts or memories about the user from past conversations.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Execute a standalone Python script in an isolated sandbox and return stdout/stderr. "
                "Use for math, data processing, text analysis, or verifying logic. "
                "To display a chart or figure to the user, save it as PNG with matplotlib "
                "(plt.savefig('plot.png'), never plt.show()); it is shown to them automatically. "
                "If the tool result contains [[IMG:...]] markers, copy them unchanged into your final "
                "answer where the image belongs. "
                "Base your report strictly on the tool output; never claim success you don't see."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Complete Python script to run."},
                    "timeout": {
                        "type": "number",
                        "description": "Optional max runtime in seconds (1-60, default 15).",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_task",
            "description": (
                "Delegate a self-contained sub-task to a specialist sub-agent and get its report back. "
                "Roles: researcher (web research), doc_analyst (answers from the user's documents), "
                "analyst (calculations and Python execution). "
                "Use for complex requests with several independent parts, or to keep heavy research "
                "out of the main conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["researcher", "doc_analyst", "analyst"],
                        "description": "Which specialist to delegate to.",
                    },
                    "task": {
                        "type": "string",
                        "description": "Clear, self-contained instructions and context for the sub-agent.",
                    },
                },
                "required": ["role", "task"],
            },
        },
    },
]

# Sub-agents can only use tools from their allow-list, and never delegate_task
# itself: delegation never recurses.
SUBAGENTS = {
    "researcher": {
        "allow": ["web_search"],
        "prompt": (
            "You are a web research specialist. Research the task using web_search "
            "(several targeted queries if needed), then write a concise report of your findings. "
            "State clearly when information could not be found or is uncertain."
        ),
    },
    "doc_analyst": {
        "allow": ["search_documents"],
        "prompt": (
            "You are a document analyst. Answer strictly from the user's documents using search_documents; "
            "quote the relevant passages you rely on. Never invent content, and say plainly when the "
            "documents do not contain the answer."
        ),
    },
    "analyst": {
        "allow": ["run_python"],
        "prompt": (
            "You are a computation specialist. Solve the task by writing and running Python with run_python. "
            "Show the key numbers/results in your final answer, computed not guessed. If code fails, fix it "
            "and retry before concluding."
        ),
    },
}


def _make_strict(spec):
    """Normalize a tool spec so strict schema providers (e.g. Groq) accept it and
    the model emits conformant arguments. Safe to call on every spec."""
    fn = spec.get("function", spec)
    params = fn.get("parameters") or {}
    if params.get("type") == "object" and "properties" in params:
        props = params.setdefault("properties", {})
        params["additionalProperties"] = False
        req = params.setdefault("required", list(props.keys()))
        for p in props:
            if p not in req:
                req.append(p)
    fn["strict"] = True
    return spec


def get_tools(include_delegate=True):
    base = list(BASE_TOOLS) if include_delegate else [t for t in BASE_TOOLS if t["function"]["name"] != "delegate_task"]
    tools = [_make_strict(t) for t in base]
    try:
        tools += [_make_strict(t) for t in mcp_client.tool_specs()]
    except Exception:
        pass
    return tools


def _tools_for_roles(allow):
    wanted = set(allow)
    return [t for t in BASE_TOOLS if t["function"]["name"] in wanted]


# Images produced by tools during a request, per thread (one request = one thread).
_ctx = threading.local()


def _images_buffer():
    if not hasattr(_ctx, "images"):
        _ctx.images = []
    return _ctx.images


def pop_images():
    """Tokens of images produced since the last run start (thread-local)."""
    out = list(_images_buffer())
    _ctx.images = []
    return out


def call_tool(name, args):
    args = args or {}
    try:
        if name == "web_search":
            query = str(args.get("query", ""))
            if not query:
                return {"error": "No query given."}
            try:
                from ddgs import DDGS  # duckduckgo_search was renamed to ddgs
            except ImportError:
                try:
                    from duckduckgo_search import DDGS
                except ImportError:
                    return {"error": "web_search is not installed. Run: pip install ddgs"}
            with DDGS() as ddgs:
                results = [
                    {"title": r.get("title", ""), "body": r.get("body", ""), "url": r.get("href", "")}
                    for r in ddgs.text(query, max_results=5)
                ]
            if not results:
                return {"result": "The web search returned no results for this query."}
            return {"results": results}
        if name == "search_documents":
            query = str(args.get("query", ""))
            if not query:
                return {"error": "No query given."}
            hits = rag.retrieve(query, top_k=3)
            if not hits:
                return {"result": "No uploaded documents match this query (or no documents have been uploaded)."}
            return {"results": [{"document": h["name"], "excerpt": h["text"]} for h in hits]}
        if name == "remember":
            info = str(args.get("information", ""))
            result = memory.remember(info)
            if not result.get("ok"):
                return {"error": result.get("error", "Could not save.")}
            return {"result": "Noted."}
        if name == "recall_memory":
            query = str(args.get("query", ""))
            hits = memory.recall(query)
            if not hits:
                return {"result": "No saved memories match this query."}
            return {"results": [{"memory": h["text"], "saved_at": h["ts"]} for h in hits]}
        if name == "run_python":
            result = sandbox.run_python(args.get("code"), args.get("timeout"))
            produced = result.get("images") or []
            if produced:
                seen = set(_images_buffer())
                for tok in produced:
                    if tok not in seen:
                        _images_buffer().append(tok)
                        seen.add(tok)
            return result
        if name == "delegate_task":
            return delegate_task(str(args.get("role", "")), args.get("task"))
        if name.startswith("mcp_"):
            return mcp_client.route_call(name, args)
        return {"error": f"unknown tool: {name}"}
    except Exception as e:
        return {"error": f"{name} failed: {e}"}


def _parse_http_error(r, body):
    detail = r.text[:300]
    try:
        j = r.json()
        detail = j.get("error", {}).get("message", detail)
    except Exception:
        pass
    hint = ""
    if r.status_code == 400:
        hint = " (the model produced an invalid request, often a malformed tool call; try rephrasing)"
    elif r.status_code == 401:
        hint = " (bad API key? check AI_AGENT_KEY)"
    elif r.status_code == 429:
        hint = " (rate limit)"
    elif r.status_code >= 500:
        hint = " (provider problem)"
    return f"HTTP {r.status_code}{hint}: {detail}"


def chat(cfg, messages, tools=None, timeout=None, retries=None):
    payload = {"model": cfg["model"], "messages": messages, "temperature": cfg["temperature"]}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    retries = retries if retries is not None else cfg["max_retries"]
    timeout = timeout or cfg["timeout"]
    deadline = time.time() + timeout * (retries + 1) + 2
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                f"{cfg['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg['api_key']}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=min(timeout, max(5, deadline - time.time())),
            )
            if r.status_code >= 200 and r.status_code < 300:
                return r.json()["choices"][0]["message"]
            if r.status_code not in RETRYABLE_CODES:
                raise APIError(_parse_http_error(r, r.text))
            last_err = _parse_http_error(r, r.text)
        except requests.exceptions.ConnectionError as e:
            last_err = f"Connection error: {e}"
        except requests.exceptions.Timeout as e:
            last_err = f"Request timed out ({timeout}s): {e}"
        if attempt < retries and time.time() < deadline:
            time.sleep(2 ** attempt)
    raise APIError(last_err)


def run_loop(cfg, messages, tools, max_steps, tool_trace=None):
    msgs = list(messages)
    toolset = tools
    for _ in range(max_steps):
        try:
            msg = chat(cfg, msgs, toolset)
        except APIError:
            # Provider rejected the request (often a malformed tool call under strict
            # schema validation). Retry without tools so the model answers directly.
            if toolset:
                toolset = []
                continue
            raise
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg.get("tool_calls")})
        if not msg.get("tool_calls"):
            return msg.get("content") or "(The model returned an empty response. Try rephrasing.)"
        for tc in msg.get("tool_calls") or []:
            raw_args = tc.get("function", {}).get("arguments") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}
            name = tc.get("function", {}).get("name", "?")
            if tool_trace is not None:
                tool_trace.append(name)
            result = call_tool(name, args)
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.get("id"),
                "content": json.dumps(result, ensure_ascii=False),
            })
    return "(max steps reached)"


def run_with_messages(messages, tool_trace=None):
    cfg = get_config()
    _ctx.images = []
    return run_loop(cfg, messages, get_tools(), cfg["max_steps"], tool_trace)


def chat_stream(cfg, messages, tools=None, timeout=None, retries=None):
    """Yield ("token", str) deltas and a final ("message", dict). Raises APIError."""
    payload = {"model": cfg["model"], "messages": messages, "temperature": cfg["temperature"],
               "stream": True}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    retries = retries if retries is not None else cfg["max_retries"]
    timeout = timeout or cfg["timeout"]
    deadline = time.time() + timeout * (retries + 1) + 2
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                f"{cfg['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
                json=payload, stream=True, timeout=min(timeout, max(5, deadline - time.time())),
            )
            if r.status_code < 200 or r.status_code >= 300:
                detail = r.text[:300]
                if r.status_code in RETRYABLE_CODES and attempt < retries and time.time() < deadline:
                    last_err = _parse_http_error(r, r.text)
                    time.sleep(2 ** attempt)
                    continue
                raise APIError(_parse_http_error(r, r.text) + f" ({detail})")
            content_buf = ""
            tools_acc = {}
            for raw in r.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8", "ignore")
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = obj.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    content_buf += delta["content"]
                    yield ("token", delta["content"])
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    acc = tools_acc.setdefault(idx, {"name": "", "arguments": ""})
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        acc["name"] += fn["name"]
                    if fn.get("arguments"):
                        acc["arguments"] += fn["arguments"]
            message = {"content": content_buf or "", "tool_calls": None}
            if tools_acc:
                tcs = []
                for idx in sorted(tools_acc):
                    a = tools_acc[idx]
                    try:
                        args = json.loads(a["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    tcs.append({"id": f"call_{idx}",
                                "function": {"name": a["name"], "arguments": json.dumps(args, ensure_ascii=False)}})
                message["tool_calls"] = tcs
            yield ("message", message)
            return
        except requests.exceptions.ConnectionError as e:
            last_err = f"Connection error: {e}"
        except requests.exceptions.Timeout as e:
            last_err = f"Request timed out ({timeout}s): {e}"
        if attempt < retries and time.time() < deadline:
            time.sleep(2 ** attempt)
    raise APIError(last_err)


def run_loop_stream(cfg, messages, tools, max_steps, tool_trace=None):
    msgs = list(messages)
    toolset = tools
    for _ in range(max_steps):
        msg = None
        try:
            for ev in chat_stream(cfg, msgs, toolset):
                if ev[0] == "token":
                    yield ("token", ev[1])
                elif ev[0] == "message":
                    msg = ev[1]
        except APIError:
            # Provider rejected the request (often a malformed tool call under strict
            # schema validation). Retry without tools so the model answers directly.
            if toolset:
                toolset = []
                continue
            raise
        if msg is None:
            return
        msgs.append({"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": msg.get("tool_calls")})
        if not msg.get("tool_calls"):
            yield ("message", msg)
            return
        for tc in msg.get("tool_calls") or []:
            raw_args = tc.get("function", {}).get("arguments") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}
            name = tc.get("function", {}).get("name", "?")
            if tool_trace is not None:
                tool_trace.append(name)
            yield ("tool", name)
            result = call_tool(name, args)
            msgs.append({"role": "tool", "tool_call_id": tc.get("id"),
                         "content": json.dumps(result, ensure_ascii=False)})
    yield ("message", {"content": "(max steps reached)", "tool_calls": None})


def stream_run_with_messages(messages, tool_trace=None):
    cfg = get_config()
    _ctx.images = []
    yield from run_loop_stream(cfg, messages, get_tools(), cfg["max_steps"], tool_trace)


def delegate_task(role, task):
    role_def = SUBAGENTS.get(role)
    if not role_def:
        return {"error": f"Unknown role '{role}'. Available: {', '.join(SUBAGENTS)}"}
    task = str(task or "").strip()
    if not task:
        return {"error": "No task given."}
    cfg = get_config()
    messages = [
        {"role": "system", "content": role_def["prompt"]},
        {"role": "user", "content": task},
    ]
    trace = []
    try:
        report = run_loop(cfg, messages, _tools_for_roles(role_def["allow"]),
                          min(cfg["max_steps"], 6), trace)
    except APIError as e:
        return {"role": role, "error": f"Sub-agent failed: {e}"}
    return {"role": role, "task": task, "report": report, "tools_used": trace}


def run(prompt):
    cfg = get_config()
    messages = [{"role": "system", "content": cfg["system_prompt"]}, {"role": "user", "content": prompt}]
    return run_with_messages(messages)


def main():
    cfg = get_config()
    if not cfg["api_key"]:
        print("No API key. Export AI_AGENT_KEY (or use AI_AGENT_PROVIDER=ollama for local, no key needed).")
        return
    print(f"Agent ready ({cfg['provider']} / {cfg['model']}). Type 'exit' to quit.")
    while True:
        try:
            prompt = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if prompt.strip().lower() in {"exit", "quit"}:
            break
        try:
            print(run(prompt))
        except APIError as e:
            print(f"Error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()