"""Application & AI Security Utilities: Signed User Tokens, File Validation, Prompt-Injection Sanitization & RAG Isolation."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

_ALLOWED_EXTENSIONS = {".pdf", ".csv", ".json", ".txt", ".md"}
_ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "text/csv",
    "application/json",
    "text/plain",
    "text/markdown",
)
_INDIRECT_INJECTION_RE = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous\s+instructions|system\s+prompt|you\s+are\s+now|"
    r"drop\s+table|;\s*delete\s+from|reveal\s+api\s+key|supabase_service_role_key)",
    re.IGNORECASE,
)
_REVOKED_TOKENS: set[str] = set()


def issue_signed_user_token(user_id: str, secret: str, *, ttl_seconds: int = 3600) -> str:
    if not secret or len(secret) < 16:
        raise ValueError("AUTH_SECRET doit contenir au moins 16 caractères.")
    payload = {"sub": user_id, "exp": int(time.time()) + ttl_seconds}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), raw.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_signed_user_token(token: str, secret: str) -> Optional[str]:
    if not token or not secret or "." not in token:
        return None
    if token in _REVOKED_TOKENS:
        return None
    try:
        raw, sig = token.split(".", 1)
        expected = hmac.new(secret.encode("utf-8"), raw.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        sub = str(payload.get("sub") or "").strip()
        return sub if len(sub) >= 3 else None
    except Exception:
        return None


def revoke_user_token(token: str) -> None:
    if token:
        _REVOKED_TOKENS.add(token)


def validate_uploaded_document(
    filename: str,
    content_bytes: bytes,
    *,
    mime_type: Optional[str] = None,
    max_bytes: int = 2 * 1024 * 1024,
) -> dict[str, Any]:
    """Validates file name, extension, MIME, size, magic bytes, and indirect prompt injection."""
    clean_name = Path(filename or "").name
    if not clean_name or clean_name != filename or ".." in filename or "/" in filename or "\\" in filename or "\x00" in filename:
        raise ValueError("Nom de fichier invalide (traversée de répertoire détectée).")

    ext = Path(clean_name).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise ValueError(f"Extension non autorisée ({ext}). Autorisées : {sorted(_ALLOWED_EXTENSIONS)}")

    if mime_type and not any(mime_type.lower().startswith(p) for p in _ALLOWED_MIME_PREFIXES):
        raise ValueError(f"Type MIME non autorisé : {mime_type}")

    if len(content_bytes) == 0:
        raise ValueError("Le fichier est vide.")
    if len(content_bytes) > max_bytes:
        raise ValueError(f"Fichier trop volumineux ({len(content_bytes)} octets > {max_bytes} max).")

    if ext == ".pdf" and not content_bytes.startswith(b"%PDF-"):
        raise ValueError("Contenu PDF invalide (en-tête %PDF- manquant).")

    if content_bytes.startswith(b"MZ") or b"<script" in content_bytes[:4096].lower():
        raise ValueError("Contenu exécutable ou script potentiellement malveillant bloqué.")

    sanitized_text = ""
    injection_detected = False
    if ext in (".txt", ".md", ".csv", ".json"):
        decoded = content_bytes.decode("utf-8", errors="replace")
        if _INDIRECT_INJECTION_RE.search(decoded):
            injection_detected = True
            decoded = _INDIRECT_INJECTION_RE.sub("[CONTENU_FILTRE]", decoded)
        sanitized_text = decoded

    return {
        "filename": clean_name,
        "extension": ext,
        "size_bytes": len(content_bytes),
        "indirect_injection_filtered": injection_detected,
        "sanitized_preview": sanitized_text[:500] if sanitized_text else None,
    }


def filter_rag_hits_for_owner(hits: list[dict[str, Any]], owner_id: Optional[str]) -> list[dict[str, Any]]:
    """Ensures private user chunks (metadata.owner_id set) are never leaked to other users or public queries."""
    out = []
    for h in hits:
        meta = h.get("metadata") or {}
        doc_owner = meta.get("owner_id")
        if doc_owner and doc_owner != owner_id:
            continue
        out.append(h)
    return out

