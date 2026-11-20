"""Application & AI Security Utilities: Signed User Tokens, File Validation, Prompt-Injection Sanitization & RAG Isolation."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
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
    "text/x-markdown",
    "text/comma-separated-values",
    "application/csv",
    "application/x-pdf",
    "application/vnd.ms-excel",  # Android déclare ainsi certains .csv
)
# Les navigateurs mobiles (iOS Safari, Android) envoient souvent un MIME vide ou générique :
# l'extension + les magic bytes décident alors (vérifiés plus bas).
_GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream", "application/unknown"}
_INDIRECT_INJECTION_RE = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous\s+instructions|ignore[rz]?\s+toutes?\s+les?\s+instructions?|"
    r"system\s+prompt|prompt\s+syst[eè]me|you\s+are\s+now|tu\s+es\s+maintenant|"
    r"drop\s+table|;\s*delete\s+from|reveal\s+api\s+key|r[eé]v[eè]le\w*\s+la\s+cl[eé]|"
    r"supabase_service_role_key|admin_token|bypass\s+quota|contourne\w*\s+les?\s+quotas?)",
    re.IGNORECASE,
)
_PDF_DANGEROUS_ACTION_RE = re.compile(rb"/(?:JavaScript|JS\b|Launch|OpenAction\s*<<[^>]*?/JavaScript)", re.IGNORECASE)
_REVOKED_TOKENS: set[str] = set()
_TOKEN_ISSUER = "freedata-ai"
_TOKEN_AUDIENCE = "freedata-app"


def issue_signed_user_token(
    user_id: str,
    secret: str,
    *,
    ttl_seconds: int = 3600,
    original_iat: Optional[int] = None,
) -> str:
    if not secret or len(secret) < 16:
        raise ValueError("AUTH_SECRET doit contenir au moins 16 caractères.")
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iss": _TOKEN_ISSUER,
        "aud": _TOKEN_AUDIENCE,
        "iat": now,
        # Date de la connexion initiale (par mot de passe) : conservée à chaque renouvellement pour borner la durée totale.
        "oiat": int(original_iat) if original_iat else now,
        "exp": now + ttl_seconds,
        "jti": secrets.token_hex(8),
    }
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
        if not isinstance(payload, dict):
            return None
        if "iss" in payload and payload["iss"] != _TOKEN_ISSUER:
            return None
        if "aud" in payload and payload["aud"] != _TOKEN_AUDIENCE:
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        sub = str(payload.get("sub") or "").strip()
        return sub if len(sub) >= 3 else None
    except Exception:
        return None


def token_claims(token: str) -> dict[str, Any]:
    """Revendications d'un jeton (SANS vérifier la signature) : à n'utiliser qu'après verify_signed_user_token."""
    try:
        raw = token.split(".", 1)[0]
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


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

    mime_clean = (mime_type or "").strip().lower()
    if mime_clean not in _GENERIC_MIME_TYPES and not any(mime_clean.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
        raise ValueError(f"Type MIME non autorisé : {mime_type}")

    if len(content_bytes) == 0:
        raise ValueError("Le fichier est vide.")
    if len(content_bytes) > max_bytes:
        raise ValueError(f"Fichier trop volumineux ({len(content_bytes)} octets > {max_bytes} max).")

    if ext == ".pdf":
        if not content_bytes.startswith(b"%PDF-"):
            raise ValueError("Contenu PDF invalide (en-tête %PDF- manquant).")
        if _PDF_DANGEROUS_ACTION_RE.search(content_bytes):
            raise ValueError("PDF contenant des actions actives/JavaScript bloqué par sécurité.")

    if (
        content_bytes.startswith((b"MZ", b"\x7fELF", b"\xfe\xed\xfa", b"PK\x03\x04"))
        or b"<script" in content_bytes[:4096].lower()
    ):
        raise ValueError("Contenu exécutable, archive ou script potentiellement malveillant bloqué.")

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


_SECRET_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(postgresql|postgres|mysql|redis)://([^:\s/@]+):([^@\s/]+)@", re.IGNORECASE), r"\1://\2:[REDACTED]@"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"\b(?:gsk_|jina_|sb_secret_|sk-[a-zA-Z0-9]|fd_)[A-Za-z0-9._\-]{6,}"), "[REDACTED_KEY]"),
    (re.compile(r"((?:api[_-]?key|token|secret|password)\s*[=:]\s*)([^\s,;'\"]+)", re.IGNORECASE), r"\1[REDACTED]"),
)


def redact_secrets(value: Any) -> str:
    """Redacts API keys, Bearer tokens, and DB passwords from log messages or diagnostic strings."""
    text = str(value if value is not None else "")
    for pat, repl in _SECRET_REDACTION_PATTERNS:
        text = pat.sub(repl, text)
    return text


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

