import json
import os
import time

import requests

import memory
import rag


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
        "You are a helpful assistant with access to tools. "
        "Use web_search for current events or anything that requires the internet. "
        "Use search_documents whenever the question could be about the user's uploaded documents; "
        "answer only from what the tool returns, and say so plainly if nothing relevant is found. "
        "Never invent document content. "
        "Use remember when the user tells you something worth keeping for later (preferences, facts about them). "
        "Use recall_memory when a question might be answered by something saved earlier. "
        "Answer directly when no tool is needed. Be concise."
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


TOOLS = [
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
]


def call_tool(name, args):
    args = args or {}
    try:
        if name == "web_search":
            query = str(args.get("query", ""))
            if not query:
                return {"error": "No query given."}
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                return {"error": "web_search is not installed. Run: pip install duckduckgo-search"}
            with DDGS() as ddgs:
                results = [
                    {"title": r["title"], "body": r["body"]}
                    for r in ddgs.text(query, max_results=3)
                ]
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
    if r.status_code == 401:
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


def run_with_messages(messages, tool_trace=None):
    cfg = get_config()
    msgs = list(messages)
    for _ in range(cfg["max_steps"]):
        msg = chat(cfg, msgs, TOOLS)
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg.get("tool_calls")})
        if not msg.get("tool_calls"):
            return msg.get("content") or "(no output)"
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