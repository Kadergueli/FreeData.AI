"""Alertes de marché étendues (PRO) : seuil, variation %, écart à la médiane, nouvelles données.

Évaluation à la lecture (pas d'envoi externe : le fil d'alertes est consulté dans l'application).
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src import db as _db
from src.market_intel import (
    PRODUCTS, _national, _product_frame, _wide, _like_for_like, market_comparison, normalize_product,
)
from src.market_pro import _utc_now_iso

KINDS = ("threshold", "variation", "gap", "new_data")
MAX_RULES_PER_OWNER = 50


class MarketAlertStore:
    def __init__(self, db_path: Optional[str] = None, *, database_url: Optional[str] = None,
                 schema: Optional[str] = None) -> None:
        self._pg_url = _db.resolve_backend(db_path, database_url_override=database_url)
        self._pg_schema = (
            _db.validate_schema(schema) if schema
            else (_db.new_test_schema(db_path) if (self._pg_url and db_path) else _db.DEFAULT_SCHEMA)
        )
        self.db_path = Path(db_path or os.getenv("FREEDATA_BILLING_DB_PATH", "data/freedata_billing.db"))
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
                CREATE TABLE IF NOT EXISTS market_alert_rules (
                    rule_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    province TEXT NOT NULL DEFAULT '',
                    market_name TEXT NOT NULL DEFAULT '',
                    direction TEXT NOT NULL DEFAULT 'above',
                    value REAL NOT NULL DEFAULT 0,
                    last_seen_month TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_market_alert_owner
                    ON market_alert_rules(owner_id, created_at DESC);
                """
            )
            if self._pg_url:
                _db.harden_tables(conn)

    def create_rule(self, owner_id: str, *, kind: str, product_id: str, value: float = 0.0,
                    direction: str = "above", province: str = "", market_name: str = "",
                    note: str = "") -> dict[str, Any]:
        kind = (kind or "").strip().lower()
        if kind not in KINDS:
            raise ValueError(f"Type d'alerte invalide ({', '.join(KINDS)}).")
        pid = normalize_product(product_id)
        direction = (direction or "above").strip().lower()
        allowed = ("above", "below") if kind in ("threshold", "gap") else ("up", "down", "any")
        if kind == "new_data":
            direction = "any"
        if direction not in allowed:
            raise ValueError(f"Direction invalide pour ce type d'alerte ({', '.join(allowed)}).")
        value = float(value)
        if kind != "new_data" and not (value > 0 and value < 1e7):
            raise ValueError("La valeur de l'alerte doit être strictement positive.")
        if kind in ("variation", "gap") and value > 500:
            raise ValueError("Un pourcentage d'alerte doit rester inférieur ou égal à 500.")
        if kind == "gap" and not market_name.strip():
            raise ValueError("Une alerte d'écart à la médiane exige un marché.")
        if len(self.list_rules(owner_id)) >= MAX_RULES_PER_OWNER:
            raise ValueError(f"Maximum {MAX_RULES_PER_OWNER} alertes par compte.")
        rid = f"A-{uuid.uuid4().hex[:10].upper()}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO market_alert_rules (rule_id, owner_id, kind, product_id, province, market_name, "
                "direction, value, last_seen_month, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rid, owner_id, kind, pid, province.strip()[:80], market_name.strip()[:80], direction,
                 value, "", note.strip()[:240], _utc_now_iso()),
            )
            row = conn.execute("SELECT * FROM market_alert_rules WHERE rule_id = ? AND owner_id = ?",
                               (rid, owner_id)).fetchone()
        return dict(row)

    def list_rules(self, owner_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_alert_rules WHERE owner_id = ? ORDER BY created_at DESC LIMIT 100",
                (owner_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_rule(self, owner_id: str, rule_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM market_alert_rules WHERE rule_id = ? AND owner_id = ?",
                               (rule_id, owner_id))
        return (cur.rowcount or 0) > 0

    def ack_rule(self, owner_id: str, rule_id: str, month: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE market_alert_rules SET last_seen_month = ? WHERE rule_id = ? AND owner_id = ?",
                (month, rule_id, owner_id))
        return (cur.rowcount or 0) > 0

    def purge_owner(self, owner_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM market_alert_rules WHERE owner_id = ?", (owner_id,))
        return int(cur.rowcount or 0)


def evaluate_rules(rules: list[dict[str, Any]], df: Optional[pd.DataFrame]) -> list[dict[str, Any]]:
    """Ajoute à chaque règle : `triggered`, `message`, `as_of`, `current`. Ne lève jamais pour une donnée manquante."""
    cache: dict[str, Any] = {}

    def _state(pid: str) -> dict[str, Any]:
        if pid not in cache:
            wide = _wide(_product_frame(df, pid))
            nat = _national(wide).dropna()
            if nat.empty:
                cache[pid] = {}
            else:
                last = nat.index[-1]
                w = wide.loc[:last]
                cache[pid] = {"last": str(last), "median": float(nat.iloc[-1]), "wide": w,
                              "mom": _like_for_like(w, 1)}
        return cache[pid]

    out = []
    for r in rules:
        item = dict(r)
        label = PRODUCTS.get(r["product_id"], {}).get("label_fr", r["product_id"])
        item.update(label_fr=label, triggered=False, message="Données indisponibles.", as_of=None, current=None)
        st = _state(r["product_id"]) if r["product_id"] in PRODUCTS else {}
        if not st:
            out.append(item)
            continue
        item["as_of"] = st["last"]
        kind, thr = r["kind"], float(r["value"])
        if kind == "threshold":
            w = st["wide"]
            cols = [c for c in w.columns
                    if (not r["province"] or c[0].lower() == r["province"].lower())
                    and (not r["market_name"] or c[1].lower() == r["market_name"].lower())]
            vals = [float(w[c].dropna().iloc[-1]) for c in cols if w[c].tail(2).notna().any()]
            cur = (sum(vals) / len(vals)) if (vals and (r["province"] or r["market_name"])) else st["median"]
            item["current"] = round(cur, 1)
            item["triggered"] = cur >= thr if r["direction"] == "above" else cur <= thr
            item["message"] = (f"{label} : {cur:.0f} XAF/kg "
                               f"({'≥' if r['direction'] == 'above' else '≤'} {thr:.0f}).") if item["triggered"] \
                else f"{label} : {cur:.0f} XAF/kg, seuil {thr:.0f} non atteint."
        elif kind == "variation":
            mom = st["mom"]
            item["current"] = None if mom is None else round(mom, 1)
            ok = mom is not None and (
                (r["direction"] == "up" and mom >= thr) or (r["direction"] == "down" and mom <= -thr)
                or (r["direction"] == "any" and abs(mom) >= thr))
            item["triggered"] = bool(ok)
            item["message"] = (f"{label} : variation mensuelle {mom:+.1f} % (seuil {thr:.0f} %)."
                               if mom is not None else "Variation mensuelle indisponible.")
        elif kind == "gap":
            comp = market_comparison(df, r["product_id"])
            row = next((m for m in comp.get("markets", [])
                        if m["market"].lower() == r["market_name"].lower()
                        and (not r["province"] or m["province"].lower() == r["province"].lower())), None)
            if row is None:
                item["message"] = "Marché non observé récemment."
            else:
                gap = row["gap_vs_median_pct"]
                item["current"] = gap
                item["triggered"] = gap >= thr if r["direction"] == "above" else gap <= -thr
                item["message"] = f"{label} à {row['market']} : {gap:+.1f} % vs médiane nationale."
        elif kind == "new_data":
            item["current"] = st["last"]
            item["triggered"] = st["last"] > (r.get("last_seen_month") or "")
            item["message"] = (f"Nouveau mois disponible pour {label} : {st['last']}." if item["triggered"]
                               else f"Pas de nouvelle donnée pour {label} depuis {st['last']}.")
        out.append(item)
    return out
