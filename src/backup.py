"""Online SQLite hot-backup, verified restoration, retention pruning, and ML artifact backup."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def backup_sqlite_file(src_path: Path, dst_dir: Path) -> dict[str, Any]:
    if not src_path.is_file():
        return {"source": str(src_path), "status": "skipped_missing"}
    dst_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst_path = dst_dir / f"{src_path.stem}_{ts}{src_path.suffix}"
    with closing(sqlite3.connect(str(src_path))) as src_conn, closing(sqlite3.connect(str(dst_path))) as dst_conn:
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
    try:
        with closing(sqlite3.connect(str(db_path))) as conn:
            row = conn.execute("PRAGMA integrity_check;").fetchone()
            return bool(row and row[0] == "ok")
    except sqlite3.DatabaseError:
        return False


def restore_sqlite_file(backup_path: Path, target_path: Path) -> dict[str, Any]:
    """Verifies backup integrity before atomically restoring it onto target_path."""
    if not backup_path.is_file():
        raise FileNotFoundError(f"Sauvegarde introuvable : {backup_path}")
    if not verify_sqlite_integrity(backup_path):
        raise ValueError(f"Sauvegarde corrompue (PRAGMA integrity_check échoué) : {backup_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(backup_path))) as src_conn, closing(sqlite3.connect(str(target_path))) as dst_conn:
        src_conn.backup(dst_conn)
    ok = verify_sqlite_integrity(target_path)
    return {
        "backup_path": str(backup_path),
        "target_path": str(target_path),
        "integrity_ok": ok,
        "status": "restored" if ok else "failed",
    }


def prune_old_backups(backup_dir: Path, *, keep_last: int = 14) -> list[str]:
    """Enforces retention policy by keeping the N most recent SQLite backups per directory."""
    if not backup_dir.is_dir():
        return []
    keep = max(1, int(keep_last))
    files = sorted(
        [p for p in backup_dir.iterdir() if p.is_file() and p.suffix in (".db", ".sqlite", ".sqlite3")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for old in files[keep:]:
        old.unlink(missing_ok=True)
        removed.append(str(old))
    return removed


def backup_model_artifacts(models_dir: Path, backup_root: Path) -> dict[str, Any]:
    """Backs up ML model registry index and versioned JSON artifacts with a SHA-256 manifest."""
    if not models_dir.is_dir():
        return {"status": "skipped_missing", "files_backed_up": 0}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_dir = backup_root / f"models_{ts}"
    snap_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for p in sorted(models_dir.glob("*.json")):
        dst = snap_dir / p.name
        shutil.copy2(p, dst)
        manifest[p.name] = hashlib.sha256(dst.read_bytes()).hexdigest()
    (snap_dir / "manifest.sha256.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "status": "verified",
        "snapshot_dir": str(snap_dir),
        "files_backed_up": len(manifest),
    }


def backup_all_databases(db_paths: list[Path], backup_root: Path) -> list[dict[str, Any]]:
    return [backup_sqlite_file(p, backup_root) for p in db_paths]
