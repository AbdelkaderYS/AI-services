import json
import os
import re
import time

DATA_DIR = "data"
STORE_PATH = os.path.join(DATA_DIR, "memory.json")
MAX_MEMORIES = 200

WORD_RE = re.compile(r"[a-zA-Z0-9À-ÿ']+", re.UNICODE)

MEMORIES = []


def _tokenize(text):
    return [w for w in WORD_RE.findall(text.lower()) if len(w) > 1]


def _persist():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(MEMORIES, f, ensure_ascii=False)
    except Exception:
        pass


def _load():
    global MEMORIES
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            MEMORIES = json.load(f)
    except FileNotFoundError:
        MEMORIES = []
    except Exception:
        MEMORIES = []


def remember(text):
    text = str(text).strip()
    if not text:
        return {"ok": False, "error": "Nothing to remember."}
    entry = {
        "id": f"{int(time.time() * 1000)}-{len(MEMORIES)}",
        "text": text,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    MEMORIES.append(entry)
    MEMORIES[:] = MEMORIES[-MAX_MEMORIES:]
    _persist()
    return {"ok": True, "id": entry["id"]}


def recall(query="", limit=5):
    if not MEMORIES:
        return []
    query = str(query).strip()
    q_tokens = set(_tokenize(query)) if query else set()
    if not q_tokens:
        return list(reversed(MEMORIES))[:limit]
    scored = []
    for m in MEMORIES:
        overlap = len(q_tokens & set(_tokenize(m["text"])))
        if overlap:
            scored.append((overlap, m))
    if not scored:
        return list(reversed(MEMORIES))[:limit]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:limit]]


def list_memories():
    return list(reversed(MEMORIES))


def forget(memory_id):
    global MEMORIES
    before = len(MEMORIES)
    MEMORIES = [m for m in MEMORIES if m["id"] != memory_id]
    if len(MEMORIES) != before:
        _persist()
        return True
    return False


_load()
