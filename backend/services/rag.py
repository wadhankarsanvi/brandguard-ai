"""Retrieval layer of the hybrid RAG pipeline.

Knowledge ingestion: guideline documents are split into heading-aware chunks and stored in SQLite.
Retrieval: a pure-Python TF-IDF vector index (unigrams + bigrams, cosine similarity) that is rebuilt
lazily whenever the chunk table changes.
Optional: fastembed (BAAI/bge-small-en-v1.5) embeddings when EMBEDDINGS=on is set.
"""
import json
import math
import re
import threading
from collections import Counter

from backend import config, db

WORD = re.compile(r"[a-z0-9]+")
STOP = set("""a an the and or but of to in on for with at by from as is are was were be been it its this that these those
you your we our they their i he she his her not no so if then than too very can will just into over about up out
all any more most also have has had do does did""".split())

_embedding_model = None


def get_embedding_model():
    """Lazily load fastembed model (BAAI/bge-small-en-v1.5).
    Falls back gracefully to None if fastembed is not installed or loading fails."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    try:
        from fastembed import TextEmbedding
        _embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        return _embedding_model
    except Exception:
        return None


def compute_embeddings(texts):
    """Compute embeddings using fastembed if available and EMBEDDINGS is on.
    Returns a list of JSON-serialized vectors, or None."""
    if not getattr(config, "EMBEDDINGS", False):
        return None
    model = get_embedding_model()
    if model is None:
        return None
    try:
        res = list(model.embed(texts))
        return [json.dumps(list(e)) for e in res]
    except Exception:
        return None


def _cosine_similarity(vec_a, vec_b):
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, dot / (norm_a * norm_b))


def _stem(w):
    if len(w) > 4:
        for suf in ("ing", "ed", "ly", "es", "s"):
            if w.endswith(suf):
                return w[: -len(suf)]
    return w


def tokens(text):
    ws = [_stem(w) for w in WORD.findall(text.lower()) if w not in STOP]
    return ws + [a + "_" + b for a, b in zip(ws, ws[1:])]


def content_words(text):
    """Unigram stems only; used for claim-coverage checks."""
    return {_stem(w) for w in WORD.findall(text.lower()) if w not in STOP and not w.isdigit()}


def chunk_text(text, max_chars=700):
    """Heading-aware paragraph chunker. Returns [(heading, text)]."""
    chunks, heading, buf = [], "", ""
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            if buf:
                chunks.append((heading, buf.strip()))
                buf = ""
            heading = block.lstrip("#").strip().split("\n")[0]
            rest = "\n".join(block.split("\n")[1:]).strip()
            block = rest
            if not block:
                continue
        if len(buf) + len(block) > max_chars and buf:
            chunks.append((heading, buf.strip()))
            buf = ""
        buf += block + "\n"
    if buf.strip():
        chunks.append((heading, buf.strip()))
    return chunks


def add_document(title, text, doc_type="guideline", filename=None, user_id=None):
    from backend.common import now
    doc_id = db.execute(
        "INSERT INTO documents(title,doc_type,filename,uploaded_by,created_at) VALUES(?,?,?,?,?)",
        (title, doc_type, filename, user_id, now()),
    )
    chunks = chunk_text(text)
    texts_to_embed = [(heading + " " + body).strip() for heading, body in chunks]
    embeddings = compute_embeddings(texts_to_embed)
    for i, (heading, body) in enumerate(chunks):
        emb_json = embeddings[i] if embeddings and i < len(embeddings) else None
        try:
            db.execute("INSERT INTO chunks(document_id,idx,heading,text,embedding) VALUES(?,?,?,?,?)",
                       (doc_id, i, heading, body, emb_json))
        except Exception:
            db.execute("INSERT INTO chunks(document_id,idx,heading,text) VALUES(?,?,?,?)",
                       (doc_id, i, heading, body))
    return doc_id


_lock = threading.Lock()
_cache = {"sig": None, "idx": None}


def _build():
    try:
        rows = db.query("SELECT c.id,c.document_id,c.heading,c.text,c.embedding,d.title FROM chunks c JOIN documents d ON d.id=c.document_id")
    except Exception:
        rows = db.query("SELECT c.id,c.document_id,c.heading,c.text,d.title FROM chunks c JOIN documents d ON d.id=c.document_id")
    df, docs = Counter(), []
    for r in rows:
        tf = Counter(tokens((r["heading"] or "") + " " + r["text"]))
        df.update(tf.keys())
        docs.append((r, tf))
    n = len(docs)
    idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
    vecs = []
    for r, tf in docs:
        v = {t: (1 + math.log(c)) * idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append((r, v, norm))
    return {"idf": idf, "vecs": vecs}


def _index():
    sig = db.query("SELECT COUNT(*) n, COALESCE(MAX(id),0) m FROM chunks", one=True)
    sig = (sig["n"], sig["m"])
    with _lock:
        if _cache["sig"] != sig:
            _cache["idx"], _cache["sig"] = _build(), sig
        return _cache["idx"]


def search(query, k=3):
    idx = _index()
    tf = Counter(tokens(query))
    q = {t: (1 + math.log(c)) * idx["idf"][t] for t, c in tf.items() if t in idx["idf"]}
    qn = math.sqrt(sum(x * x for x in q.values()))

    use_embeddings = getattr(config, "EMBEDDINGS", False)
    q_emb = None
    if use_embeddings:
        model = get_embedding_model()
        if model:
            try:
                emb_res = list(model.embed([query]))
                if emb_res:
                    q_emb = list(emb_res[0])
            except Exception:
                q_emb = None

    if not q and not q_emb:
        return []

    out = []
    for r, v, norm in idx["vecs"]:
        tfidf_score = 0.0
        if q and norm > 0 and qn > 0:
            dot = sum(w * v.get(t, 0.0) for t, w in q.items())
            if dot > 0:
                tfidf_score = dot / (qn * norm)

        cos_score = 0.0
        if q_emb and r.get("embedding"):
            try:
                c_emb = json.loads(r["embedding"])
                cos_score = _cosine_similarity(q_emb, c_emb)
            except Exception:
                cos_score = 0.0

        if q_emb:
            combined = 0.6 * cos_score + 0.4 * tfidf_score
        else:
            combined = tfidf_score

        if combined > 0:
            out.append({
                "chunk_id": r["id"], "document_id": r["document_id"], "doc_title": r["title"],
                "heading": r["heading"], "text": r["text"], "score": round(combined, 4),
            })
    out.sort(key=lambda x: -x["score"])
    return out[:k]
