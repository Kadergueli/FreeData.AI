"""User Account Authentication Store (SQLite / Supabase PostgreSQL freedata_app) & Signed Bearer Sessions."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src import db as _db
from src.security import issue_signed_user_token, revoke_user_token, token_claims, verify_signed_user_token

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_PBKDF2_ITERATIONS = 260_000
DEFAULT_TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 jours
MAX_SESSION_LIFETIME_SECONDS = 30 * 24 * 3600  # durée totale max d'une session renouvelée (30 jours)
ALLOWED_PERSONAS = ("analyste", "agronome", "marche", "banque")


def normalize_persona(persona: Optional[str]) -> str:
    cleaned = (persona or "").strip().lower()
    return cleaned if cleaned in ALLOWED_PERSONAS else "analyste"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if not cleaned or len(cleaned) > 160 or not _EMAIL_RE.fullmatch(cleaned):
        raise ValueError("Adresse e-mail invalide.")
    return cleaned


def _hash_password(password: str, salt_hex: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        _PBKDF2_ITERATIONS,
    )
    return dk.hex()


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_auth_secret() -> str:
    """Retourne AUTH_SECRET depuis l'environnement (>= 16 car.), sinon lève RuntimeError."""
    secret = os.getenv("AUTH_SECRET", "").strip()
    if len(secret) < 16:
        raise RuntimeError("AUTH_SECRET non configuré (minimum 16 caractères requis pour les comptes utilisateurs).")
    return secret


class AuthStore:
    """Gestion des comptes utilisateurs (email/mot de passe PBKDF2-SHA256) et révocation de jetons."""

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
        self.db_path = Path(db_path or os.getenv("FREEDATA_AUTH_DB_PATH", "data/freedata_auth.db"))
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
                CREATE TABLE IF NOT EXISTS user_accounts (
                    user_id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_user_accounts_email ON user_accounts(email);
                CREATE TABLE IF NOT EXISTS revoked_tokens (
                    token_hash TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL,
                    revoked_at TEXT NOT NULL
                );
                """
            )
            # Migration douce : date avant laquelle les jetons émis sont invalides + persona métier.
            alter_kw = "ADD COLUMN IF NOT EXISTS" if self._pg_url else "ADD COLUMN"
            for col_sql in (
                f"ALTER TABLE user_accounts {alter_kw} tokens_valid_after INTEGER NOT NULL DEFAULT 0",
                f"ALTER TABLE user_accounts {alter_kw} persona TEXT NOT NULL DEFAULT 'analyste'",
            ):
                try:
                    if self._pg_url:
                        conn.execute("SAVEPOINT sp_auth_mig")
                    conn.execute(col_sql)
                    if self._pg_url:
                        conn.execute("RELEASE SAVEPOINT sp_auth_mig")
                except Exception:
                    if self._pg_url:
                        conn.execute("ROLLBACK TO SAVEPOINT sp_auth_mig")
                        conn.execute("RELEASE SAVEPOINT sp_auth_mig")
            if self._pg_url:
                _db.harden_tables(conn)

    @staticmethod
    def _public_user(row: Any) -> dict[str, Any]:
        d = dict(row)
        return {
            "user_id": d["user_id"],
            "email": d["email"],
            "display_name": d.get("display_name") or "",
            "persona": normalize_persona(d.get("persona")),
            "status": d.get("status") or "active",
            "created_at": d.get("created_at"),
            "last_login_at": d.get("last_login_at"),
        }

    def register(self, email: str, password: str, display_name: str = "", persona: str = "analyste") -> dict[str, Any]:
        norm_email = _normalize_email(email)
        if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
            raise ValueError("Le mot de passe doit contenir entre 8 et 128 caractères.")
        clean_name = (display_name or "").strip()[:80]
        clean_persona = normalize_persona(persona)
        user_id = f"u{uuid.uuid4().hex}"  # 33 car. -> compatible _STRONG_UID_RE
        salt_hex = secrets.token_hex(16)
        pw_hash = _hash_password(password, salt_hex)
        now = _utc_now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT user_id FROM user_accounts WHERE email = ?",
                (norm_email,),
            ).fetchone()
            if existing:
                raise FileExistsError("Un compte existe déjà avec cette adresse e-mail.")
            try:
                conn.execute(
                    """
                    INSERT INTO user_accounts (user_id, email, display_name, persona, password_hash, password_salt, status, created_at, last_login_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (user_id, norm_email, clean_name, clean_persona, pw_hash, salt_hex, now, now),
                )
            except Exception as exc:  # inscription simultanée : la contrainte UNIQUE(email) gagne -> 409, pas 500
                if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                    raise FileExistsError("Un compte existe déjà avec cette adresse e-mail.") from exc
                raise
            row = conn.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone()
        return self._public_user(row)

    def authenticate(self, email: str, password: str) -> dict[str, Any]:
        try:
            norm_email = _normalize_email(email)
        except ValueError as exc:
            raise PermissionError("Identifiants incorrects.") from exc
        if not isinstance(password, str) or not password:
            raise PermissionError("Identifiants incorrects.")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_accounts WHERE email = ?", (norm_email,)).fetchone()
            if not row:
                # Temps constant factice contre l'énumération d'e-mails
                _hash_password(password, "00" * 16)
                raise PermissionError("Identifiants incorrects.")
            expected = row["password_hash"]
            actual = _hash_password(password, row["password_salt"])
            if not hmac.compare_digest(expected, actual):
                raise PermissionError("Identifiants incorrects.")
            if row["status"] != "active":
                raise PermissionError("Compte suspendu ou désactivé. Contactez le support.")
            now = _utc_now_iso()
            conn.execute("UPDATE user_accounts SET last_login_at = ? WHERE user_id = ?", (now, row["user_id"]))
        user = self._public_user(row)
        user["last_login_at"] = now
        return user

    def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        clean = (user_id or "").strip().removeprefix("user:")
        if not clean:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_accounts WHERE user_id = ?", (clean,)).fetchone()
        return self._public_user(row) if row else None

    def set_account_status(self, user_id: str, status: str) -> bool:
        """Met à jour user_accounts.status ('active' | 'suspended') si le compte existe."""
        if status not in ("active", "suspended"):
            raise ValueError("Statut invalide (active | suspended).")
        clean = (user_id or "").strip().removeprefix("user:")
        if not clean:
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE user_accounts SET status = ? WHERE user_id = ?",
                (status, clean),
            )
            return (cur.rowcount or 0) > 0

    def list_accounts(self) -> list[dict[str, Any]]:
        """Retourne tous les comptes inscrits (sans hash/salt) pour la console d'administration."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM user_accounts ORDER BY created_at DESC").fetchall()
        return [self._public_user(r) for r in rows]

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: Optional[str] = None,
        persona: Optional[str] = None,
    ) -> dict[str, Any]:
        clean = (user_id or "").strip().removeprefix("user:")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_accounts WHERE user_id = ?", (clean,)).fetchone()
            if not row:
                raise KeyError("Compte introuvable.")
            next_name = (display_name or "").strip()[:80] if display_name is not None else (row["display_name"] or "")
            next_persona = normalize_persona(persona) if persona is not None else normalize_persona(dict(row).get("persona"))
            conn.execute(
                "UPDATE user_accounts SET display_name = ?, persona = ? WHERE user_id = ?",
                (next_name, next_persona, clean),
            )
            updated = conn.execute("SELECT * FROM user_accounts WHERE user_id = ?", (clean,)).fetchone()
        return self._public_user(updated)

    def change_password(self, user_id: str, *, current_password: str, new_password: str) -> dict[str, Any]:
        clean = (user_id or "").strip().removeprefix("user:")
        if not isinstance(new_password, str) or len(new_password) < 8 or len(new_password) > 128:
            raise ValueError("Le nouveau mot de passe doit contenir entre 8 et 128 caractères.")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_accounts WHERE user_id = ?", (clean,)).fetchone()
            if not row:
                raise KeyError("Compte introuvable.")
            actual = _hash_password(current_password or "", row["password_salt"])
            if not hmac.compare_digest(row["password_hash"], actual):
                raise PermissionError("Mot de passe actuel incorrect.")
            new_salt = secrets.token_hex(16)
            new_hash = _hash_password(new_password, new_salt)
            # Tous les jetons émis jusqu'ici deviennent invalides (session volée / ancien appareil).
            conn.execute(
                "UPDATE user_accounts SET password_hash = ?, password_salt = ?, tokens_valid_after = ? WHERE user_id = ?",
                (new_hash, new_salt, int(time.time()), clean),
            )
            updated = conn.execute("SELECT * FROM user_accounts WHERE user_id = ?", (clean,)).fetchone()
        return self._public_user(updated)

    def delete_account(self, user_id: str, *, password: str) -> bool:
        clean = (user_id or "").strip().removeprefix("user:")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_accounts WHERE user_id = ?", (clean,)).fetchone()
            if not row:
                raise KeyError("Compte introuvable.")
            actual = _hash_password(password or "", row["password_salt"])
            if not hmac.compare_digest(row["password_hash"], actual):
                raise PermissionError("Mot de passe incorrect.")
            conn.execute("DELETE FROM user_accounts WHERE user_id = ?", (clean,))
        return True

    def issue_session(
        self,
        user: dict[str, Any],
        *,
        secret: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
        original_iat: Optional[int] = None,
    ) -> dict[str, Any]:
        auth_secret = secret if secret is not None else get_auth_secret()
        token = issue_signed_user_token(
            user["user_id"], auth_secret, ttl_seconds=ttl_seconds, original_iat=original_iat
        )
        return {
            "token": token,
            "token_type": "bearer",
            "expires_in": ttl_seconds,
            "user": user,
        }

    def verify_session_token(self, token: str, *, secret: Optional[str] = None) -> Optional[str]:
        auth_secret = (secret if secret is not None else os.getenv("AUTH_SECRET", "")).strip()
        if not token or not auth_secret:
            return None
        sub = verify_signed_user_token(token, auth_secret)
        if not sub:
            return None
        if self.is_token_revoked(token):
            return None
        return sub

    def revoke_token(self, token: str, *, ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS) -> None:
        if not token:
            return
        revoke_user_token(token)
        now_ts = int(time.time())
        exp_ts = now_ts + max(60, int(ttl_seconds))
        digest = _token_digest(token)
        with self._connect() as conn:
            conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now_ts,))
            conn.execute(
                """
                INSERT INTO revoked_tokens (token_hash, expires_at, revoked_at)
                VALUES (?, ?, ?)
                ON CONFLICT (token_hash) DO NOTHING
                """,
                (digest, exp_ts, _utc_now_iso()),
            )

    def is_token_stale(self, token: str, user_id: str) -> bool:
        """True si le jeton a été émis avant le dernier changement de mot de passe du compte."""
        clean = (user_id or "").strip().removeprefix("user:")
        with self._connect() as conn:
            row = conn.execute("SELECT tokens_valid_after FROM user_accounts WHERE user_id = ?", (clean,)).fetchone()
        valid_after = int(row["tokens_valid_after"] or 0) if row else 0
        if valid_after <= 0:
            return False
        return int(token_claims(token).get("iat") or 0) < valid_after

    def session_age_seconds(self, token: str) -> int:
        """Âge de la session d'origine (connexion par mot de passe) ; 0 si le jeton ne porte pas `oiat`."""
        claims = token_claims(token)
        oiat = int(claims.get("oiat") or claims.get("iat") or 0)
        return max(0, int(time.time()) - oiat) if oiat else 0

    def is_token_revoked(self, token: str) -> bool:
        if not token:
            return True
        digest = _token_digest(token)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token_hash FROM revoked_tokens WHERE token_hash = ?",
                (digest,),
            ).fetchone()
        return row is not None

    def get_auth_check_state(self, token: str, user_id: str) -> dict[str, Any]:
        """Vérifie en une seule requête SQL : révocation, existence du compte, statut et `tokens_valid_after`."""
        if not token:
            return {"revoked": True, "exists": False, "status": None, "stale": False}
        clean = (user_id or "").strip().removeprefix("user:")
        digest = _token_digest(token)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    (SELECT 1 FROM revoked_tokens WHERE token_hash = ? LIMIT 1) AS is_revoked,
                    u.user_id AS found_user_id,
                    u.status AS user_status,
                    u.tokens_valid_after AS tokens_valid_after
                FROM (SELECT 1) AS _auth_probe
                LEFT JOIN user_accounts u ON u.user_id = ?
                """,
                (digest, clean),
            ).fetchone()
        if not row:
            return {"revoked": False, "exists": False, "status": None, "stale": False}
        revoked = row["is_revoked"] is not None
        exists = row["found_user_id"] is not None
        status = row["user_status"]
        valid_after = int(row["tokens_valid_after"] or 0) if exists else 0
        stale = bool(valid_after > 0 and int(token_claims(token).get("iat") or 0) < valid_after)
        return {
            "revoked": revoked,
            "exists": exists,
            "status": status,
            "stale": stale,
        }

