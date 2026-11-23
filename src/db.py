"""Accès base de données : SQLite (par défaut) ou PostgreSQL/Supabase quand SUPABASE_DB_URL est défini.

Les stores (projets, abonnements, support, admin) écrivent du SQL « portable » avec des `?` et des
`sqlite3.Row`. Ce module fournit, pour Postgres, une connexion qui imite ce contrat :

- `?` → `%s` (le `%` littéral est échappé) ;
- lignes accessibles par nom, par index et via `dict(row)` ;
- `executescript()` (types SQLite traduits : REAL → DOUBLE PRECISION) ;
- `BEGIN IMMEDIATE` → verrou consultatif transactionnel (même sémantique : un seul écrivain à la fois) ;
- `with conn:` = COMMIT si succès, ROLLBACK sinon, puis retour de la connexion au pool.

Les tables vivent dans un schéma privé (`freedata_app` par défaut), non exposé par l'API REST de Supabase,
avec RLS activée et sans aucun droit pour `anon` / `authenticated`.
"""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Iterable, Optional

DEFAULT_SCHEMA = "freedata_app"
_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

_POOLS: dict[tuple[str, str], Any] = {}
_POOLS_LOCK = threading.Lock()
_BOOTSTRAPPED: set[tuple[str, str]] = set()
_SEARCH_PATH_READY: set[tuple[int, str]] = set()


def database_url() -> str:
    url = os.getenv("SUPABASE_DB_URL", "").strip()
    # SQLAlchemy accepte « postgresql+psycopg2:// » ; psycopg2 seul exige « postgresql:// ».
    return re.sub(r"^(postgres(?:ql)?)\+\w+://", r"\1://", url)


def _pytest_all_pg() -> bool:
    # Crochet de test uniquement (pytest positionne PYTEST_CURRENT_TEST) : fait tourner toute la suite sur Postgres,
    # avec un schéma neuf par instance de store. Ignoré en production.
    return bool(os.getenv("FREEDATA_TEST_ALL_PG")) and bool(os.getenv("PYTEST_CURRENT_TEST")) and bool(database_url())


def resolve_backend(explicit_path: Optional[str], *, database_url_override: Optional[str] = None) -> Optional[str]:
    """Retourne l'URL Postgres à utiliser, ou None pour SQLite.

    Un chemin SQLite passé explicitement (tests, scripts) reste toujours SQLite.
    """
    url = (database_url_override or "").strip() or database_url()
    if not url:
        return None
    if explicit_path and not _pytest_all_pg():
        return None
    return url


def new_test_schema(db_path: Optional[str] = None) -> str:
    """Schéma de test déterministe par chemin (un « redémarrage » de store retrouve ses données)."""
    import hashlib

    return "t_" + hashlib.sha1(str(db_path).encode()).hexdigest()[:12]


def validate_schema(schema: str) -> str:
    if not _SCHEMA_RE.match(schema):
        raise ValueError(f"Nom de schéma invalide : {schema!r}")
    return schema


def _translate(sql: str) -> str:
    return sql.replace("%", "%%").replace("?", "%s")


def _translate_ddl(script: str) -> str:
    out = re.sub(r"\bREAL\b", "DOUBLE PRECISION", script)
    out = re.sub(r"\bBLOB\b", "BYTEA", out)
    return out.replace("%", "%%")


class PgRow:
    """Ligne compatible `sqlite3.Row` : row["col"], row[0], dict(row), row.keys()."""

    __slots__ = ("_values", "_index")

    def __init__(self, values: tuple, index: dict[str, int]) -> None:
        self._values = values
        self._index = index

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._values[self._index[key]]

    def keys(self) -> list[str]:
        return list(self._index)

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:  # pragma: no cover
        return f"PgRow({dict(zip(self._index, self._values))!r})"


class PgCursor:
    def __init__(self, cur: Any) -> None:
        self._cur = cur
        desc = cur.description
        self._index = {d[0]: i for i, d in enumerate(desc)} if desc else {}

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    def fetchone(self) -> Optional[PgRow]:
        r = self._cur.fetchone()
        return PgRow(r, self._index) if r is not None else None

    def fetchall(self) -> list[PgRow]:
        return [PgRow(r, self._index) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


def _get_pool(url: str, schema: str):
    import psycopg2.extensions
    from psycopg2.pool import ThreadedConnectionPool

    key = (url, schema)
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            # NUMERIC (ex. AVG) → float, comme SQLite.
            psycopg2.extensions.register_type(
                psycopg2.extensions.new_type(
                    psycopg2.extensions.DECIMAL.values, "DEC2FLOAT", lambda v, c: float(v) if v is not None else None
                )
            )
            maxconn = max(2, int(os.getenv("DB_POOL_MAX", "8")))
            pool = ThreadedConnectionPool(
                1, maxconn, dsn=url, connect_timeout=10
            )
            _POOLS[key] = pool
        return pool


def _pool_acquire_timeout() -> float:
    try:
        return max(0.0, float(os.getenv("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", "5")))
    except (TypeError, ValueError):
        return 5.0


def _acquire_pool_connection(pool: Any) -> Any:
    """Attend brièvement une connexion libre au lieu d'échouer immédiatement à saturation du pool."""
    from psycopg2.pool import PoolError

    timeout = _pool_acquire_timeout()
    poll_interval = 0.05
    deadline = time.monotonic() + timeout
    while True:
        try:
            return pool.getconn()
        except PoolError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Pool PostgreSQL saturé : aucune connexion libre après {timeout:.1f}s."
                ) from exc
            time.sleep(min(poll_interval, remaining))


class PgConnection:
    def __init__(self, url: str, schema: str) -> None:
        validate_schema(schema)
        self._pool = _get_pool(url, schema)
        self._conn = _acquire_pool_connection(self._pool)
        self._released = False
        try:
            self._conn.autocommit = False
            # PgBouncer Transaction Pooler (port 6543) réinitialise search_path entre transactions.
            # En mode Direct / Session Pooler (port 5432), search_path persiste sur la session physique
            # identifiée par backend_pid (lu localement en C par libpq sans aller-retour réseau).
            is_tx_pooler = ":6543" in url
            backend_pid = getattr(getattr(self._conn, "info", None), "backend_pid", None) or id(self._conn)
            conn_key = (int(backend_pid), schema)
            with _POOLS_LOCK:
                needs_sp = is_tx_pooler or conn_key not in _SEARCH_PATH_READY or getattr(self._conn, "closed", 0) != 0
            if needs_sp:
                with self._conn.cursor() as cur:
                    cur.execute(f'SET search_path TO "{schema}", public')
                self._conn.commit()
                if not is_tx_pooler:
                    with _POOLS_LOCK:
                        _SEARCH_PATH_READY.add(conn_key)
        except Exception:
            # Une erreur d'initialisation ne doit pas immobiliser une connexion du pool.
            self._released = True
            self._pool.putconn(self._conn, close=True)
            raise

    # --- API compatible sqlite3 -------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> PgCursor:
        norm = sql.strip().rstrip(";").strip().upper()
        if norm in ("BEGIN", "BEGIN IMMEDIATE", "BEGIN EXCLUSIVE"):
            # Écrivain unique, comme BEGIN IMMEDIATE ; le verrou est libéré au COMMIT/ROLLBACK.
            cur = self._conn.cursor()
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()))")
            return PgCursor(cur)
        if norm == "COMMIT":
            self._conn.commit()
            return PgCursor(self._conn.cursor())
        if norm == "ROLLBACK":
            self._conn.rollback()
            return PgCursor(self._conn.cursor())
        cur = self._conn.cursor()
        cur.execute(_translate(sql), tuple(params))
        return PgCursor(cur)

    def executescript(self, script: str) -> None:
        cur = self._conn.cursor()
        cur.execute(_translate_ddl(script))
        self._conn.commit()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._release()

    def _release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            if getattr(self._conn, "closed", 0) == 0 and getattr(self._conn, "status", 0) != 1:
                self._conn.rollback()
        finally:
            self._pool.putconn(self._conn, close=bool(getattr(self._conn, "closed", 0)))

    def __enter__(self) -> "PgConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if getattr(self._conn, "closed", 0) == 0 and getattr(self._conn, "status", 0) != 1:
                if exc_type is None:
                    self._conn.commit()
                else:
                    self._conn.rollback()
        finally:
            self._release()


def _bootstrap_schema(url: str, schema: str) -> None:
    """Crée le schéma privé et retire tout droit à anon / authenticated (rôles Supabase, s'ils existent)."""
    key = (url, schema)
    if key in _BOOTSTRAPPED:
        return
    validate_schema(schema)
    import psycopg2

    conn = psycopg2.connect(url, connect_timeout=10)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            cur.execute(
                f"""
                DO $$
                DECLARE r text;
                BEGIN
                  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                      EXECUTE format('REVOKE ALL ON SCHEMA "{schema}" FROM %I', r);
                      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" REVOKE ALL ON TABLES FROM %I', r);
                    END IF;
                  END LOOP;
                END $$;
                """
            )
    finally:
        conn.close()
    _BOOTSTRAPPED.add(key)


_HARDEN_LOCK = threading.Lock()


def harden_tables(conn: PgConnection) -> None:
    """Active la RLS (sans politique : personne sauf le rôle propriétaire) et retire les droits publics.

    Sérialisé par verrou consultatif + ordre déterministe + filtre `rowsecurity = false` afin
    d'éviter tout deadlock `AccessExclusiveLock` lors des initialisations concurrentes au démarrage.
    """
    with _HARDEN_LOCK:
        cur = conn._conn.cursor()
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext('harden_' || current_schema()))"
        )
        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = current_schema() AND rowsecurity = false "
            "ORDER BY tablename"
        )
        names = [r[0] for r in cur.fetchall()]
        for name in names:
            cur.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
            cur.execute(
                f"""
                DO $$
                DECLARE r text;
                BEGIN
                  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                      EXECUTE format('REVOKE ALL ON TABLE "{name}" FROM %I', r);
                    END IF;
                  END LOOP;
                END $$;
                """
            )
        conn._conn.commit()


def pg_connect(url: str, schema: str) -> PgConnection:
    _bootstrap_schema(url, schema)
    return PgConnection(url, schema)
