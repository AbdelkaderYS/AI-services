import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import memory
import rag
from agent import call_tool, get_config, APIError


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

os.environ["AI_AGENT_MODEL"] = "qwen/qwen3.6-27b"
check("model override from env", get_config()["model"] == "qwen/qwen3.6-27b")
os.environ.pop("AI_AGENT_MODEL", None)

try:
    raise APIError("boom")
except APIError:
    check("APIError importable", True)

print("\nAll tests passed.")