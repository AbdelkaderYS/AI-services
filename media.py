import base64
import binascii
import hashlib
import threading

MAX_IMAGES = 30
MAX_B64_LEN = 1_000_000  # ~750 KB per image once decoded

MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}

_lock = threading.Lock()
_store = {}  # token -> (bytes, mime)
_order = []


def mime_for(name):
    dot = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return MIME_BY_EXT.get(dot, "application/octet-stream")


def store_b64(name, b64):
    """Register a base64-encoded image; returns its token or None if rejected."""
    b64 = str(b64 or "").strip()
    if not b64 or len(b64) > MAX_B64_LEN:
        return None
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    return store_bytes(name, data)


def store_bytes(name, data):
    if not data:
        return None
    digest = hashlib.md5(data).hexdigest()[:12]
    token = f"IMG:{digest}"
    with _lock:
        if token in _order:
            _order.remove(token)
        _store[token] = (data, mime_for(name))
        _order.append(token)
        while len(_order) > MAX_IMAGES:
            old = _order.pop(0)
            _store.pop(old, None)
    return f"[[{token}]]"


def get(token):
    token = token.strip("[]")
    with _lock:
        hit = _store.get(token)
    return (hit[0], hit[1]) if hit else (None, None)


def clear():
    with _lock:
        _store.clear()
        _order.clear()
