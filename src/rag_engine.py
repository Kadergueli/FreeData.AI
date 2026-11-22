"""Hybrid RAG Engine: multi-format ingestion, BM25 + vector hybrid retrieval, reranking, and evaluation."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_SYNONYMS = {
    "mil": "millet",
    "sorgho": "sorghum",
    "mais": "maize",
    "riz": "rice rice_local",
    "arachide": "groundnuts groundnut_raw",
    "niebe": "cowpeas beans",
    "sesame": "sesame oilseed",
    "gomme arabique": "gum arabic acacia",
    "gomme": "gum arabic acacia",
    "oignon": "onion",
    "tomate": "tomato",
    "coton": "cotton",
    "betail": "livestock cattle",
    "bovins": "cattle livestock",
    "ovins": "sheep livestock",
    "caprins": "goats livestock",
    "viande": "meat livestock",
    "lait": "milk dairy",
    "poisson": "fisheries",
    "coro": "coro local unit kg",
    "koro": "coro local unit kg",
    "sac": "bag 100kg",
    "bord champ": "farmgate discount",
    "soudure": "lean season deficit",
    "recolte": "harvest",
    "pluvial": "rainfed",
    "ndjamena": "n'djamena",
    "abeche": "ouaddai",
    "moundou": "logone occidental",
    "sarh": "moyen-chari",
    "bongor": "mayo-kebbi est",
    "doba": "logone oriental",
    "koumra": "mandoul",
    "pala": "mayo-kebbi ouest",
    "mongo": "guera",
    "ati": "batha",
    "mao": "kanem",
    "bol": "lac",
    "point mort": "break-even",
    "risque": "credit passport volatility",
}


def _norm_tokens(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return re.findall(r"[a-z0-9]+", stripped)


def _hashed_embedding(text: str, dim: int = 128) -> np.ndarray:
    """Deterministic feature-hashed n-gram embedding (zero external API dependency)."""
    vec = np.zeros(dim, dtype=float)
    tokens = _norm_tokens(text)
    if not tokens:
        return vec
    grams = list(tokens) + [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def rewrite_query(query: str) -> str:
    """Expands French/English agricultural synonyms for higher recall."""
    q_norm = " ".join(_norm_tokens(query))
    expansions = [v for k, v in _SYNONYMS.items() if k in q_norm]
    return f"{query} {' '.join(expansions)}".strip()


@dataclass
class RAGChunk:
    chunk_id: str
    content: str
    title: str
    source: str
    doc_type: str  # markdown | csv | json | report
    metadata: dict[str, Any] = field(default_factory=dict)
    tokens: list[str] = field(default_factory=list)
    embedding: np.ndarray = field(default_factory=lambda: np.zeros(128))


class HybridRAGEngine:
    """Local hybrid BM25 + semantic cosine retriever with metadata filtering, reranking, and compression."""

    def __init__(self) -> None:
        self.chunks: list[RAGChunk] = []
        self._df: dict[str, int] = {}
        self._avg_len: float = 1.0

    def add_text_document(
        self,
        doc_id: str,
        text: str,
        *,
        title: str,
        source: str,
        doc_type: str = "markdown",
        metadata: Optional[dict[str, Any]] = None,
        chunk_size: int = 900,
        overlap: int = 150,
    ) -> int:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return 0
        added = 0
        start = 0
        idx = 0
        while start < len(cleaned):
            piece = cleaned[start : start + chunk_size]
            tokens = _norm_tokens(piece)
            self.chunks.append(
                RAGChunk(
                    chunk_id=f"{doc_id}#{idx}",
                    content=piece,
                    title=title,
                    source=source,
                    doc_type=doc_type,
                    metadata=dict(metadata or {}),
                    tokens=tokens,
                    embedding=_hashed_embedding(piece),
                )
            )
            added += 1
            idx += 1
            if start + chunk_size >= len(cleaned):
                break
            start += chunk_size - overlap
        self._rebuild_stats()
        return added

    def ingest_file(self, path: Path, *, source: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> int:
        suffix = path.suffix.lower()
        src = source or path.name
        if suffix in (".md", ".txt"):
            return self.add_text_document(path.stem, path.read_text(encoding="utf-8"), title=path.stem, source=src, doc_type="markdown", metadata=metadata)
        if suffix == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            txt = json.dumps(raw, ensure_ascii=False)
            return self.add_text_document(path.stem, txt, title=path.stem, source=src, doc_type="json", metadata=metadata)
        if suffix == ".csv":
            df = pd.read_csv(path).head(200)
            txt = df.to_string(index=False)
            return self.add_text_document(path.stem, txt, title=path.stem, source=src, doc_type="csv", metadata=metadata)
        return 0

    def _rebuild_stats(self) -> None:
        df_counts: dict[str, int] = {}
        total_len = 0
        for ch in self.chunks:
            total_len += len(ch.tokens)
            for t in set(ch.tokens):
                df_counts[t] = df_counts.get(t, 0) + 1
        self._df = df_counts
        self._avg_len = total_len / max(1, len(self.chunks))

    def _bm25_score(self, query_tokens: list[str], chunk: RAGChunk, k1: float = 1.5, b: float = 0.75) -> float:
        n_docs = max(1, len(self.chunks))
        doc_len = max(1, len(chunk.tokens))
        tf_map: dict[str, int] = {}
        for t in chunk.tokens:
            tf_map[t] = tf_map.get(t, 0) + 1
        score = 0.0
        for t in query_tokens:
            tf = tf_map.get(t, 0)
            if tf == 0:
                continue
            df = self._df.get(t, 0)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1.0 - b + b * (doc_len / self._avg_len))
            score += idf * ((tf * (k1 + 1.0)) / denom)
        return score

    @staticmethod
    def _compress_context(content: str, query_tokens: list[str], max_chars: int = 360) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", content)
        qset = set(query_tokens)
        scored = sorted(
            sentences,
            key=lambda s: len(qset.intersection(_norm_tokens(s))),
            reverse=True,
        )
        out = " ".join(scored[:2]).strip()
        return out[:max_chars] if out else content[:max_chars]

    def search(
        self,
        query: str,
        *,
        top_k: int = 4,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        if not self.chunks:
            return []
        rewritten = rewrite_query(query)
        q_tokens = _norm_tokens(rewritten)
        q_vec = _hashed_embedding(rewritten)

        candidates = []
        for ch in self.chunks:
            if filters:
                if any(str(ch.metadata.get(k, "")).lower() != str(v).lower() for k, v in filters.items() if v is not None):
                    continue
            bm25 = self._bm25_score(q_tokens, ch)
            cos = float(np.dot(q_vec, ch.embedding))
            # Hybrid reranking score (normalized BM25 + semantic cosine)
            hybrid = 0.65 * (bm25 / (1.0 + bm25)) + 0.35 * max(0.0, cos)
            if hybrid > 0.0:
                candidates.append((hybrid, bm25, cos, ch))

        candidates.sort(key=lambda x: x[0], reverse=True)
        results = []
        for hybrid, bm25, cos, ch in candidates[:top_k]:
            results.append({
                "chunk_id": ch.chunk_id,
                "title": ch.title,
                "source": ch.source,
                "doc_type": ch.doc_type,
                "metadata": ch.metadata,
                "score": round(hybrid, 4),
                "bm25": round(bm25, 4),
                "semantic_cosine": round(cos, 4),
                "compressed_excerpt": self._compress_context(ch.content, q_tokens),
                "verified_fact": False,  # Retrieved text is never automatically treated as verified data
            })
        return results

    def evaluate_retrieval(self, eval_cases: list[dict[str, Any]], top_k: int = 3) -> dict[str, Any]:
        """Evaluates Precision@k and Mean Reciprocal Rank (MRR) on benchmark queries."""
        if not eval_cases:
            return {"cases": 0, "precision_at_k": 0.0, "mrr": 0.0}
        prec_sum = 0.0
        rr_sum = 0.0
        for case in eval_cases:
            hits = self.search(case["query"], top_k=top_k, filters=case.get("filters"))
            expected = str(case["expected_title"]).lower()
            hit_titles = [h["title"].lower() for h in hits]
            if expected in hit_titles:
                rank = hit_titles.index(expected) + 1
                rr_sum += 1.0 / rank
                prec_sum += 1.0 / max(1, len(hits))
        n = len(eval_cases)
        return {
            "cases": n,
            "top_k": top_k,
            "precision_at_k": round(prec_sum / n, 3),
            "mrr": round(rr_sum / n, 3),
        }

