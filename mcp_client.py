import json
import os
import queue
import re
import subprocess
import threading
import time

CONFIG_PATH = os.path.join("data", "mcp.json")
HANDSHAKE_TIMEOUT = 15
DEFAULT_CALL_TIMEOUT = 30
MAX_TOOL_NAME_LEN = 64

_lock = threading.Lock()
_servers = {}
_tool_map = {}
_status = {}
_configured = False


class MCPError(Exception):
    pass


def _sanitize(name):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(name))[:40] or "tool"


def _resolve_sandbox(sandbox):
    """Resolve a sandbox path to an absolute, canonical directory, or None."""
    if not sandbox:
        return None
    path = os.path.realpath(os.path.abspath(str(sandbox)))
    return path if os.path.isdir(path) else None


def _is_write_tool(name):
    n = str(name).lower()
    return any(h in n for h in WRITE_HINTS)


def _check_sandbox(srv, args):
    """Return an error string if any path argument escapes the sandbox, else None."""
    if not srv.sandbox or not isinstance(args, dict):
        return None
    for key, val in args.items():
        if key not in PATH_KEYS:
            continue
        for v in (val if isinstance(val, list) else [val]):
            if not isinstance(v, str) or not v.strip():
                continue
            raw = v.strip()
            # Relative paths resolve against the sandbox root, not the cwd.
            candidate = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(srv.sandbox, raw))
            if candidate != srv.sandbox and not candidate.startswith(srv.sandbox + os.sep):
                return (f"Refusing '{raw}': outside the sandbox '{srv.sandbox}'. "
                        f"Filesystem access is confined to that directory.")
    return None


# Tool names (or substrings) that mutate state. Used for the read-only guardrail.
WRITE_HINTS = ("write", "create", "delete", "remove", "move", "rename", "edit", "mkdir", "rmdir", "append")
# Argument keys whose values are file paths we must keep inside the sandbox.
PATH_KEYS = ("path", "source", "destination", "uri", "file_path", "dir_path", "target")


class MCPServer:
    def __init__(self, name, command, args=None, env=None, call_timeout=None,
                 read_only=False, sandbox=None):
        self.name = name
        self.command = str(command)
        self.args = [str(a) for a in (args or [])]
        self.env = {str(k): str(v) for k, v in (env or {}).items()}
        self.call_timeout = float(call_timeout) if call_timeout else DEFAULT_CALL_TIMEOUT
        # Guardrails: read-only blocks write tools; sandbox confines path args.
        self.read_only = bool(read_only)
        self.sandbox = _resolve_sandbox(sandbox)
        self.proc = None
        self.queue = None
        self._id = 0

    def _send(self, payload):
        line = json.dumps(payload, ensure_ascii=False)
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            raise MCPError(f"'{self.name}' pipe broken: {e}")

    def _reader(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.queue.put(msg)
        self.queue.put(None)

    def _request(self, method, params, timeout):
        if self.proc is None or self.proc.poll() is not None:
            raise MCPError(f"Server '{self.name}' is not running.")
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise MCPError(f"Timeout ({timeout:.0f}s) waiting for '{method}' from '{self.name}'.")
            msg = self.queue.get(timeout=remaining)
            if msg is None:
                raise MCPError(f"Server '{self.name}' exited unexpectedly.")
            if msg.get("id") == rid:
                if "error" in msg:
                    err = msg["error"]
                    raise MCPError(f"{method} failed: {err.get('message', err)}")
                return msg.get("result", {})

    def _notify(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def start(self):
        env = dict(os.environ)
        env.update(self.env)
        self.proc = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        self.queue = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        result = self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ai-services", "version": "1.0"},
            },
            HANDSHAKE_TIMEOUT,
        )
        info = result.get("serverInfo", {})
        self._notify("notifications/initialized")
        return info.get("name") or self.command

    def list_tools(self):
        return self._request("tools/list", {}, HANDSHAKE_TIMEOUT).get("tools", [])

    def call(self, tool, arguments, timeout=None):
        result = self._request("tools/call", {"name": tool, "arguments": arguments},
                               timeout or self.call_timeout)
        parts = []
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        text = "\n".join(p for p in parts if p)
        if result.get("isError"):
            return {"error": text or "Tool reported an error."}
        out = {"content": text}
        if "structuredContent" in result:
            out["structured"] = result["structuredContent"]
        return out

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None


def _register_server(name, cfg):
    entry = {"name": name, "ok": False, "error": "", "server": "", "tools": []}
    _status[name] = entry
    srv = MCPServer(name, cfg.get("command"), cfg.get("args"), cfg.get("env"),
                     cfg.get("call_timeout"), cfg.get("read_only"), cfg.get("sandbox"))
    try:
        entry["server"] = srv.start()
        tools = srv.list_tools()
    except Exception as e:
        entry["error"] = str(e)
        srv.stop()
        return
    entry["ok"] = True
    _servers[name] = srv
    for t in tools:
        orig = t.get("name")
        if not orig:
            continue
        openai_name = f"mcp_{_sanitize(name)}_{_sanitize(orig)}"[:MAX_TOOL_NAME_LEN]
        while openai_name in _tool_map:
            openai_name = openai_name[: MAX_TOOL_NAME_LEN - 2] + "_x"
        _tool_map[openai_name] = (srv, orig)
        spec = {
            "type": "function",
            "function": {
                "name": openai_name,
                "description": (t.get("description") or f"MCP tool '{orig}' from server '{name}'").strip(),
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
            },
        }
        entry["tools"].append(openai_name)
        TOOL_SPECS.append(spec)


TOOL_SPECS = []


def configure(config):
    """Connect to every server in `config`.

    Accepts either {"servers": {name: {...}}} or a flat {name: {...}} map.
    Replaces any previous configuration; a failing server never raises.
    """
    global _configured
    shutdown()
    TOOL_SPECS.clear()
    _tool_map.clear()
    _status.clear()
    if not isinstance(config, dict):
        servers = {}
    elif "servers" in config and isinstance(config["servers"], dict):
        servers = config["servers"]
    else:
        servers = config
    for name, cfg in servers.items():
        if not isinstance(cfg, dict) or not cfg.get("command"):
            continue
        _register_server(str(name), cfg)
    _configured = True


def ensure_configured():
    global _configured
    with _lock:
        if _configured:
            return
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                configure(json.load(f))
        except FileNotFoundError:
            _configured = True
        except Exception as e:
            _status["_config"] = {"name": "config", "ok": False, "error": str(e),
                                  "server": "", "tools": []}
            _configured = True


def tool_specs():
    ensure_configured()
    return list(TOOL_SPECS)


def route_call(openai_name, args):
    ensure_configured()
    hit = _tool_map.get(openai_name)
    if not hit:
        return {"error": f"unknown MCP tool: {openai_name}"}
    srv, orig = hit
    # Guardrail 1: read-only servers cannot perform mutating operations.
    if srv.read_only and _is_write_tool(orig):
        return {"error": (
            f"Write tool '{orig}' blocked: server '{srv.name}' is read-only. "
            f"Enable writes in data/mcp.json with \"read_only\": false (and set a \"sandbox\")."
        )}
    # Guardrail 2: keep every path argument inside the configured sandbox.
    sandbox_err = _check_sandbox(srv, args)
    if sandbox_err:
        return {"error": sandbox_err}
    try:
        return srv.call(orig, args or {})
    except MCPError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"{srv.name}/{orig} failed: {e}"}


def status():
    ensure_configured()
    return [{"name": e["name"], "ok": e["ok"], "error": e["error"],
             "tools": list(e["tools"]), "server_name": e.get("server", "")}
            for e in _status.values()]


def shutdown():
    for srv in _servers.values():
        srv.stop()
    _servers.clear()
    for entry in _status.values():
        if entry["ok"]:
            entry["ok"] = False
            entry["error"] = "Stopped."


def reset():
    global _configured
    with _lock:
        shutdown()
        TOOL_SPECS.clear()
        _tool_map.clear()
        _status.clear()
        _configured = False
