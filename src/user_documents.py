"""Private User Document Vault & Jina Embeddings / Hybrid BM25 Retrieval + Groq Synthesis.

Architecture:
1. Validation & Anti-Injection: `validate_uploaded_document` checks size, MIME, magic bytes, and indirect prompt injection.
2. PDF / CSV / MD / TXT / JSON Extraction: Extracts clean text (using `pypdf` for PDFs with fallback).
3. Chunking & Jina Embeddings (`EMBED_API_KEY` / `jina-embeddings-v3`):
   - Computes 1024-d semantic vectors via Jina API for user PDFs/documents when `EMBED_API_KEY` is configured.
   - Always computes a local 128-d deterministic hash vector + BM25 tokens as a sovereign zero-downtime fallback.
4. Strict Owner Isolation (`owner_id`):
   - Stored in `user_documents` and `user_document_chunks` (SQLite locally / `freedata_app` schema on Supabase PostgreSQL).
   - Every query filters strictly by `WHERE owner_id = ?`. No user can ever access or retrieve another user's document.
5. Token Budget Management for Groq (`LLM_API_KEY`):
   - Retrieves only the top-K most relevant chunks (compressed to <= 450 chars per chunk, max ~1 500 chars total)
     so Groq receives high-signal excerpts without exhausting context window or token quotas.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import requests

from src import db as _db
from src.config import settings
from src.rag_engine import _hashed_embedding, _norm_tokens, rewrite_query
from src.security import _INDIRECT_INJECTION_RE, redact_secrets, validate_uploaded_document

logger = logging.getLogger("freedata.user_documents")

_MALICIOUS_OR_UNSAFE_DOC_RE = re.compile(
    r"\b(?:porno(?:graphie|graphique)?|nsfw|xxx|sexe\s+explicite|pedophil|terroris(?:me|te)|"
    r"bombe\s+artisanale|explosif\s+militaire|trafic\s+d['’]?armes|ransomware|malware|keylogger|"
    r"exploit\s+payload|reverse\s+shell|ddos\s+attack|injection\s+sql|pirater\s+un\s+compte|"
    r"blanchiment\s+d['’]?argent|drogue\s+dure|cocaine|heroine)\b",
    re.IGNORECASE,
)

_DOMAIN_VOCAB_RE = re.compile(
    r"\b(?:mil|millet|sorgho|sorghum|berbere|mais|maize|riz|rice|arachide|groundnut|peanut|"
    r"sesame|niebe|cowpea|haricot|manioc|cassava|oignon|onion|tomate|gombo|okra|ail|piment|"
    r"betail|bovin|ovin|caprin|chameau|volaille|poisson|viande|lait|sucre|huile|farine|cereale|"
    r"semence|engrais|intrant|recolte|campagne|agricol\w*|elevage|pastoral\w*|agro\w*|vivrier\w*|"
    r"marche|prix|tarif|cout|fret|transport\w*|camion|tonne\w*|sac\w*|kg|kilogramme\w*|quintal|"
    r"stock\w*|magasin\w*|entrepot|logistique|corridor|commerce|commercant|negociant|grossiste|"
    r"detaillant|cooperative|producteur|acheteur|vendeur|client|fournisseur|facture|devis|contrat|"
    r"bon\s+de\s+commande|bordereau|livraison|"
    r"xaf|fcfa|cfa|franc\w*|capital|budget|marge|benefice|rentabilite|revenu|chiffre\s+d['’]?affaires|"
    r"depense|charge|investissement|bfr|capex|tresorerie|credit|pret|emprunt|microfinance|imf|"
    r"banque|garantie|collateral|ltv|taux|remboursement|financement|subvention|business\s*plan|"
    r"etude|projet|risque|inflation|volatilite|saisonnalite|soudure|anomalie|"
    r"tchad\w*|ndjamena|djamena|moundou|sarh|abeche|mongo|am\s+timan|salamat|ouaddai|guera|"
    r"logone|mayo|kebbi|tandjile|mandoul|moyen\s+chari|lac|kanem|bahr\s+el\s+ghazal|batha|wadi\s+fira|"
    r"sila|ennedi|tibesti|borkou|chari\s+baguirmi|hadjer\s+lamis|sahel|fews\s*net|pam|wfp|fao|ocha|"
    r"ong|humanitaire|securite\s+alimentaire|analyse|statistique|serie|prevision|donnee\w*|rapport|"
    r"enquete|collecte|indicateur|tableau|indice|economie|economique|developpement)\b",
    re.IGNORECASE,
)


_EXPLICIT_DOC_QUERY_RE = re.compile(
    r"\b(?:document|pdf|fichier|contrat|devis|facture|rapport|dossier|etude|annexe|"
    r"piece\s+jointe|televerse|uploade|importe|ce\s+texte|mon\s+tableau|mes\s+donnees)\b",
    re.IGNORECASE,
)

_DOC_OVERVIEW_INTENT_RE = re.compile(
    r"\b(?:resume\w*|synthes\w*|analyse\w*|points?\s+cles?|apercu|de\s+quoi\s+parle|contenu\s+de|explique\w*)\b",
    re.IGNORECASE,
)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def validate_document_domain_relevance(text: str, filename: str = "") -> dict[str, Any]:
    """Ensures uploaded documents are safe and relevant to FreeData.AI's professional scope
    (agriculture, trade, logistics, finance, market studies, economics, data science, or Chad/Sahel).
    Evaluates the document BODY (not just the filename) so a single keyword in a filename cannot bypass validation.
    Raises ValueError if malicious, abusive, or out-of-domain.
    """
    full_norm = _strip_accents(f"{filename} {text}")
    bad = _MALICIOUS_OR_UNSAFE_DOC_RE.search(full_norm)
    if bad:
        raise ValueError(
            "Document refusé par la charte de sécurité FreeData.AI : contenu inapproprié, illicite ou malveillant détecté."
        )

    body_norm = _strip_accents(text)
    body_words = re.findall(r"[a-z0-9]{2,}", body_norm)
    body_matches = [m.group(0).lower() for m in _DOMAIN_VOCAB_RE.finditer(body_norm)]
    distinct_terms = sorted(set(body_matches))
    word_count = max(1, len(body_words))
    density = len(body_matches) / word_count

    # Require at least 2 distinct domain terms in the document body, and for longer texts (>= 60 words)
    # require a minimum topical density (>= 2.5%) or >= 4 distinct domain terms to reject mixed-domain noise.
    if len(distinct_terms) < 2 or (word_count >= 60 and density < 0.025 and len(distinct_terms) < 4):
        raise ValueError(
            "Document hors périmètre FreeData.AI : le contenu du document ne présente pas suffisamment "
            "d'éléments liés à l'agriculture, au négoce, à la logistique/transport, à la finance/microfinance, "
            "aux études de marché ou à l'économie au Tchad/Sahel."
        )
    return {
        "domain_valid": True,
        "matched_domain_terms": distinct_terms[:15],
        "domain_density": round(density, 4),
    }


def extract_document_business_parameters(text: str) -> dict[str, Any]:
    """Automatically extracts structured business parameters (commodity, origin/dest provinces,
    capital_xaf, transport_cost_per_kg, quantity_kg) from document text so FreeData.AI's calculation
    engines (Market Simulator, Credit Passport, Arbitrage) can immediately integrate them.
    """
    try:
        from src.ai_agent import _extract_business_params_with_meta, _resolve_provinces_and_commodity

        provs, comm = _resolve_provinces_and_commodity(text)
        biz = _extract_business_params_with_meta(_strip_accents(text))
        out: dict[str, Any] = {
            "commodity": comm,
            "provinces": provs[:4],
            "origin_province": provs[0] if provs else None,
            "dest_province": provs[1] if len(provs) >= 2 else None,
            "capital_xaf": biz["capital_xaf"] if not biz.get("is_default_capital", True) else None,
            "transport_cost_per_kg": (
                biz["transport_cost_per_kg"] if not biz.get("is_default_transport", True) else None
            ),
            "quantity_kg": biz.get("quantity_kg"),
        }
        return {k: v for k, v in out.items() if v is not None and v != []}
    except Exception:
        return {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_text_from_bytes(filename: str, content_bytes: bytes) -> tuple[str, int]:
    """Extracts sanitized text and page/section count from .pdf, .csv, .txt, .md, or .json."""
    ext = Path(filename or "").suffix.lower()
    text = ""
    page_count = 1

    if ext == ".pdf":
        extracted_pages: list[str] = []
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content_bytes))
            page_count = max(1, len(reader.pages))
            for idx, page in enumerate(reader.pages, start=1):
                page_txt = (page.extract_text() or "").strip()
                if page_txt:
                    extracted_pages.append(f"[Page {idx}] {page_txt}")
        except Exception as exc:
            logger.warning("pypdf extraction fallback for %s: %s", filename, exc)

        if not extracted_pages:
            # Lightweight fallback for simple/uncompressed PDF streams in tests or minimal PDFs
            latin = content_bytes.decode("latin-1", errors="ignore")
            literals = re.findall(r"\(([^()\\]{3,})\)", latin)
            if literals:
                extracted_pages.append(" ".join(literals))
        text = "\n\n".join(extracted_pages).strip()
        if not text:
            raise ValueError(
                "Aucun texte extractible dans ce PDF (il s'agit probablement d'une image scannée sans couche texte OCR)."
            )

    elif ext == ".csv":
        df = pd.read_csv(io.BytesIO(content_bytes)).head(300)
        page_count = 1
        cols = ", ".join(str(c) for c in df.columns)
        text = f"Colonnes CSV ({len(df)} lignes) : {cols}\n" + df.to_string(index=False)

    elif ext == ".json":
        raw = json.loads(content_bytes.decode("utf-8", errors="replace"))
        text = json.dumps(raw, ensure_ascii=False, indent=2)

    else:  # .txt, .md
        text = content_bytes.decode("utf-8", errors="replace")

    if _INDIRECT_INJECTION_RE.search(text):
        text = _INDIRECT_INJECTION_RE.sub("[CONTENU_FILTRE]", text)

    cleaned = " ".join(text.split())
    if not cleaned:
        raise ValueError("Le document ne contient aucun texte exploitable.")
    return cleaned, page_count


def chunk_document_text_with_meta(
    text: str,
    *,
    chunk_size: int = 1000,
    overlap: int = 180,
    max_chunks: int = 80,
    chunk_offset: int = 0,
) -> dict[str, Any]:
    """Splits document text into overlapping chunks with explicit truncation/progressive-indexing metadata."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return {
            "chunks": [],
            "total_chunks": 0,
            "indexed_chunks": 0,
            "chunk_offset": max(0, int(chunk_offset)),
            "truncated": False,
            "coverage_pct": 100.0,
            "next_offset": None,
        }
    step = max(1, chunk_size - overlap)
    all_chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = start + chunk_size
        all_chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start += step

    total = len(all_chunks)
    offset = max(0, min(int(chunk_offset), total))
    selected = all_chunks[offset : offset + max(1, int(max_chunks))]
    end_idx = offset + len(selected)
    truncated = end_idx < total
    coverage = round((end_idx / max(1, total)) * 100.0, 1)
    return {
        "chunks": selected,
        "total_chunks": total,
        "indexed_chunks": len(selected),
        "chunk_offset": offset,
        "truncated": truncated,
        "coverage_pct": coverage,
        "next_offset": end_idx if truncated else None,
    }


def chunk_document_text(text: str, *, chunk_size: int = 1000, overlap: int = 180, max_chunks: int = 80) -> list[str]:
    """Splits document text into overlapping chunks capped at `max_chunks` to control token/embedding costs."""
    return chunk_document_text_with_meta(
        text,
        chunk_size=chunk_size,
        overlap=overlap,
        max_chunks=max_chunks,
    )["chunks"]


def compute_jina_embeddings(texts: list[str]) -> Optional[list[list[float]]]:
    """Calls Jina Embeddings API (`EMBED_API_KEY`) in batches of 16; returns None if unconfigured or unreachable."""
    api_key = (settings.embed_api_key or os.getenv("EMBED_API_KEY", "")).strip()
    if not api_key or not texts:
        return None
    base_url = (settings.embed_base_url or "https://api.jina.ai/v1/embeddings").strip()
    model = (settings.embed_model or "jina-embeddings-v3").strip()
    all_vecs: list[list[float]] = []
    try:
        for i in range(0, len(texts), 16):
            batch = texts[i : i + 16]
            resp = requests.post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "input": batch},
                timeout=12,
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
            ordered = [
                item["embedding"]
                for _, item in sorted(enumerate(data), key=lambda pair: pair[1].get("index", pair[0]))
            ]
            if len(ordered) != len(batch):
                return None
            all_vecs.extend(ordered)
        return all_vecs
    except Exception as exc:
        logger.warning("Jina Embeddings unavailable, falling back to local hybrid vector/BM25: %s", redact_secrets(exc))
        return None


def _cosine_similarity(vec_a: list[float] | np.ndarray, vec_b: list[float] | np.ndarray) -> float:
    a = np.asarray(vec_a, dtype=float)
    b = np.asarray(vec_b, dtype=float)
    if a.shape != b.shape or a.size == 0:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-9:
        return 0.0
    return float(np.dot(a, b) / denom)


class UserDocumentStore:
    """Private per-user document vault with Jina semantic embeddings + local BM25/hash fallback."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        database_url: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> None:
        self._pg_url = _db.resolve_backend(db_path, database_url_override=database_url)
        self._pg_schema = (
            _db.validate_schema(schema)
            if schema
            else (_db.new_test_schema(db_path) if (self._pg_url and db_path) else _db.DEFAULT_SCHEMA)
        )
        self.db_path = Path(db_path or os.getenv("FREEDATA_DOCUMENTS_DB_PATH", "data/freedata_documents.db"))
        if not self._pg_url:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        if self._pg_url:
            return _db.pg_connect(self._pg_url, self._pg_schema)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_documents (
                    doc_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    project_id TEXT,
                    filename TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    page_count INTEGER NOT NULL DEFAULT 1,
                    chunks_count INTEGER NOT NULL DEFAULT 0,
                    total_chunks INTEGER NOT NULL DEFAULT 0,
                    indexing_status TEXT NOT NULL DEFAULT 'complete',
                    content_hash TEXT,
                    embedding_provider TEXT NOT NULL DEFAULT 'local_hybrid',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_user_documents_owner
                    ON user_documents(owner_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS user_document_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    project_id TEXT,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    jina_embedding_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_user_doc_chunks_owner
                    ON user_document_chunks(owner_id, doc_id, chunk_index);
                """
            )
            # Migration douce (idempotente) pour bases existantes
            # PostgreSQL avorte la transaction courante sur DuplicateColumn : utiliser IF NOT EXISTS + SAVEPOINT.
            alter_kw = "ADD COLUMN IF NOT EXISTS" if self._pg_url else "ADD COLUMN"
            for idx_i, stmt in enumerate((
                f"ALTER TABLE user_documents {alter_kw} project_id TEXT",
                f"ALTER TABLE user_documents {alter_kw} total_chunks INTEGER NOT NULL DEFAULT 0",
                f"ALTER TABLE user_documents {alter_kw} indexing_status TEXT NOT NULL DEFAULT 'complete'",
                f"ALTER TABLE user_documents {alter_kw} content_hash TEXT",
                f"ALTER TABLE user_document_chunks {alter_kw} project_id TEXT",
                "CREATE INDEX IF NOT EXISTS idx_user_documents_owner_project ON user_documents(owner_id, project_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_user_doc_chunks_owner_project ON user_document_chunks(owner_id, project_id)",
            )):
                sp = f"sp_doc_mig_{idx_i}"
                try:
                    if self._pg_url:
                        conn.execute(f"SAVEPOINT {sp}")
                    conn.execute(stmt)
                    if self._pg_url:
                        conn.execute(f"RELEASE SAVEPOINT {sp}")
                except Exception:
                    if self._pg_url:
                        conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                        conn.execute(f"RELEASE SAVEPOINT {sp}")
            if self._pg_url:
                _db.harden_tables(conn)

    def ingest_document(
        self,
        owner_id: str,
        *,
        filename: str,
        content_bytes: bytes,
        mime_type: Optional[str] = None,
        project_id: Optional[str] = None,
        max_bytes: int = 2 * 1024 * 1024,
        max_docs: int = 10,
        max_chunks: int = 40,
        chunk_offset: int = 0,
    ) -> dict[str, Any]:
        """Validates, extracts text, checks duplicates, indexes chunks via Jina (or local fallback),
        and persists under `owner_id` (and optional `project_id`) with explicit truncation metadata.
        """
        if not owner_id:
            raise PermissionError("Authentification requise pour téléverser un document.")

        clean_project_id = project_id.strip()[:80] if isinstance(project_id, str) and project_id.strip() else None

        validation = validate_uploaded_document(
            filename,
            content_bytes,
            mime_type=mime_type,
            max_bytes=max_bytes,
        )

        # Duplicate prevention per (owner_id, project_id, content_hash) on initial upload (chunk_offset == 0)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        if chunk_offset == 0:
            with self._connect() as conn:
                if clean_project_id:
                    dup = conn.execute(
                        "SELECT * FROM user_documents WHERE owner_id = ? AND project_id = ? AND content_hash = ?",
                        (owner_id, clean_project_id, content_hash),
                    ).fetchone()
                else:
                    dup = conn.execute(
                        "SELECT * FROM user_documents WHERE owner_id = ? AND (project_id IS NULL OR project_id = '') AND content_hash = ?",
                        (owner_id, content_hash),
                    ).fetchone()
                if dup:
                    d = dict(dup)
                    return {
                        **d,
                        "duplicate": True,
                        "raw_binary_stored": False,
                        "indexing_warning": (
                            "Ce document identique est déjà indexé dans cet espace (doublon évité)."
                        ),
                    }

        existing = self.list_documents(owner_id)
        if chunk_offset == 0 and len(existing) >= max_docs:
            raise OverflowError(
                f"Limite de documents atteinte ({max_docs} documents max pour votre plan). Supprimez un document existant ou passez à PRO."
            )

        text, page_count = extract_text_from_bytes(validation["filename"], content_bytes)
        domain_check = validate_document_domain_relevance(text, validation["filename"])
        extracted_params = extract_document_business_parameters(text)
        chunk_meta = chunk_document_text_with_meta(
            text,
            max_chunks=max_chunks,
            chunk_offset=chunk_offset,
        )
        text_chunks = chunk_meta["chunks"]
        if not text_chunks:
            raise ValueError("Aucun segment de texte exploitable n'a pu être extrait.")

        jina_vecs = compute_jina_embeddings(text_chunks)
        emb_provider = "jina-embeddings-v3" if jina_vecs is not None else "local_hybrid_bm25"
        indexing_status = "partial" if chunk_meta["truncated"] else "complete"
        indexing_warning = (
            f"Document volumineux : {chunk_meta['indexed_chunks']} segments indexés sur {chunk_meta['total_chunks']} "
            f"({chunk_meta['coverage_pct']}%). L'indexation est partielle ; utilisez chunk_offset={chunk_meta['next_offset']} "
            "pour poursuivre l'indexation progressive."
            if chunk_meta["truncated"]
            else None
        )

        doc_id = f"DOC-{uuid.uuid4().hex[:12].upper()}"
        now = _utc_now_iso()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_documents (
                    doc_id, owner_id, project_id, filename, extension, size_bytes,
                    page_count, chunks_count, total_chunks, indexing_status, content_hash,
                    embedding_provider, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    owner_id,
                    clean_project_id,
                    validation["filename"],
                    validation["extension"],
                    validation["size_bytes"],
                    page_count,
                    len(text_chunks),
                    int(chunk_meta["total_chunks"]),
                    indexing_status,
                    content_hash,
                    emb_provider,
                    now,
                ),
            )
            for idx, piece in enumerate(text_chunks):
                abs_idx = int(chunk_meta["chunk_offset"]) + idx
                chunk_id = f"{doc_id}#{abs_idx}"
                # Compress float precision to 4 decimals to prevent database bloat while preserving >99.9% cosine accuracy
                vec_json = (
                    json.dumps([round(float(v), 4) for v in jina_vecs[idx]], separators=(",", ":"))
                    if (jina_vecs and idx < len(jina_vecs))
                    else None
                )
                conn.execute(
                    """
                    INSERT INTO user_document_chunks (
                        chunk_id, doc_id, owner_id, project_id, chunk_index, content, jina_embedding_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (chunk_id, doc_id, owner_id, clean_project_id, abs_idx, piece, vec_json, now),
                )

        return {
            "doc_id": doc_id,
            "owner_id": owner_id,
            "project_id": clean_project_id,
            "filename": validation["filename"],
            "extension": validation["extension"],
            "size_bytes": validation["size_bytes"],
            "page_count": page_count,
            "chunks_count": len(text_chunks),
            "total_chunks": int(chunk_meta["total_chunks"]),
            "truncated": bool(chunk_meta["truncated"]),
            "coverage_pct": float(chunk_meta["coverage_pct"]),
            "next_offset": chunk_meta["next_offset"],
            "indexing_status": indexing_status,
            "indexing_warning": indexing_warning,
            "duplicate": False,
            "embedding_provider": emb_provider,
            "indirect_injection_filtered": validation["indirect_injection_filtered"],
            "domain_valid": domain_check["domain_valid"],
            "matched_domain_terms": domain_check["matched_domain_terms"],
            "extracted_business_params": extracted_params,
            "raw_binary_stored": False,
            "preview": text[:320],
            "created_at": now,
        }

    def list_documents(self, owner_id: str, *, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        if not owner_id:
            return []
        clean_pid = project_id.strip()[:80] if isinstance(project_id, str) and project_id.strip() else None
        with self._connect() as conn:
            if clean_pid:
                rows = conn.execute(
                    "SELECT * FROM user_documents WHERE owner_id = ? AND project_id = ? ORDER BY created_at DESC",
                    (owner_id, clean_pid),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM user_documents WHERE owner_id = ? ORDER BY created_at DESC",
                    (owner_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_document(self, owner_id: str, doc_id: str) -> bool:
        if not owner_id or not doc_id:
            return False
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM user_document_chunks WHERE owner_id = ? AND doc_id = ?",
                (owner_id, doc_id),
            )
            cur = conn.execute(
                "DELETE FROM user_documents WHERE owner_id = ? AND doc_id = ?",
                (owner_id, doc_id),
            )
            return (cur.rowcount or 0) > 0

    def delete_project_documents(self, owner_id: str, project_id: str) -> int:
        """Explicit lifecycle cleanup: safely deletes all documents & chunks attached to a deleted project."""
        if not owner_id or not project_id:
            return 0
        clean_pid = project_id.strip()[:80]
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM user_document_chunks WHERE owner_id = ? AND project_id = ?",
                (owner_id, clean_pid),
            )
            cur = conn.execute(
                "DELETE FROM user_documents WHERE owner_id = ? AND project_id = ?",
                (owner_id, clean_pid),
            )
            return int(cur.rowcount or 0)

    def purge_owner(self, owner_id: str) -> int:
        if not owner_id:
            return 0
        with self._connect() as conn:
            conn.execute("DELETE FROM user_document_chunks WHERE owner_id = ?", (owner_id,))
            cur = conn.execute("DELETE FROM user_documents WHERE owner_id = ?", (owner_id,))
            return int(cur.rowcount or 0)

    def retrieve_for_owner(
        self,
        owner_id: str,
        query: str,
        *,
        project_id: Optional[str] = None,
        top_k: int = 5,
        max_excerpt_chars: int = 700,
        min_score: float = 0.25,
    ) -> list[dict[str, Any]]:
        """Retrieves top-K chunks strictly belonging to `owner_id` (and scoped to `project_id` when provided),
        using Jina cosine + BM25 hybrid scoring.
        """
        if not owner_id or not (query or "").strip():
            return []

        clean_pid = project_id.strip()[:80] if isinstance(project_id, str) and project_id.strip() else None

        q_clean = _strip_accents(query)
        explicit_doc_ref = bool(_EXPLICIT_DOC_QUERY_RE.search(q_clean))
        # Skip unnecessary Jina/DB work on pure smalltalk greetings ("bonjour", "merci", "salut")
        if not explicit_doc_ref and len(q_clean.split()) <= 3 and re.fullmatch(
            r"(?:bonjour|bonsoir|salut|hello|hi|coucou|merci(?:\s+beaucoup)?|ok|d'accord|super|parfait|au\s+revoir)[!?. ]*",
            q_clean,
        ):
            return []

        with self._connect() as conn:
            if clean_pid:
                doc_rows = {
                    r["doc_id"]: dict(r)
                    for r in conn.execute(
                        "SELECT doc_id, filename, extension, embedding_provider, project_id FROM user_documents WHERE owner_id = ? AND project_id = ?",
                        (owner_id, clean_pid),
                    ).fetchall()
                }
                if not doc_rows:
                    return []
                chunk_rows = conn.execute(
                    "SELECT chunk_id, doc_id, chunk_index, content, jina_embedding_json FROM user_document_chunks WHERE owner_id = ? AND project_id = ?",
                    (owner_id, clean_pid),
                ).fetchall()
            else:
                doc_rows = {
                    r["doc_id"]: dict(r)
                    for r in conn.execute(
                        "SELECT doc_id, filename, extension, embedding_provider, project_id FROM user_documents WHERE owner_id = ? AND (project_id IS NULL OR project_id = '')",
                        (owner_id,),
                    ).fetchall()
                }
                if not doc_rows:
                    return []
                chunk_rows = conn.execute(
                    "SELECT chunk_id, doc_id, chunk_index, content, jina_embedding_json FROM user_document_chunks WHERE owner_id = ? AND (project_id IS NULL OR project_id = '')",
                    (owner_id,),
                ).fetchall()

        if not chunk_rows:
            return []

        rewritten = rewrite_query(query)
        q_tokens = _norm_tokens(rewritten)
        q_hash_vec = _hashed_embedding(rewritten)

        # Only call Jina query embedding if at least one chunk has a stored Jina vector
        has_jina_chunks = any(r["jina_embedding_json"] for r in chunk_rows)
        q_jina_vec: Optional[list[float]] = None
        if has_jina_chunks:
            vecs = compute_jina_embeddings([query])
            if vecs:
                q_jina_vec = vecs[0]

        # Precompute BM25 document frequencies across user's chunks
        parsed_chunks: list[tuple[dict[str, Any], list[str]]] = []
        df_counts: dict[str, int] = {}
        total_len = 0
        for r in chunk_rows:
            d = dict(r)
            toks = _norm_tokens(d["content"])
            parsed_chunks.append((d, toks))
            total_len += len(toks)
            for t in set(toks):
                df_counts[t] = df_counts.get(t, 0) + 1

        n_docs = max(1, len(parsed_chunks))
        avg_len = max(1.0, total_len / n_docs)

        scored: list[tuple[float, dict[str, Any], str]] = []
        for d, toks in parsed_chunks:
            doc_len = max(1, len(toks))
            tf_map: dict[str, int] = {}
            for t in toks:
                tf_map[t] = tf_map.get(t, 0) + 1
            bm25 = 0.0
            for t in q_tokens:
                tf = tf_map.get(t, 0)
                if tf == 0:
                    continue
                df = df_counts.get(t, 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + 1.5 * (1.0 - 0.75 + 0.75 * (doc_len / avg_len))
                bm25 += idf * ((tf * 2.5) / denom)

            sem_cos = 0.0
            raw_jina = d.get("jina_embedding_json")
            if q_jina_vec is not None and raw_jina:
                try:
                    c_vec = json.loads(raw_jina)
                    sem_cos = max(0.0, _cosine_similarity(q_jina_vec, c_vec))
                except Exception:
                    sem_cos = 0.0
            else:
                c_hash = _hashed_embedding(d["content"])
                sem_cos = max(0.0, float(np.dot(q_hash_vec, c_hash)))

            bm25_norm = bm25 / (1.0 + bm25)
            # If Jina vector is available, weight semantic similarity higher (60% Jina + 40% BM25)
            if q_jina_vec is not None and raw_jina:
                hybrid = 0.60 * sem_cos + 0.40 * bm25_norm
            else:
                hybrid = 0.60 * bm25_norm + 0.40 * sem_cos

            # Phase 2A: Never disable minimum relevance blindly just because the user said "document/rapport".
            # Only allow broad summary/overview retrieval ("résume mon document", "analyse mon contrat")
            # when the user explicitly asks for an overview; specific factual queries must meet a relevance floor.
            is_overview_query = explicit_doc_ref and bool(_DOC_OVERVIEW_INTENT_RE.search(q_clean))
            effective_floor = 0.05 if is_overview_query else (0.18 if explicit_doc_ref else min_score)
            total_score = hybrid
            if total_score >= effective_floor:
                scored.append((total_score, d, d["content"][:max_excerpt_chars]))

        scored.sort(key=lambda item: item[0], reverse=True)
        out: list[dict[str, Any]] = []
        for score, d, excerpt in scored[: max(1, top_k)]:
            doc_meta = doc_rows.get(d["doc_id"], {})
            fname = doc_meta.get("filename", "Document utilisateur")
            out.append({
                "chunk_id": d["chunk_id"],
                "doc_id": d["doc_id"],
                "filename": fname,
                "titre": f"{fname} (Document privé)",
                "editeur": "Espace personnel",
                "title": f"{fname} (Document privé)",
                "source": "Espace personnel",
                "page": int(d["chunk_index"]) + 1,
                "content": excerpt,
                "compressed_excerpt": excerpt,
                "similarity": round(min(0.99, float(score)), 4),
                "embedding_provider": doc_meta.get("embedding_provider", "local_hybrid"),
                "metadata": {"owner_id": owner_id, "doc_id": d["doc_id"], "private": True},
            })
        return out

