# ADR-003: Hybrid BM25 + Vector RAG with Owner-Scoped Isolation

- **Status:** Accepted
- **Evidence in Repo:** `src/rag_engine.py`, `src/security.py`, `scripts/build_vector_store.py`

## Context
FreeData.AI indexes both shared public/reference documents (`docs/manifest.json`) and user-uploaded documents across French and English queries.

## Problem
Pure semantic vector search misses exact domain terms (e.g., `XAF/kg`, `80/8/12`, `SWOT`), external embedding APIs may be unavailable offline or in tests, and multi-tenant RAG risks cross-user data leakage.

## Options Considered
1. Vector-only retrieval requiring external embedding APIs at all times.
2. Hybrid BM25 + semantic cosine retrieval with deterministic hashed-embedding fallback and strict `owner_id` filtering.

## Decision
Use `HybridRAGEngine` (`src/rag_engine.py`) combining normalized BM25 (0.65) and cosine similarity (0.35) with bilingual synonym query expansion (`rewrite_query`), deterministic `_hashed_embedding` for zero-dependency/offline execution (alongside `EMBED_API_KEY`/Jina v3 support in `scripts/build_vector_store.py`), and `filter_rag_hits_for_owner` (`src/security.py`) to isolate private documents.

## Consequences
- **Positive:** Reproducible offline testing, higher MRR than BM25-only or hashed-vector-only (verified in `run_rag_retrieval_ablation`), and tenant isolation.
- **Trade-off:** Hashed n-gram embeddings are weaker on deep paraphrase matching than dense transformer embeddings when external embedding APIs are disabled.

