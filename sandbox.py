import math
import os
import subprocess
import sys
import tempfile
import time

import media

DEFAULT_TIMEOUT = 15.0
MAX_TIMEOUT = 60.0
MAX_OUTPUT = 6000
MEM_LIMIT_BYTES = 512 * 1024 * 1024
MAX_IMAGES = 4
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

# The user's code never runs in this process: a throwaway interpreter is
# spawned in isolated mode (-I: no user site, env vars ignored, cwd off sys.path)
# and executes the code through a wrapper that applies resource limits first.
WRAPPER = """
import sys
try:
    import resource
    cpu = {cpu}
    mem = {mem}
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
except Exception:
    pass
with open(sys.argv[1], encoding="utf-8") as f:
    src = f.read()
exec(compile(src, sys.argv[1], "exec"), {{"__name__": "__main__"}})
"""


def _truncate(text):
    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT] + f"\n... [truncated, {len(text)} chars total]"
    return text


def _minimal_env(workdir):
    env = {}
    for key in ("PATH", "SystemRoot", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "LANG"):
        if key in os.environ:
            env[key] = os.environ[key]
    env["PYTHONIOENCODING"] = "utf-8"
    env["MPLBACKEND"] = "Agg"
    env["HOME"] = workdir
    return env


def _collect_images(workdir):
    """Register image files the code wrote (charts...); returns their tokens."""
    found = []
    for root, _, files in os.walk(workdir):
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in IMAGE_EXTS:
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            token = media.store_bytes(fname, data)
            if token:
                found.append(token)
            if len(found) >= MAX_IMAGES:
                return found
    return found


def run_python(code, timeout=None):
    code = str(code or "")
    if not code.strip():
        return {"error": "No code provided."}
    try:
        timeout = float(timeout) if timeout is not None else DEFAULT_TIMEOUT
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    timeout = max(1.0, min(timeout, MAX_TIMEOUT))

    workdir = tempfile.mkdtemp(prefix="ai-sandbox-")
    code_path = os.path.join(workdir, "main.py")
    with open(code_path, "w", encoding="utf-8") as f:
        f.write(code)

    wrapper_path = os.path.join(workdir, "_wrapper.py")
    with open(wrapper_path, "w", encoding="utf-8") as f:
        f.write(WRAPPER.format(cpu=max(1, math.ceil(timeout)) + 1, mem=MEM_LIMIT_BYTES))

    cmd = [sys.executable, "-I", wrapper_path, code_path]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=workdir,
            env=_minimal_env(workdir),
        )
    except subprocess.TimeoutExpired as e:
        return {
            "timed_out": True,
            "error": f"Timed out after {timeout:.0f}s and was killed.",
            "stdout": _truncate(e.stdout or "") if isinstance(e.stdout, str) else "",
            "stderr": _truncate(e.stderr or "") if isinstance(e.stderr, str) else "",
        }
    except OSError as e:
        return {"error": f"Could not start sandbox: {e}"}

    result = {
        "exit_code": proc.returncode,
        "stdout": _truncate(proc.stdout or ""),
        "stderr": _truncate(proc.stderr or ""),
        "duration_s": round(time.time() - started, 2),
    }
    if proc.returncode != 0 and not proc.stderr:
        result["stderr"] = f"Process exited with code {proc.returncode}."
    if "ModuleNotFoundError" in result.get("stderr", ""):
        result["hint"] = ("A package is missing in the server's Python environment. "
                          "Install it with: python3 -m pip install <package>")
    images = _collect_images(workdir)
    if images:
        result["images"] = images
    return result


if __name__ == "__main__":
    print(run_python("print(sum(range(101)))"))
