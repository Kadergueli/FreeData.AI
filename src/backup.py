"""Online SQLite hot-backup and integrity verification utilities."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def backup_sqlite_file(src_path: Path, dst_dir: Path) -> dict[str, Any]:
    if not src_path.is_file():
        return {"source": str(src_path), "status": "skipped_missing"}
    dst_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst_path = dst_dir / f"{src_path.stem}_{ts}{src_path.suffix}"
    with sqlite3.connect(str(src_path)) as src_conn, sqlite3.connect(str(dst_path)) as dst_conn:
        src_conn.backup(dst_conn)
    ok = verify_sqlite_integrity(dst_path)
    return {
        "source": str(src_path),
        "backup_path": str(dst_path),
        "size_bytes": dst_path.stat().st_size,
        "integrity_ok": ok,
        "status": "verified" if ok else "corrupted",
    }


def verify_sqlite_integrity(db_path: Path) -> bool:
    if not db_path.is_file():
        return False
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute("PRAGMA integrity_check;").fetchone()
        return bool(row and row[0] == "ok")


def backup_all_databases(db_paths: list[Path], backup_root: Path) -> list[dict[str, Any]]:
    return [backup_sqlite_file(p, backup_root) for p in db_paths]

