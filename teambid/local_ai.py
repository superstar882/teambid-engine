"""Free local AI through Ollama (https://ollama.com), used only when it is running. Everything still works without it.

- Embeddings (default nomic-embed-text): meaning-based similarity. Used to rank resume bullets against a job post and
  to add a "meaning match" to job scores. Safe by design: embeddings never write text.
- Chat (default qwen3:4b-instruct): optional wording polish for cover letters. Small local models change facts (tested:
  it turned "migration of our data pipelines" into "teamwork"), so every output goes through llm.guard() and is
  rejected if it adds numbers, tools or claims that are not in the resume.

Settings: OLLAMA_URL (default http://127.0.0.1:11434), TEAMBID_EMBED_MODEL, TEAMBID_LOCAL_MODEL, TEAMBID_LOCAL_AI=off to disable.
"""
import hashlib
import json
import math
import os
import sqlite3
import threading
import time

import requests

from . import config

URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = os.environ.get("TEAMBID_EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL = os.environ.get("TEAMBID_LOCAL_MODEL", "qwen3:4b-instruct")
DISABLED = os.environ.get("TEAMBID_LOCAL_AI", "").lower() in ("off", "0", "false", "no")
_status = {"t": 0, "models": None}
_lock = threading.Lock()


def models():
    """Installed Ollama models (cached 60 s); [] if Ollama isn't running."""
    if DISABLED:
        return []
    with _lock:
        if time.time() - _status["t"] < 60 and _status["models"] is not None:
            return _status["models"]
        try:
            r = requests.get(f"{URL}/api/tags", timeout=2)
            names = [m["name"] for m in r.json().get("models", [])] if r.ok else []
        except (requests.RequestException, ValueError):
            names = []
        _status.update(t=time.time(), models=names)
        return names


def _has(model):
    base = model.split(":")[0]
    return any(m == model or m.split(":")[0] == base for m in models())


def embed_available():
    return _has(EMBED_MODEL)


def chat_available():
    return _has(CHAT_MODEL)


def status():
    return {"running": bool(models()), "embed": embed_available(), "chat": chat_available(),
            "embed_model": EMBED_MODEL, "chat_model": CHAT_MODEL, "url": URL}


# ---------------------------------------------------------------- embeddings (with a disk cache)
def _cache():
    config.CACHE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.CACHE / "embeddings.sqlite", timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS e (k TEXT PRIMARY KEY, v TEXT)")
    return con


def embed(texts, kind="document"):
    """List of vectors (or None if embeddings are unavailable). kind: 'query' (a job post) or 'document' (bullets).
    nomic-embed-text expects task prefixes; other models get the plain text."""
    if not texts or not embed_available():
        return None
    prefix = {"query": "search_query: ", "document": "search_document: "}[kind] if "nomic" in EMBED_MODEL else ""
    items = [prefix + (t or "")[:2000] for t in texts]
    keys = [hashlib.sha1(f"{EMBED_MODEL}|{x}".encode("utf-8")).hexdigest() for x in items]
    con = _cache()
    try:
        have = {k: json.loads(v) for k, v in con.execute(
            f"SELECT k, v FROM e WHERE k IN ({','.join('?' * len(keys))})", keys)}
        missing = [(k, x) for k, x in zip(keys, items) if k not in have]
        for i in range(0, len(missing), 32):
            chunk = missing[i:i + 32]
            r = requests.post(f"{URL}/api/embed", json={"model": EMBED_MODEL, "input": [x for _, x in chunk]}, timeout=120)
            r.raise_for_status()
            for (k, _), vec in zip(chunk, r.json()["embeddings"]):
                have[k] = vec
                con.execute("INSERT OR REPLACE INTO e VALUES (?, ?)", (k, json.dumps(vec)))
        con.commit()
        return [have[k] for k in keys]
    except (requests.RequestException, ValueError, KeyError):
        return None
    finally:
        con.close()


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def similarities(query, docs):
    """Cosine similarity of each doc to the query, or None if embeddings are unavailable."""
    q = embed([query], "query")
    d = embed(docs, "document")
    if not q or d is None:
        return None
    return [cosine(q[0], v) for v in d]


# ---------------------------------------------------------------- chat
def chat(system, user, max_tokens=700, temperature=0.3):
    """One reply from the local chat model (thinking disabled), or raises RuntimeError."""
    if not chat_available():
        raise RuntimeError(f"Local model {CHAT_MODEL} isn't available in Ollama")
    body = {"model": CHAT_MODEL, "stream": False, "think": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"num_predict": max_tokens, "temperature": temperature, "num_ctx": 8192}}
    try:
        r = requests.post(f"{URL}/api/chat", json=body, timeout=600)
        if r.status_code == 400 and "think" in r.text:          # older Ollama without the think flag
            body.pop("think")
            r = requests.post(f"{URL}/api/chat", json=body, timeout=600)
        r.raise_for_status()
        text = r.json()["message"]["content"]
    except (requests.RequestException, ValueError, KeyError) as e:
        raise RuntimeError(f"Ollama error: {e}") from e
    import re
    return re.sub(r"(?s)<think>.*?</think>", "", text).strip()
