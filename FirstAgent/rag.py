import logging
import re
import uuid
from pathlib import Path
from typing import Literal

import httpx
import chromadb

from html_parser import HtmlExtractor

logger = logging.getLogger(__name__)

# ── Stop words for query rewriting ──────────────────────────────────────────
_STOP_WORDS: set[str] = {
    # English
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "not", "only", "own", "same", "so", "than", "too",
    "very", "just", "about", "also", "if", "or", "and", "but", "this",
    "that", "it", "its", "he", "she", "they", "them", "their", "we",
    "you", "i", "me", "my", "your", "our",
    # Русские
    "в", "на", "с", "и", "к", "по", "из", "от", "для", "как", "что",
    "это", "так", "или", "но", "да", "нет", "не", "ни", "бы", "ли",
    "же", "то", "все", "всё", "она", "оно", "они", "мы", "вы", "ты",
    "меня", "мне", "тебя", "тебе", "себя", "себе", "весь", "вся",
    "мой", "твой", "свой", "наш", "ваш", "его", "её", "их", "кто",
    "кого", "кому", "кем", "ком", "чей", "чья", "чьё", "чьи", "где",
    "куда", "откуда", "зачем", "почему", "когда", "какой", "какая",
    "какое", "какие", "который", "которая", "которое", "которые",
    "быть", "есть", "был", "была", "было", "были", "буду", "будет",
    "будут", "чтобы", "если", "хотя", "пока", "после", "до", "без",
    "над", "под", "при", "про", "через", "из-за", "около", "уже",
    "ещё", "еще", "только", "очень", "можно", "надо", "нужно",
    "ко", "во", "со", "об", "обо", "ото", "перед", "между", "ради",
}

OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
RAG_DIR = Path("memory/rag")

ChunkStrategy = Literal["fixed", "structural"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _title_from_source(source: str) -> str:
    return Path(source).stem if source else ""


# ── Strategy 1: Fixed-size chunking ──────────────────────────────────────────

def chunk_fixed(
    text: str,
    source: str = "",
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """Split text into fixed-size character windows with overlap.

    Metadata per chunk: source, title, section (chunk_N), chunk_id, chunk_index, strategy.
    """
    title = _title_from_source(source)
    chunks: list[dict] = []
    start = 0
    idx = 0
    while start < len(text):
        fragment = text[start : start + chunk_size].strip()
        if fragment:
            chunks.append(
                {
                    "text": fragment,
                    "source": source,
                    "title": title,
                    "section": f"chunk_{idx}",
                    "chunk_id": f"fixed_{uuid.uuid4().hex[:8]}",
                    "chunk_index": idx,
                    "strategy": "fixed",
                }
            )
            idx += 1
        start += chunk_size - overlap
    return chunks


# ── Strategy 2: Structural chunking ──────────────────────────────────────────

MIN_STRUCTURAL_CHUNK = 400  # minimum chars per structural chunk; merge smaller neighbours


def _merge_small_chunks(chunks: list[dict]) -> list[dict]:
    """Merge adjacent chunks that are below MIN_STRUCTURAL_CHUNK into the next chunk.

    Merging preserves section name from the FIRST chunk in the merge group
    and joins texts with double-newline.
    """
    if not chunks:
        return chunks
    merged: list[dict] = []
    buf_text = ""
    buf_section = ""
    buf_source = ""
    buf_title = ""
    for c in chunks:
        if buf_text:
            buf_text += "\n\n" + c["text"]
        else:
            buf_text = c["text"]
            buf_section = c["section"]
            buf_source = c["source"]
            buf_title = c["title"]
        if len(buf_text) >= MIN_STRUCTURAL_CHUNK:
            merged.append({
                "text": buf_text,
                "source": buf_source,
                "title": buf_title,
                "section": buf_section,
                "chunk_id": f"struct_{uuid.uuid4().hex[:8]}",
                "chunk_index": len(merged),
                "strategy": "structural",
            })
            buf_text = ""
    if buf_text:
        merged.append({
            "text": buf_text,
            "source": buf_source,
            "title": buf_title,
            "section": buf_section,
            "chunk_id": f"struct_{uuid.uuid4().hex[:8]}",
            "chunk_index": len(merged),
            "strategy": "structural",
        })
    return merged


def chunk_structural(text: str, source: str = "") -> list[dict]:
    """Split text by Markdown headings; fall back to double-newline paragraphs.

    Adjacent sections shorter than MIN_STRUCTURAL_CHUNK are merged so that
    tightly related sentences (e.g. a heading's single-sentence intro and its
    follow-up explanation) stay together in one retrieval chunk.

    Metadata per chunk: source, title, section (heading text or paragraph_N),
    chunk_id, chunk_index, strategy.
    """
    title = _title_from_source(source)
    matches = list(_HEADING_RE.finditer(text))

    if matches:
        raw: list[tuple[str, str]] = []  # (section_label, text_slice)

        preamble = text[: matches[0].start()].strip()
        if preamble:
            raw.append(("preamble", preamble))

        for i, m in enumerate(matches):
            section_label = m.group(2).strip()
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            raw.append((section_label, text[start:end].strip()))

        chunks = []
        for idx, (section_label, fragment) in enumerate(raw):
            if fragment:
                chunks.append(
                    {
                        "text": fragment,
                        "source": source,
                        "title": title,
                        "section": section_label,
                        "chunk_id": f"struct_{uuid.uuid4().hex[:8]}",
                        "chunk_index": idx,
                        "strategy": "structural",
                    }
                )
        return _merge_small_chunks(chunks)

    # Fallback: paragraph splitting
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    raw_chunks = [
        {
            "text": para,
            "source": source,
            "title": title,
            "section": f"paragraph_{i}",
            "chunk_id": f"struct_{uuid.uuid4().hex[:8]}",
            "chunk_index": i,
            "strategy": "structural",
        }
        for i, para in enumerate(paragraphs)
    ]
    return _merge_small_chunks(raw_chunks)


def split_chunks(
    text: str, source: str = "", strategy: ChunkStrategy = "fixed"
) -> list[dict]:
    if strategy == "structural":
        return chunk_structural(text, source)
    return chunk_fixed(text, source)


# ── Strategy comparison ───────────────────────────────────────────────────────

def compare_strategies(text: str, source: str = "") -> dict:
    """Return side-by-side stats for fixed vs structural chunking (no embeddings)."""

    def _stats(chunks: list[dict]) -> dict:
        if not chunks:
            return {"count": 0, "avg_len": 0, "min_len": 0, "max_len": 0, "sections": [], "preview": []}
        lengths = [len(c["text"]) for c in chunks]
        return {
            "count": len(chunks),
            "avg_len": round(sum(lengths) / len(lengths)),
            "min_len": min(lengths),
            "max_len": max(lengths),
            "sections": [c["section"] for c in chunks],
            "preview": [
                {"section": c["section"], "text": c["text"][:150] + ("…" if len(c["text"]) > 150 else "")}
                for c in chunks[:4]
            ],
        }

    fixed = chunk_fixed(text, source)
    structural = chunk_structural(text, source)
    total_chars = len(text)

    return {
        "total_chars": total_chars,
        "fixed": _stats(fixed),
        "structural": _stats(structural),
        "verdict": (
            "structural"
            if (structural and abs(sum(len(c["text"]) for c in structural) / len(structural) - 400) <
                abs(sum(len(c["text"]) for c in fixed) / len(fixed) - 400) if fixed else False)
            else "fixed"
        ),
    }


# ── Embedding ─────────────────────────────────────────────────────────────────

async def _get_embedding(text: str) -> list[float]:
    # Tight timeouts, no retries — health check уже сделан, эмбеддинг должен
    # отрабатывать быстро. Зависание → сразу ConnectionError без перебора IPv4/IPv6.
    transport = httpx.AsyncHTTPTransport(retries=0)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        transport=transport,
    ) as client:
        resp = await client.post(OLLAMA_URL, json={"model": EMBED_MODEL, "prompt": text})
        resp.raise_for_status()
        return resp.json()["embedding"]


# ── RAG Store ─────────────────────────────────────────────────────────────────

class RAGStore:
    def __init__(self, project_path: str = ""):
        RAG_DIR.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(RAG_DIR))
        self._project_path = ""
        self._collection = None
        # Set initial project
        self.set_project(project_path or str(Path.cwd()))

    def _collection_name(self, project_path: str) -> str:
        """Derive a stable collection name from the project path."""
        import hashlib
        h = hashlib.md5(str(project_path).encode()).hexdigest()[:12]
        name = Path(project_path).name
        # Sanitize: keep only alphanumeric, dash, underscore
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        return f"rag_{safe}_{h}"

    def set_project(self, project_path: str) -> None:
        """Switch the active collection to the given project path."""
        name = self._collection_name(project_path)
        old_name = getattr(self._collection, 'name', 'none')
        try:
            self._collection = self._client.get_collection(name)
        except Exception:
            self._collection = self._client.create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        self._project_path = str(project_path)
        logger.info("[RAG] switched collection: %s → %s  chunks=%d  project=%s",
                     old_name, name, self._collection.count(), self._project_path)

    def count(self) -> int:
        """Return number of chunks in the active collection."""
        return self._collection.count() if self._collection else 0

    def delete_project(self, project_path: str) -> int:
        """Delete the ChromaDB collection for a project. Returns chunks deleted."""
        name = self._collection_name(project_path)
        try:
            chunks = self._client.get_collection(name).count()
            self._client.delete_collection(name)
            logger.info("[RAG] deleted collection=%s  chunks=%d", name, chunks)
            # If we deleted the active collection, switch to home
            if self._project_path == str(project_path):
                self.set_project(str(Path.home()))
            return chunks
        except Exception:
            logger.warning("[RAG] collection not found: %s", name)
            return 0

    @property
    def project_path(self) -> str:
        return self._project_path

    async def add_document_stream(
        self, text: str, source: str = "", strategy: ChunkStrategy = "fixed",
        format: str = "auto",
    ):
        """Async generator that yields progress events while embedding each chunk.

        Event shapes:
          {"type": "start",    "doc_id": str, "total": int}
          {"type": "progress", "current": int, "total": int, "section": str}
          {"type": "done",     "doc_id": str, "chunks": int, "source": str, "strategy": str,
                               "detected_format": str, "extracted_title": str | None}
          {"type": "error",    "message": str}
        """
        # ── Preprocess HTML / MHTML ──────────────────────────────────────
        detected_format = "text"
        extracted_title: str | None = None
        if format == "auto":
            detected_format = HtmlExtractor.detect_format(text)
        else:
            detected_format = format

        if detected_format == "mhtml":
            result = HtmlExtractor.from_mhtml(text)
            text = result["clean_text"]
            extracted_title = result.get("title") or None
            if not source and extracted_title:
                source = extracted_title
        elif detected_format == "html":
            result = HtmlExtractor.from_html(text)
            text = result["clean_text"]
            extracted_title = result.get("title") or None
            if not source and extracted_title:
                source = extracted_title

        doc_id = "doc_" + uuid.uuid4().hex[:8]
        chunks = split_chunks(text, source=source, strategy=strategy)

        if not chunks:
            yield {"type": "done", "doc_id": doc_id, "chunks": 0, "source": source,
                   "strategy": strategy, "detected_format": detected_format,
                   "extracted_title": extracted_title}
            return

        yield {"type": "start", "doc_id": doc_id, "total": len(chunks)}

        ids, embeddings, documents, metadatas = [], [], [], []
        try:
            for i, chunk in enumerate(chunks):
                embedding = await _get_embedding(chunk["text"])
                chroma_id = f"{doc_id}_{chunk['chunk_id']}"
                ids.append(chroma_id)
                embeddings.append(embedding)
                documents.append(chunk["text"])
                metadatas.append(
                    {
                        "doc_id": doc_id,
                        "source": source,
                        "title": chunk["title"],
                        "section": chunk["section"],
                        "chunk_id": chunk["chunk_id"],
                        "chunk_index": chunk["chunk_index"],
                        "total_chunks": len(chunks),
                        "strategy": strategy,
                    }
                )
                yield {"type": "progress", "current": i + 1, "total": len(chunks), "section": chunk["section"]}
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}
            return

        self._collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
        logger.info(
            "[RAG] added document %s (%d chunks, source=%r, strategy=%s, format=%s)",
            doc_id, len(chunks), source, strategy, detected_format,
        )
        yield {
            "type": "done", "doc_id": doc_id, "chunks": len(chunks),
            "source": source, "strategy": strategy,
            "detected_format": detected_format,
            "extracted_title": extracted_title,
        }

    async def add_document(
        self, text: str, source: str = "", strategy: ChunkStrategy = "fixed",
        format: str = "auto",
    ) -> dict:
        # ── Preprocess HTML / MHTML ──────────────────────────────────────
        detected_format = "text"
        extracted_title: str | None = None
        if format == "auto":
            detected_format = HtmlExtractor.detect_format(text)
        else:
            detected_format = format

        if detected_format == "mhtml":
            result = HtmlExtractor.from_mhtml(text)
            text = result["clean_text"]
            extracted_title = result.get("title") or None
            if not source and extracted_title:
                source = extracted_title
        elif detected_format == "html":
            result = HtmlExtractor.from_html(text)
            text = result["clean_text"]
            extracted_title = result.get("title") or None
            if not source and extracted_title:
                source = extracted_title

        doc_id = "doc_" + uuid.uuid4().hex[:8]
        chunks = split_chunks(text, source=source, strategy=strategy)
        if not chunks:
            return {"doc_id": doc_id, "chunks": 0, "source": source, "strategy": strategy,
                    "detected_format": detected_format, "extracted_title": extracted_title}

        ids, embeddings, documents, metadatas = [], [], [], []
        for chunk in chunks:
            embedding = await _get_embedding(chunk["text"])
            chroma_id = f"{doc_id}_{chunk['chunk_id']}"
            ids.append(chroma_id)
            embeddings.append(embedding)
            documents.append(chunk["text"])
            metadatas.append(
                {
                    "doc_id": doc_id,
                    "source": source,
                    "title": chunk["title"],
                    "section": chunk["section"],
                    "chunk_id": chunk["chunk_id"],
                    "chunk_index": chunk["chunk_index"],
                    "total_chunks": len(chunks),
                    "strategy": strategy,
                }
            )

        self._collection.add(
            ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
        )
        logger.info(
            "[RAG] added document %s (%d chunks, source=%r, strategy=%s, format=%s)",
            doc_id, len(chunks), source, strategy, detected_format,
        )
        return {"doc_id": doc_id, "chunks": len(chunks), "source": source,
                "strategy": strategy, "detected_format": detected_format,
                "extracted_title": extracted_title}

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        col_name = getattr(self._collection, 'name', '?')
        total = self._collection.count()
        logger.info("[RAG] retrieve collection=%s  chunks=%d  query=%.80s", col_name, total, query)
        if total == 0:
            return []
        embedding = await _get_embedding(query)
        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, total),
            include=["documents", "metadatas", "distances"],
        )
        items = []
        if results["ids"] and results["ids"][0]:
            for doc, meta, dist in zip(
                results["documents"][0], results["metadatas"][0], results["distances"][0]
            ):
                items.append(
                    {
                        "text": doc,
                        "source": meta.get("source", ""),
                        "title": meta.get("title", ""),
                        "section": meta.get("section", ""),
                        "chunk_id": meta.get("chunk_id", ""),
                        "doc_id": meta.get("doc_id", ""),
                        "strategy": meta.get("strategy", "fixed"),
                        "score": round(1 - dist, 4),
                    }
                )
        return items

    def retrieve_by_keywords(self, terms: list[str], top_k: int = 10) -> list[dict]:
        """Return chunks whose text contains at least one of *terms* (case-insensitive).

        Used as a supplement to semantic search for named entities that the
        embedding model fails to connect.  Scored at 0.85 (above mid-range but
        below high-confidence semantic matches).
        """
        if not terms or self._collection.count() == 0:
            return []
        found: list[dict] = []
        for term in terms:
            # ChromaDB $contains is case-sensitive — try original and lowered
            candidates = {term, term.lower(), term.capitalize()}
            for variant in candidates:
                try:
                    results = self._collection.get(
                        where_document={"$contains": variant},
                        include=["documents", "metadatas"],
                    )
                except Exception:
                    continue
                if results["ids"]:
                    for doc, meta in zip(results["documents"], results["metadatas"]):
                        fid = meta.get("chunk_id", "")
                        if any(f["chunk_id"] == fid for f in found):
                            continue  # dedup
                        found.append({
                            "text": doc,
                            "source": meta.get("source", ""),
                            "title": meta.get("title", ""),
                            "section": meta.get("section", ""),
                            "chunk_id": fid,
                            "chunk_index": meta.get("chunk_index", 0),
                            "doc_id": meta.get("doc_id", ""),
                            "strategy": meta.get("strategy", "fixed"),
                            "score": 0.97,  # high score so keyword results survive pre_k filtering
                            "_keyword_match": True,
                        })
        return found[:top_k]

    def get_chunk_by_doc_index(self, doc_id: str, chunk_index: int) -> dict | None:
        """Return a single chunk by doc_id + chunk_index, or None."""
        try:
            results = self._collection.get(
                where={"$and": [
                    {"doc_id": doc_id},
                    {"chunk_index": chunk_index},
                ]},
                include=["documents", "metadatas"],
            )
        except Exception:
            return None
        if results["ids"]:
            meta = results["metadatas"][0]
            return {
                "text": results["documents"][0],
                "source": meta.get("source", ""),
                "title": meta.get("title", ""),
                "section": meta.get("section", ""),
                "chunk_id": meta.get("chunk_id", ""),
                "doc_id": meta.get("doc_id", ""),
                "chunk_index": meta.get("chunk_index", 0),
                "strategy": meta.get("strategy", "fixed"),
                "score": 0.92,  # neighbor score (base, overridden in agent)
            }
        return None

    def list_documents(self) -> list[dict]:
        if self._collection.count() == 0:
            return []
        results = self._collection.get(include=["metadatas"])
        seen: dict[str, dict] = {}
        for meta in results["metadatas"]:
            doc_id = meta["doc_id"]
            if doc_id not in seen:
                seen[doc_id] = {
                    "doc_id": doc_id,
                    "source": meta.get("source", ""),
                    "title": meta.get("title", ""),
                    "chunks": meta["total_chunks"],
                    "strategy": meta.get("strategy", "fixed"),
                }
        return list(seen.values())

    def delete_document(self, doc_id: str) -> bool:
        results = self._collection.get(where={"doc_id": doc_id})
        if not results["ids"]:
            return False
        self._collection.delete(ids=results["ids"])
        logger.info("[RAG] deleted document %s (%d chunks)", doc_id, len(results["ids"]))
        return True

    def build_context_block(self, results: list[dict]) -> str:
        if not results:
            return ""
        lines = ["[RAG CONTEXT — relevant documents retrieved by semantic search]"]
        for i, r in enumerate(results, 1):
            parts = []
            if r.get("source"):
                parts.append(f"source: {r['source']}")
            if r.get("title"):
                parts.append(r["title"])
            if r.get("section"):
                parts.append(f"section: {r['section']}")
            if r.get("chunk_id"):
                parts.append(f"chunk_id: {r['chunk_id']}")
            label = f" [{' / '.join(parts)}]" if parts else ""
            lines.append(f"({i}){label} (score: {r.get('score', 0):.3f})\n{r['text']}")
        return "\n".join(lines)

    @staticmethod
    def build_rag_output_instructions() -> str:
        return (
            "[RAG OUTPUT FORMAT — MANDATORY]\n"
            "You MUST structure your response as follows:\n\n"
            "1. ANSWER: Provide a direct answer to the user's question based on the retrieved context.\n\n"
            "2. SOURCES: List every source you used, in format:\n"
            "   - source (section: name, chunk_id: id)\n\n"
            "3. QUOTES: For each claim, include a relevant quote from the retrieved chunks.\n"
            "   Format quotes as: «...quoted text from chunk...»\n\n"
            "If the retrieved context does NOT contain enough information to answer the question, "
            'you MUST respond with "Я не знаю ответа на этот вопрос. В найденных документах недостаточно информации. '
            'Пожалуйста, уточните вопрос или предоставьте дополнительные материалы." '
            "and ask a clarifying question."
        )

    @staticmethod
    def build_no_context_instructions() -> str:
        return (
            "[RAG — No relevant context found]\n"
            "Semantic search did not find documents relevant enough to answer the user's question. "
            "The relevance scores of all retrieved chunks were below the required threshold.\n\n"
            "You MUST respond with:\n"
            '"Я не знаю ответа на этот вопрос. В найденных документах недостаточно релевантной информации. '
            'Пожалуйста, уточните вопрос или предоставьте дополнительные материалы."\n'
            "Then ask 1-2 clarifying questions that would help find the answer."
        )


# ── Query Rewriting ─────────────────────────────────────────────────────────

def rewrite_query_keywords(query: str) -> str:
    """Extract key terms from query, dropping stop words and short tokens."""
    tokens = re.findall(r"[a-zA-Zа-яёА-ЯЁ0-9_]{2,}", query.lower())
    keywords = [t for t in tokens if t not in _STOP_WORDS]
    return " ".join(keywords) if keywords else query


def rewrite_query_expand(query: str) -> str:
    """Generate an expanded query by duplicating key noun phrases."""
    keywords = rewrite_query_keywords(query)
    if not keywords:
        return query
    parts = keywords.split()
    if len(parts) <= 3:
        return f"{query} {keywords}"
    return f"{query} {' '.join(parts[: max(3, len(parts) // 2)])}"


RewriteStrategy = Literal["none", "keywords", "expand"]


def rewrite_query(query: str, strategy: RewriteStrategy = "keywords") -> str:
    if strategy == "keywords":
        return rewrite_query_keywords(query)
    elif strategy == "expand":
        return rewrite_query_expand(query)
    return query


# ── Reranker ────────────────────────────────────────────────────────────────

def apply_score_threshold(
    results: list[dict],
    threshold: float = 0.3,
    post_k: int = 5,
) -> list[dict]:
    """Filter chunks by minimum similarity score, then take top post_k."""
    filtered = [r for r in results if r["score"] >= threshold]
    filtered.sort(key=lambda r: r["score"], reverse=True)
    return filtered[:post_k]


def apply_mmr(
    results: list[dict],
    post_k: int = 5,
    lambda_param: float = 0.7,
) -> list[dict]:
    """Maximum Marginal Relevance — balance relevance with diversity.

    lambda_param: 1.0 = pure relevance, 0.0 = pure diversity.
    Default 0.7 favours relevance while penalising near-duplicate chunks.
    """
    if len(results) <= post_k:
        return list(results)

    # Build a crude token-overlap similarity matrix (Jaccard-based)
    def tokenize(text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Zа-яёА-ЯЁ0-9_]{2,}", text.lower()))

    token_sets = [tokenize(r["text"]) for r in results]

    def jaccard(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    selected: list[int] = []
    remaining = list(range(len(results)))

    # First pick: highest score
    best = max(remaining, key=lambda i: results[i]["score"])
    selected.append(best)
    remaining.remove(best)

    while remaining and len(selected) < post_k:
        scores = []
        for i in remaining:
            relevance = results[i]["score"]
            diversity = max(jaccard(token_sets[i], token_sets[s]) for s in selected) if selected else 0.0
            mmr = lambda_param * relevance - (1 - lambda_param) * diversity
            scores.append(mmr)
        best = remaining[max(range(len(scores)), key=lambda j: scores[j])]
        selected.append(best)
        remaining.remove(best)

    return [results[i] for i in selected]


def _boost_keyword_match(results: list[dict], query: str, boost_strength: float = 0.18) -> list[dict]:
    """Add a small score bonus for chunks that share keywords with the query.

    This is a lightweight hybrid-retrieval fix: the embedding model may rank
    semantically related paragraphs above the literal answer if the answer
    uses different wording.  Keyword overlap gives the literal match a slight
    nudge so it isn't buried.
    """
    if not query or not results:
        return results
    query_tokens = set(re.findall(r"[a-zA-Zа-яёА-ЯЁ0-9_]{3,}", query.lower()))
    query_keywords = {t for t in query_tokens if t not in _STOP_WORDS}
    if not query_keywords:
        return results

    boosted: list[dict] = []
    for r in results:
        chunk_tokens = set(re.findall(r"[a-zA-Zа-яёА-ЯЁ0-9_]{3,}", r["text"].lower()))
        overlap = len(query_keywords & chunk_tokens) / len(query_keywords)
        bonus = overlap * boost_strength
        r_copy = dict(r)
        r_copy["score"] = round(min(r["score"] + bonus, 1.0), 4)
        boosted.append(r_copy)
    # Re-sort by boosted score
    boosted.sort(key=lambda r: r["score"], reverse=True)
    return boosted


def rerank_results(
    results: list[dict],
    pre_k: int = 10,
    post_k: int = 5,
    threshold: float = 0.0,
    use_mmr: bool = True,
    mmr_lambda: float = 0.7,
    query: str = "",
) -> dict:
    """Full reranking pipeline.

    Args:
        results: raw retrieval results (sorted by score descending)
        pre_k: take this many before reranking
        post_k: return this many after reranking
        threshold: minimum similarity score (0-1). Chunks below are discarded.
        use_mmr: apply MMR diversity reranking after threshold filtering
        mmr_lambda: relevance vs diversity weight (1.0 = pure relevance)
        query: original query for keyword-boost (hybrid retrieval nudge)

    Returns:
        dict with 'results', 'before_count', 'after_count', 'threshold', 'pre_k', 'post_k'
    """
    before_count = len(results)

    # Step 0: keyword-boost scores so literal matches aren't buried
    candidates = _boost_keyword_match(results, query)

    # Step 1: limit to pre_k
    candidates = candidates[:pre_k]

    # Step 2: filter by threshold
    if threshold > 0:
        candidates = [r for r in candidates if r["score"] >= threshold]

    filtered_count = len(candidates)

    # Step 3: MMR diversity reranking (or pure score sort)
    if use_mmr and len(candidates) > 1:
        candidates = apply_mmr(candidates, post_k=post_k, lambda_param=mmr_lambda)
    else:
        candidates.sort(key=lambda r: r["score"], reverse=True)
        candidates = candidates[:post_k]

    return {
        "results": candidates,
        "before_count": before_count,
        "after_count": len(candidates),
        "threshold": threshold,
        "pre_k": pre_k,
        "post_k": post_k,
    }


# ── RAG Retriever (orchestrates retrieval + rerank + rewrite) ───────────────

class RAGRetriever:
    """Orchestrates the full retrieval pipeline: query rewrite → search → rerank."""

    def __init__(self, store: "RAGStore"):
        self.store = store

    async def retrieve(
        self,
        query: str,
        pre_k: int = 10,
        post_k: int = 5,
        threshold: float = 0.0,
        rewrite: RewriteStrategy = "none",
        use_mmr: bool = True,
        mmr_lambda: float = 0.7,
    ) -> dict:
        """Run the full pipeline and return results + metadata about each stage.

        Returns:
            {
                "query_original": str,
                "query_rewritten": str or None,
                "rewrite_strategy": str,
                "results": [...],
                "before_rerank": int,
                "after_rerank": int,
                "threshold": float,
                "pre_k": int,
                "post_k": int,
            }
        """
        # Stage 1: Query rewrite
        rewritten = None
        search_query = query
        if rewrite != "none":
            rewritten = rewrite_query(query, strategy=rewrite)
            search_query = rewritten

        # Stage 2: Semantic search with pre_k
        raw_results = await self.store.retrieve(search_query, top_k=pre_k)

        # Stage 3: Rerank
        rerank = rerank_results(
            raw_results,
            pre_k=pre_k,
            post_k=post_k,
            threshold=threshold,
            use_mmr=use_mmr,
            mmr_lambda=mmr_lambda,
            query=query,
        )

        return {
            "query_original": query,
            "query_rewritten": rewritten,
            "rewrite_strategy": rewrite,
            "results": rerank["results"],
            "before_rerank": rerank["before_count"],
            "after_rerank": rerank["after_count"],
            "threshold": threshold,
            "pre_k": pre_k,
            "post_k": post_k,
        }