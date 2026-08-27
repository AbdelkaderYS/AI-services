import json
import os
import sys

# Minimal, dependency-free MCP filesystem server for local testing.
# Every operation is confined to MCP_FS_ROOT; paths escaping it are refused.
BASE = os.path.realpath(os.environ.get("MCP_FS_ROOT", "."))
ROOT_DESC = f" All paths are confined to the sandbox directory: {BASE}."


def _safe(path):
    target = os.path.realpath(os.path.join(BASE, path))
    if target != BASE and not target.startswith(BASE + os.sep):
        raise ValueError(f"'{path}' is outside the sandbox '{BASE}'")
    return target


def handle(msg):
    method = msg.get("method")
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mini-fs", "version": "0.1"},
        }
    if method == "tools/list":
        return {"tools": [
            {"name": "server_root", "description": "Return the absolute path of the sandbox directory." + ROOT_DESC,
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
            {"name": "read_file", "description": "Read a file inside the sandbox." + ROOT_DESC,
             "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                             "required": ["path"]}},
            {"name": "write_file", "description": "Write a file inside the sandbox. Returns its absolute path." + ROOT_DESC,
             "inputSchema": {"type": "object",
                             "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                             "required": ["path", "content"]}},
            {"name": "list_directory", "description": "List the sandbox directory." + ROOT_DESC,
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
        ]}
    if method == "tools/call":
        name = msg["params"]["name"]
        a = msg["params"].get("arguments", {})
        try:
            if name == "server_root":
                return {"content": [{"type": "text", "text": f"sandbox root: {BASE}"}]}
            if name == "read_file":
                path = _safe(a["path"])
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                return {"content": [{"type": "text", "text": f"[file: {path}]\n{text}"}]}
            if name == "write_file":
                path = _safe(a["path"])
                with open(path, "w", encoding="utf-8") as f:
                    f.write(a.get("content", ""))
                return {"content": [{"type": "text", "text": f"written: {path}"}]}
            if name == "list_directory":
                return {"content": [{"type": "text",
                                     "text": f"Sandbox root: {BASE}\n" + "\n".join(os.listdir(BASE))}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
        return {"content": [{"type": "text", "text": "unknown tool"}], "isError": True}
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("method") == "notifications/initialized":
            continue
        if "id" not in msg:
            continue
        res = handle(msg)
        if res is None:
            res = {"error": {"code": -32601, "message": "unknown method"}}
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)


if __name__ == "__main__":
    main()
