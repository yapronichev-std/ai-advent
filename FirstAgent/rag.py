import logging
import re
import uuid
from pathlib import Path
from typing import Literal

import httpx
import chromadb

logger = logging.getLogger(__name__)

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

def chunk_structural(text: str, source: str = "") -> list[dict]:
    """Split text by Markdown headings; fall back to double-newline paragraphs.

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
        return chunks

    # Fallback: paragraph splitting
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return [
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
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(OLLAMA_URL, json={"model": EMBED_MODEL, "prompt": text})
        resp.raise_for_status()
        return resp.json()["embedding"]


# ── RAG Store ─────────────────────────────────────────────────────────────────

class RAGStore:
    def __init__(self):
        RAG_DIR.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(RAG_DIR))
        self._collection = self._client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("[RAG] initialized, %d chunks in collection", self._collection.count())

    async def add_document_stream(
        self, text: str, source: str = "", strategy: ChunkStrategy = "fixed"
    ):
        """Async generator that yields progress events while embedding each chunk.

        Event shapes:
          {"type": "start",    "doc_id": str, "total": int}
          {"type": "progress", "current": int, "total": int, "section": str}
          {"type": "done",     "doc_id": str, "chunks": int, "source": str, "strategy": str}
          {"type": "error",    "message": str}
        """
        doc_id = "doc_" + uuid.uuid4().hex[:8]
        chunks = split_chunks(text, source=source, strategy=strategy)

        if not chunks:
            yield {"type": "done", "doc_id": doc_id, "chunks": 0, "source": source, "strategy": strategy}
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
            "[RAG] added document %s (%d chunks, source=%r, strategy=%s)",
            doc_id, len(chunks), source, strategy,
        )
        yield {"type": "done", "doc_id": doc_id, "chunks": len(chunks), "source": source, "strategy": strategy}

    async def add_document(
        self, text: str, source: str = "", strategy: ChunkStrategy = "fixed"
    ) -> dict:
        doc_id = "doc_" + uuid.uuid4().hex[:8]
        chunks = split_chunks(text, source=source, strategy=strategy)
        if not chunks:
            return {"doc_id": doc_id, "chunks": 0, "source": source, "strategy": strategy}

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
            "[RAG] added document %s (%d chunks, source=%r, strategy=%s)",
            doc_id, len(chunks), source, strategy,
        )
        return {"doc_id": doc_id, "chunks": len(chunks), "source": source, "strategy": strategy}

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        total = self._collection.count()
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
            if r.get("title"):
                parts.append(r["title"])
            if r.get("section"):
                parts.append(r["section"])
            label = f" [{' / '.join(parts)}]" if parts else (f" [{r['source']}]" if r["source"] else "")
            lines.append(f"({i}){label} {r['text']}")
        return "\n".join(lines)