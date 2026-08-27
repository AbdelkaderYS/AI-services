import io
import math
import os
import re
import zipfile
from collections import Counter

MAX_DOCS = 5
DATA_DIR = "data"
STORE_PATH = os.path.join(DATA_DIR, "documents.json")

TEXT_EXTS = {".txt", ".md", ".markdown", ".json", ".log", ".text", ".py"}

# Formats handled by AnyDoc (Firecrawl) when available. AnyDoc converts them to
# clean GitHub-Flavored Markdown, covering office formats the legacy parsers can't.
ANYDOC_EXTS = {
    ".doc", ".docm", ".docx",
    ".xls", ".xlsx", ".xlsm", ".xlsb",
    ".ppt", ".pptx", ".pps", ".pot", ".pptm", ".ppsx", ".ppsm",
    ".odt", ".ods", ".odp",
    ".rtf", ".epub",
    ".pdf", ".csv",
}

# Legacy hand-rolled parsers, kept as a fallback when AnyDoc is not installed.
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}

STOPWORDS = set(
    """a about above after again all also am an and any are as at be because been before being
    between both but by can could did do does doing down during each few for from further had
    has have having he her here hers herself him himself his how i if in into is it its itself
    just me more most my myself no nor not now of off on once only or other our ours ourselves
    out over own same she should so some such than that the their theirs them themselves then
    there these they this those through to too under until up very was we were what when where
    which while who whom why will with would you your yours yourself yourselves""".split()
)

WORD_RE = re.compile(r"[a-zA-Z0-9À-ÿ']+", re.UNICODE)

DOCS = []
_index = {"chunks": [], "ids": [], "names": [], "terms": [], "dfs": Counter(), "n": 0, "norms": []}


def _safe_name(name):
    return os.path.basename(name.replace("\\", "/")).strip() or "unknown.txt"


def supported_doc():
    return TEXT_EXTS | ANYDOC_EXTS


def tokenize(text):
    words = WORD_RE.findall(text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def parse_docx(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
    except Exception as e:
        return "", f"Could not read .docx: {e}"
    paras = []
    for p in xml.split("</w:p>"):
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S)
        if texts:
            paras.append("".join(texts))
    return "\n".join(paras), None


def parse_pdf(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "PDF needs 'pypdf'. Run: pip install pypdf"
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return text, None
    except Exception as e:
        return None, f"Could not read PDF: {e}"


def parse_anydoc(name, data):
    """Convert a document to Markdown via AnyDoc. Returns (text, error)."""
    try:
        import anydoc
    except ImportError:
        return None, "anydoc is not installed. Run: pip install firecrawl-anydoc"
    try:
        # AnyDoc detects most formats from the bytes, but signature-less formats
        # (e.g. CSV) need an explicit hint resolved from the extension.
        fmt = None
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        try:
            resolved = anydoc.format_from_extension(ext)
            if resolved is not None:
                fmt = resolved
        except Exception:
            fmt = None
        out = anydoc.to_markdown_bytes(data, fmt)
        if isinstance(out, bytes):
            out = out.decode("utf-8", "ignore")
        if not out or not out.strip():
            return None, "AnyDoc produced no text for this file."
        return out, None
    except Exception as e:
        return None, f"AnyDoc could not convert this file: {e}"


def parse_file(name, data):
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in TEXT_EXTS:
        try:
            return data.decode("utf-8"), None
        except UnicodeDecodeError:
            return data.decode("latin-1", "ignore"), None

    # Try AnyDoc first for every office/PDF/CSV format it supports.
    if ext in ANYDOC_EXTS:
        text, err = parse_anydoc(name, data)
        if text:
            return text, None
        # Fall back to the legacy parsers for the two formats they cover.
        if ext in PDF_EXTS:
            text, ferr = parse_pdf(data)
            if text:
                return text, None
            return None, ferr or err
        if ext in DOCX_EXTS:
            text, ferr = parse_docx(data)
            if text:
                return text, None
            return None, ferr or err
        return None, err

    return None, f"Unsupported file type: '{ext or name}'. Use: {', '.join(sorted(supported_doc())[:6])}"


def chunk_text(text, size=1200, overlap=150):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        paras = [line.strip() for line in text.splitlines() if line.strip()]
    if not paras:
        return []

    # A paragraph can itself be bigger than `size` (common with PDFs that
    # extract without blank lines between paragraphs); split those further
    # so a single dense block can't become one giant chunk.
    pieces = []
    for p in paras:
        if len(p) <= size:
            pieces.append(p)
        else:
            start = 0
            while start < len(p):
                pieces.append(p[start:start + size])
                start += size - overlap
    paras = pieces

    chunks, cur, cur_len = [], [], 0
    for p in paras:
        if cur_len + len(p) > size and cur:
            chunks.append("\n\n".join(cur))
            if not overlap:
                cur, cur_len = [], 0
                cur.append(p)
                cur_len = len(p) + 2
                continue
            keep, keep_len = [], 0
            for prev in reversed(cur):
                if keep_len + len(prev) > overlap:
                    break
                keep.insert(0, prev)
                keep_len += len(prev) + 2
            cur, cur_len = keep, keep_len
        cur.append(p)
        cur_len += len(p) + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return [c for c in chunks if len(c.strip()) >= 30]


def rebuild_index():
    chunks, ids, names = [], [], []
    for d in DOCS:
        for c in d["chunks"]:
            chunks.append(c)
            ids.append(d["id"])
            names.append(d["name"])
    terms = [Counter(tokenize(c)) for c in chunks]
    dfs = Counter()
    for t in terms:
        dfs.update(set(t))
    n = len(chunks)
    norms = []
    for t in terms:
        s = 0.0
        for w, c in t.items():
            idf = math.log(1 + n / (1 + dfs[w])) + 1
            s += (c * idf) ** 2
        norms.append(math.sqrt(s) or 1.0)
    _index.update({"chunks": chunks, "ids": ids, "names": names, "terms": terms,
                   "dfs": dfs, "n": n, "norms": norms})


def _persist():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        import json as _json
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            _json.dump([{"id": d["id"], "name": d["name"], "chunks": d["chunks"]} for d in DOCS], f,
                       ensure_ascii=False)
    except Exception:
        pass


def _load():
    global DOCS
    try:
        import json as _json
        with open(STORE_PATH, encoding="utf-8") as f:
            data = _json.load(f)
        DOCS = [{"id": _safe_name(d.get("id", "")), "name": _safe_name(d.get("name", "doc")),
                 "chunks": [str(c) for c in d.get("chunks", [])]} for d in data if d.get("chunks")]
    except FileNotFoundError:
        DOCS = []
    except Exception:
        DOCS = []
    if DOCS:
        rebuild_index()


def add_document(name, data):
    name = _safe_name(name)
    if len(DOCS) >= MAX_DOCS:
        return {"ok": False, "error": f"Max {MAX_DOCS} documents reached. Remove one first."}
    text, err = parse_file(name, data)
    if err:
        return {"ok": False, "error": err}
    if not text or not text.strip():
        return {"ok": False, "error": "The document is empty."}
    chunks = chunk_text(text)
    if not chunks:
        return {"ok": False, "error": "The document has no readable text."}

    for d in list(DOCS):
        if d["name"] == name:
            DOCS.remove(d)
            rebuild_index()

    doc = {"id": f"{len(DOCS)}-{name}", "name": name, "chunks": chunks}
    DOCS.append(doc)
    rebuild_index()
    _persist()
    return {"ok": True, "id": doc["id"], "name": name, "chunks": len(chunks),
            "remaining": MAX_DOCS - len(DOCS)}


def list_documents():
    return [{"id": d["id"], "name": d["name"], "chunks": len(d["chunks"])} for d in DOCS], MAX_DOCS - len(DOCS)


def remove_document(doc_id):
    global DOCS
    before = len(DOCS)
    DOCS = [d for d in DOCS if d["id"] != doc_id]
    if len(DOCS) != before:
        rebuild_index()
        _persist()
        return True
    return False


def retrieve(query, top_k=3):
    if not _index["n"]:
        return []
    q_tok = Counter(tokenize(query))
    if not q_tok:
        return []
    idf = {w: math.log(1 + _index["n"] / (1 + _index["dfs"][w])) + 1 for w in q_tok}
    q_norm = math.sqrt(sum((c * idf[w]) ** 2 for w, c in q_tok.items())) or 1.0
    scored = []
    for i, t in enumerate(_index["terms"]):
        dot = sum(c * (q_tok[w] * idf[w]) for w, c in t.items() if w in q_tok)
        if dot:
            scored.append((dot / (_index["norms"][i] * q_norm), i))
    scored.sort(reverse=True)
    return [{"text": _index["chunks"][i], "name": _index["names"][i], "score": round(s, 3)}
            for s, i in scored[:top_k]]


_load()