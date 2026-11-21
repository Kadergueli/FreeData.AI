"""Modular Machine Learning Engine (pure NumPy/Pandas): Ridge Regression, K-Means, Risk Classifier & ModelRegistry."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_lag_features(prices: np.ndarray, months: Optional[np.ndarray] = None) -> tuple[np.ndarray, np.ndarray]:
    """Builds strictly causal lag features (lag_1, lag_2, lag_3, ma_3, sin_m, cos_m) — zero future leakage."""
    n = len(prices)
    if n < 5:
        return np.empty((0, 6)), np.empty((0,))
    X_rows = []
    y_rows = []
    for t in range(3, n):
        lag1 = float(prices[t - 1])
        lag2 = float(prices[t - 2])
        lag3 = float(prices[t - 3])
        ma3 = (lag1 + lag2 + lag3) / 3.0
        m_num = int(months[t]) if months is not None else ((t % 12) + 1)
        sin_m = math.sin(2.0 * math.pi * m_num / 12.0)
        cos_m = math.cos(2.0 * math.pi * m_num / 12.0)
        X_rows.append([lag1, lag2, lag3, ma3, sin_m, cos_m])
        y_rows.append(float(prices[t]))
    return np.array(X_rows, dtype=float), np.array(y_rows, dtype=float)


class RidgePriceRegressor:
    """L2-regularized linear regression on causal price lags with chronological evaluation."""

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = float(alpha)
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0
        self.feat_mean: Optional[np.ndarray] = None
        self.feat_std: Optional[np.ndarray] = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "RidgePriceRegressor":
        self.feat_mean = X.mean(axis=0)
        self.feat_std = np.where(X.std(axis=0) > 1e-8, X.std(axis=0), 1.0)
        Xs = (X - self.feat_mean) / self.feat_std
        Xb = np.column_stack([np.ones(len(Xs)), Xs])
        reg = np.eye(Xb.shape[1]) * self.alpha
        reg[0, 0] = 0.0  # do not regularize intercept
        theta = np.linalg.pinv(Xb.T @ Xb + reg) @ (Xb.T @ y)
        self.bias = float(theta[0])
        self.weights = theta[1:]
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.weights is None or self.feat_mean is None or self.feat_std is None:
            raise RuntimeError("RidgePriceRegressor must be fitted before predict().")
        Xs = (X - self.feat_mean) / self.feat_std
        return self.bias + Xs @ self.weights

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": "RidgePriceRegressor",
            "alpha": self.alpha,
            "bias": self.bias,
            "weights": self.weights.tolist() if self.weights is not None else [],
            "feat_mean": self.feat_mean.tolist() if self.feat_mean is not None else [],
            "feat_std": self.feat_std.tolist() if self.feat_std is not None else [],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RidgePriceRegressor":
        m = cls(alpha=float(data.get("alpha", 1.0)))
        m.bias = float(data.get("bias", 0.0))
        m.weights = np.array(data["weights"], dtype=float)
        m.feat_mean = np.array(data["feat_mean"], dtype=float)
        m.feat_std = np.array(data["feat_std"], dtype=float)
        return m


def evaluate_ridge_chronological(
    prices: np.ndarray,
    *,
    alphas: tuple[float, ...] = (0.1, 1.0, 10.0),
    min_history: int = 8,
) -> dict[str, Any]:
    """Chronological train/test split comparing tuned Ridge Regression against Naive baseline."""
    if len(prices) < min_history:
        return {"status": "insufficient_history", "observations": int(len(prices)), "min_required": min_history}

    X, y = build_lag_features(prices)
    if len(X) < 5:
        return {"status": "insufficient_history", "observations": int(len(prices)), "min_required": min_history}

    split = max(3, int(len(X) * 0.7))
    X_tr, y_tr = X[:split], y[:split]
    X_te, y_te = X[split:], y[split:]

    best_model = None
    best_mae = float("inf")
    best_alpha = alphas[0]
    for a in alphas:
        cand = RidgePriceRegressor(alpha=a).fit(X_tr, y_tr)
        preds = cand.predict(X_te)
        mae = float(np.mean(np.abs(y_te - preds)))
        if mae < best_mae:
            best_mae = mae
            best_model = cand
            best_alpha = a

    ridge_preds = best_model.predict(X_te)
    ridge_rmse = float(np.sqrt(np.mean((y_te - ridge_preds) ** 2)))
    naive_preds = X_te[:, 0]  # lag_1
    naive_mae = float(np.mean(np.abs(y_te - naive_preds)))
    naive_rmse = float(np.sqrt(np.mean((y_te - naive_preds) ** 2)))

    return {
        "status": "evaluated",
        "best_alpha": best_alpha,
        "train_samples": int(len(X_tr)),
        "test_samples": int(len(X_te)),
        "ridge_mae_xaf_kg": round(best_mae, 2),
        "ridge_rmse_xaf_kg": round(ridge_rmse, 2),
        "naive_mae_xaf_kg": round(naive_mae, 2),
        "naive_rmse_xaf_kg": round(naive_rmse, 2),
        "beats_baseline": best_mae <= naive_mae,
        "model": best_model,
    }


class KMeansMarketClusterer:
    """Deterministic K-Means clustering for market segmentation by volatility and price level."""

    def __init__(self, k: int = 3, max_iter: int = 30, seed: int = 42) -> None:
        self.k = max(1, int(k))
        self.max_iter = max_iter
        self.seed = seed
        self.centroids: Optional[np.ndarray] = None
        self.feat_mean: Optional[np.ndarray] = None
        self.feat_std: Optional[np.ndarray] = None

    def fit_predict(self, df: pd.DataFrame, feature_cols: list[str]) -> dict[str, Any]:
        clean = df.dropna(subset=feature_cols).copy()
        if len(clean) < self.k:
            return {"status": "insufficient_data", "clusters": [], "inertia": None}

        X = clean[feature_cols].to_numpy(dtype=float)
        self.feat_mean = X.mean(axis=0)
        self.feat_std = np.where(X.std(axis=0) > 1e-8, X.std(axis=0), 1.0)
        Xs = (X - self.feat_mean) / self.feat_std

        rng = np.random.default_rng(self.seed)
        init_idx = rng.choice(len(Xs), size=self.k, replace=False)
        centroids = Xs[init_idx].copy()

        labels = np.zeros(len(Xs), dtype=int)
        for _ in range(self.max_iter):
            dists = np.linalg.norm(Xs[:, None, :] - centroids[None, :, :], axis=2)
            new_labels = np.argmin(dists, axis=1)
            if np.array_equal(new_labels, labels):
                break
            labels = new_labels
            for c in range(self.k):
                mask = labels == c
                if mask.any():
                    centroids[c] = Xs[mask].mean(axis=0)

        self.centroids = centroids
        inertia = float(sum(np.sum((Xs[i] - centroids[labels[i]]) ** 2) for i in range(len(Xs))))
        clean["cluster_id"] = labels.tolist()
        return {
            "status": "clustered",
            "k": self.k,
            "samples": int(len(clean)),
            "inertia": round(inertia, 3),
            "records": clean.to_dict(orient="records"),
        }


class RiskGradeClassifier:
    """L2-regularized Logistic Regression predicting high market risk (grade C/D) from CV% and drawdown."""

    def __init__(self, lr: float = 0.2, epochs: int = 300, l2: float = 0.05) -> None:
        self.lr = lr
        self.epochs = epochs
        self.l2 = l2
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0
        self.feat_mean: Optional[np.ndarray] = None
        self.feat_std: Optional[np.ndarray] = None

    @staticmethod
    def _sigmoid(z: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))

    def fit_and_evaluate(self, X: np.ndarray, y: np.ndarray) -> dict[str, Any]:
        if len(X) < 6 or len(np.unique(y)) < 2:
            return {"status": "insufficient_data"}
        self.feat_mean = X.mean(axis=0)
        self.feat_std = np.where(X.std(axis=0) > 1e-8, X.std(axis=0), 1.0)
        Xs = (X - self.feat_mean) / self.feat_std
        w = np.zeros(Xs.shape[1], dtype=float)
        b = 0.0
        n = float(len(Xs))
        for _ in range(self.epochs):
            p = self._sigmoid(b + Xs @ w)
            err = p - y
            w -= self.lr * ((Xs.T @ err) / n + self.l2 * w)
            b -= self.lr * float(np.mean(err))
        self.weights = w
        self.bias = b

        preds = (self._sigmoid(b + Xs @ w) >= 0.5).astype(int)
        tp = int(np.sum((preds == 1) & (y == 1)))
        fp = int(np.sum((preds == 1) & (y == 0)))
        fn = int(np.sum((preds == 0) & (y == 1)))
        tn = int(np.sum((preds == 0) & (y == 0)))
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        acc = (tp + tn) / max(1, len(y))
        return {
            "status": "evaluated",
            "samples": int(len(y)),
            "accuracy": round(acc, 3),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1_score": round(f1, 3),
        }


MODEL_LIFECYCLE_STATES: tuple[str, ...] = (
    "REGISTERED",
    "TRAINING",
    "TRAINED",
    "EVALUATION",
    "APPROVED",
    "DEPLOYED",
    "DEPRECATED",
    "ARCHIVED",
    "FAILED",
)


class ModelRegistry:
    """Centralized, versioned ML Model Registry with lifecycle states, dataset traceability,
    deterministic production selection, execution telemetry, and lazy on-disk artifact loading.
    """

    def __init__(
        self,
        models_dir: Optional[str] = None,
        max_loaded_models: int = 4,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
    ) -> None:
        from collections import OrderedDict
        import sqlite3
        import threading
        from src import db as _db

        self.models_dir = Path(models_dir or "data/models")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.models_dir / "registry_index.json"
        self._lock = threading.Lock()
        self._pg_url = _db.resolve_backend(
            db_path or (str(self.models_dir / "model_registry.db") if models_dir else None),
            database_url_override=database_url,
        )
        self._pg_schema = _db.DEFAULT_SCHEMA
        self._sqlite_path = Path(db_path) if db_path else (self.models_dir / "model_registry.db")
        self._sqlite3 = sqlite3
        self._init_durable_store()
        self._entries: dict[str, dict[str, Any]] = self._load_index()
        self.max_loaded_models = max(1, int(max_loaded_models))
        self._loaded_artifacts: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def _durable_connect(self):
        from contextlib import closing
        from src import db as _db

        if self._pg_url:
            return _db.pg_connect(self._pg_url, self._pg_schema)
        return closing(self._sqlite3.connect(str(self._sqlite_path)))

    def _init_durable_store(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS ml_model_registry (
            entry_key TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            metadata_json TEXT NOT NULL,
            artifact_json TEXT,
            updated_at TEXT NOT NULL
        );
        """
        with self._durable_connect() as conn:
            conn.executescript(ddl)

    def _entry_key(self, model_id: str, version: int) -> str:
        return f"{model_id}::v{int(version)}"

    def _load_index(self) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        # 1. Load from durable DB (survives Render redeployments / ephemeral disk wipes)
        try:
            with self._durable_connect() as conn:
                rows = conn.execute("SELECT entry_key, metadata_json FROM ml_model_registry").fetchall()
                for row in rows:
                    k = row[0]
                    meta = json.loads(row[1])
                    if isinstance(meta, dict):
                        entries[k] = meta
        except Exception:
            pass
        # 2. Merge any local index entries not yet in DB
        if self._index_path.is_file():
            try:
                raw = json.loads(self._index_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        entries.setdefault(k, v)
            except Exception:
                pass
        return entries

    def _persist_index(self) -> None:
        now = _utc_now()
        try:
            with self._durable_connect() as conn:
                for key, entry in self._entries.items():
                    meta_json = json.dumps(entry, ensure_ascii=False)
                    cur = conn.execute(
                        "UPDATE ml_model_registry SET metadata_json = ?, updated_at = ? WHERE entry_key = ?",
                        (meta_json, now, key),
                    )
                    if cur.rowcount == 0:
                        conn.execute(
                            "INSERT INTO ml_model_registry (entry_key, model_id, version, metadata_json, artifact_json, updated_at) "
                            "VALUES (?, ?, ?, ?, NULL, ?)",
                            (key, str(entry["model_id"]), int(entry["version"]), meta_json, now),
                        )
                if not self._pg_url:
                    conn.commit()
        except Exception:
            pass
        self._index_path.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _persist_artifact(self, model_id: str, version: int, meta_bundle: dict[str, Any]) -> None:
        key = self._entry_key(model_id, version)
        now = _utc_now()
        art_json = json.dumps(meta_bundle, ensure_ascii=False)
        entry_meta = json.dumps(self._entries.get(key, {"model_id": model_id, "version": int(version)}), ensure_ascii=False)
        with self._durable_connect() as conn:
            cur = conn.execute(
                "UPDATE ml_model_registry SET artifact_json = ?, updated_at = ? WHERE entry_key = ?",
                (art_json, now, key),
            )
            if cur.rowcount == 0:
                conn.execute(
                    "INSERT INTO ml_model_registry (entry_key, model_id, version, metadata_json, artifact_json, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (key, model_id, int(version), entry_meta, art_json, now),
                )
            if not self._pg_url:
                conn.commit()

    def _load_artifact_from_durable_store(self, model_id: str, version: int) -> Optional[dict[str, Any]]:
        key = self._entry_key(model_id, version)
        try:
            with self._durable_connect() as conn:
                row = conn.execute(
                    "SELECT artifact_json FROM ml_model_registry WHERE entry_key = ?",
                    (key,),
                ).fetchone()
                if row and row[0]:
                    return json.loads(row[0])
        except Exception:
            return None
        return None

    def register_model(
        self,
        *,
        model_id: str,
        model_name: str,
        domain: str,
        algorithm: str,
        task_type: str,
        version: int = 1,
        description: str = "",
        training_dataset_ref: Optional[str] = None,
        evaluation_dataset_ref: Optional[str] = None,
        dataset_provenance: Optional[dict[str, Any]] = None,
        training_date: Optional[str] = None,
        lifecycle_status: str = "REGISTERED",
        evaluation_metrics: Optional[dict[str, Any]] = None,
        configuration: Optional[dict[str, Any]] = None,
        dependencies: Optional[list[str]] = None,
        enabled: bool = True,
        set_active: bool = False,
    ) -> dict[str, Any]:
        status = lifecycle_status.strip().upper()
        if status not in MODEL_LIFECYCLE_STATES:
            raise ValueError(f"Statut de cycle de vie invalide : {lifecycle_status}")
        key = self._entry_key(model_id, version)
        deploy_status = "DEPLOYED" if (status == "DEPLOYED" and enabled) else (
            "DISABLED" if (status == "DEPLOYED" and not enabled) else "NOT_DEPLOYED"
        )
        entry = {
            "model_id": model_id,
            "name": model_id,  # backward-compatible alias
            "model_name": model_name,
            "domain": domain,
            "algorithm": algorithm,
            "task_type": task_type,
            "version": int(version),
            "description": description,
            "training_dataset_ref": training_dataset_ref,
            "evaluation_dataset_ref": evaluation_dataset_ref,
            "dataset_provenance": dataset_provenance or {},
            "training_date": training_date,
            "saved_at_utc": _utc_now(),
            "lifecycle_status": status,
            "deployment_status": deploy_status,
            "enabled": bool(enabled),
            "is_active_production": bool(set_active and status == "DEPLOYED" and enabled),
            "evaluation_metrics": dict(evaluation_metrics or {}),
            "metrics": dict(evaluation_metrics or {}),  # backward-compatible alias
            "configuration": dict(configuration or {}),
            "dependencies": list(dependencies or []),
            "last_execution_date": None,
            "execution_count": 0,
            "failure_count": 0,
            "total_inference_latency_ms": 0.0,
            "avg_inference_latency_ms": 0.0,
            "last_error": None,
        }
        with self._lock:
            if entry["is_active_production"]:
                for other in self._entries.values():
                    if other["model_id"] == model_id:
                        other["is_active_production"] = False
            self._entries[key] = entry
            self._persist_index()
        return self._public_view(entry)

    def transition_status(
        self,
        model_id: str,
        version: int,
        new_status: str,
        *,
        set_active: bool = False,
        enabled: Optional[bool] = None,
    ) -> dict[str, Any]:
        status = new_status.strip().upper()
        if status not in MODEL_LIFECYCLE_STATES:
            raise ValueError(f"Statut de cycle de vie invalide : {new_status}")
        key = self._entry_key(model_id, version)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise KeyError(f"Modèle introuvable : {model_id} v{version}")
            entry["lifecycle_status"] = status
            if enabled is not None:
                entry["enabled"] = bool(enabled)
            if status == "DEPLOYED" and entry["enabled"]:
                entry["deployment_status"] = "DEPLOYED"
                if set_active:
                    for other in self._entries.values():
                        if other["model_id"] == model_id:
                            other["is_active_production"] = False
                    entry["is_active_production"] = True
            elif status == "DEPLOYED" and not entry["enabled"]:
                entry["deployment_status"] = "DISABLED"
                entry["is_active_production"] = False
            else:
                entry["deployment_status"] = "STOPPED" if status in ("DEPRECATED", "ARCHIVED", "FAILED") else "NOT_DEPLOYED"
                entry["is_active_production"] = False
            self._persist_index()
            return self._public_view(entry)

    def select_model(
        self,
        *,
        domain: Optional[str] = None,
        task_type: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Deterministically selects an operational (DEPLOYED + enabled + active) model matching criteria."""
        with self._lock:
            candidates = [
                e for e in self._entries.values()
                if e.get("lifecycle_status") == "DEPLOYED"
                and e.get("enabled") is True
                and e.get("is_active_production") is True
                and (model_id is None or e.get("model_id") == model_id)
                and (domain is None or e.get("domain") == domain)
                and (task_type is None or e.get("task_type") == task_type)
            ]
        if not candidates:
            raise LookupError(
                f"Aucun modèle ML déployé et actif pour domain={domain}, task_type={task_type}, model_id={model_id}."
            )
        # Deterministic ordering: highest version, then lexical model_id
        candidates.sort(key=lambda e: (-int(e["version"]), str(e["model_id"])))
        return self._public_view(candidates[0])

    def record_execution(
        self,
        model_id: str,
        version: int,
        *,
        latency_ms: float,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        key = self._entry_key(model_id, version)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry["execution_count"] = int(entry.get("execution_count", 0)) + 1
            entry["total_inference_latency_ms"] = float(entry.get("total_inference_latency_ms", 0.0)) + max(0.0, float(latency_ms))
            entry["avg_inference_latency_ms"] = round(
                entry["total_inference_latency_ms"] / max(1, entry["execution_count"]), 2
            )
            entry["last_execution_date"] = _utc_now()
            if not success:
                entry["failure_count"] = int(entry.get("failure_count", 0)) + 1
                entry["last_error"] = (error or "Execution error")[:200]
            self._persist_index()

    def compare_versions(self, model_id: str) -> list[dict[str, Any]]:
        with self._lock:
            versions = [self._public_view(e) for e in self._entries.values() if e["model_id"] == model_id]
        if not versions:
            raise KeyError(f"Aucun modèle enregistré pour '{model_id}'.")
        versions.sort(key=lambda e: int(e["version"]))
        return versions

    def seed_builtin_models(self, *, data_ready: bool = False) -> None:
        """Registers FreeData.AI's core NumPy/Pandas ML models with honest lifecycle states and zero invented metrics."""
        builtins = [
            {
                "model_id": "ridge_price_regressor",
                "model_name": "Ridge Price Forecaster (Causal Lags + Seasonality)",
                "domain": "markets_and_prices",
                "algorithm": "RidgeRegression_L2",
                "task_type": "forecasting",
                "description": "Prévision causale des prix des produits au Tchad (XAF/kg) avec lags 1-3 mois, MA3 et harmoniques saisonnières.",
                "training_dataset_ref": "table_ml_forecasts",
                "evaluation_dataset_ref": "chronological_holdout_30pct",
                "dataset_provenance": {"source": "WFP/FEWSNET Chad Markets", "split": "chronological_70_30"},
                "configuration": {"alphas": [0.1, 1.0, 10.0], "min_history": 8},
                "dependencies": ["numpy", "pandas"],
            },
            {
                "model_id": "kmeans_market_clusterer",
                "model_name": "K-Means Market Volatility & Price Clusterer",
                "domain": "markets_and_prices",
                "algorithm": "KMeans_Deterministic",
                "task_type": "clustering",
                "description": "Segmentation déterministe des marchés tchadiens par niveau de prix et volatilité (CV%).",
                "training_dataset_ref": "table_ml_forecasts",
                "evaluation_dataset_ref": "inertia_silhouette_internal",
                "dataset_provenance": {"source": "WFP/FEWSNET Chad Markets", "seed": 42},
                "configuration": {"k": 3, "max_iter": 30, "seed": 42},
                "dependencies": ["numpy", "pandas"],
            },
            {
                "model_id": "risk_grade_classifier",
                "model_name": "Logistic Risk Grade Classifier (Credit Passport)",
                "domain": "economy",
                "algorithm": "LogisticRegression_L2",
                "task_type": "classification",
                "description": "Classification du risque marché au Tchad (grades C/D) à partir de la volatilité (CV%) et du drawdown.",
                "training_dataset_ref": "table_ml_credit_passport",
                "evaluation_dataset_ref": "credit_passport_validation",
                "dataset_provenance": {"source": "FreeData.AI Credit Passport Gold"},
                "configuration": {"lr": 0.2, "epochs": 300, "l2": 0.05},
                "dependencies": ["numpy", "pandas"],
            },
        ]
        for spec in builtins:
            key = self._entry_key(spec["model_id"], 1)
            if key not in self._entries:
                self.register_model(
                    **spec,
                    version=1,
                    lifecycle_status="DEPLOYED" if data_ready else "REGISTERED",
                    set_active=bool(data_ready),
                )

    @staticmethod
    def _public_view(entry: dict[str, Any]) -> dict[str, Any]:
        # Strip internal accumulator; never expose raw artifact weights or filesystem paths
        out = dict(entry)
        out.pop("total_inference_latency_ms", None)
        out.pop("artifact", None)
        out.pop("path", None)
        return out

    def save_model(
        self,
        name: str,
        model_payload: dict[str, Any],
        metrics: dict[str, Any],
        *,
        domain: str = "markets_and_prices",
        algorithm: str = "custom",
        task_type: str = "regression",
        training_dataset_ref: Optional[str] = None,
        lifecycle_status: str = "TRAINED",
    ) -> dict[str, Any]:
        existing = sorted(self.models_dir.glob(f"{name}_v*.json"))
        next_v = len(existing) + 1
        now = _utc_now()
        meta = {
            "name": name,
            "version": next_v,
            "saved_at_utc": now,
            "metrics": metrics,
            "artifact": model_payload,
        }
        path = self.models_dir / f"{name}_v{next_v}.json"
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self.register_model(
            model_id=name,
            model_name=name,
            domain=domain,
            algorithm=model_payload.get("model_type") or algorithm,
            task_type=task_type,
            version=next_v,
            training_dataset_ref=training_dataset_ref,
            training_date=now,
            lifecycle_status=lifecycle_status,
            evaluation_metrics=metrics,
        )
        self._persist_artifact(name, next_v, meta)
        return {"name": name, "version": next_v, "path": str(path), "metrics": metrics}

    def load_latest(self, name: str) -> dict[str, Any]:
        existing = sorted(self.models_dir.glob(f"{name}_v*.json"))
        if existing:
            latest_path = existing[-1]
            data = json.loads(latest_path.read_text(encoding="utf-8"))
            version = int(data.get("version", 1))
            self._cache_loaded(name, version, data)
            return data
        # Fallback to durable DB when local disk is ephemeral/empty (e.g. fresh Render container)
        versions = sorted(
            int(e["version"]) for e in self._entries.values() if e.get("model_id") == name
        )
        for v in reversed(versions):
            db_data = self._load_artifact_from_durable_store(name, v)
            if db_data is not None:
                self._cache_loaded(name, v, db_data)
                return db_data
        raise KeyError(f"Aucun modèle enregistré pour '{name}'.")

    def load_version(self, model_id: str, version: int) -> dict[str, Any]:
        """Lazy-loads a specific model artifact from LRU cache, local disk, or durable DB."""
        key = self._entry_key(model_id, version)
        with self._lock:
            if key in self._loaded_artifacts:
                self._loaded_artifacts.move_to_end(key)
                return self._loaded_artifacts[key]
        path = self.models_dir / f"{model_id}_v{int(version)}.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            self._cache_loaded(model_id, version, data)
            return data
        db_data = self._load_artifact_from_durable_store(model_id, version)
        if db_data is not None:
            self._cache_loaded(model_id, version, db_data)
            return db_data
        raise FileNotFoundError(f"Artefact introuvable pour '{model_id}' v{version}.")

    def _cache_loaded(self, model_id: str, version: int, data: dict[str, Any]) -> None:
        key = self._entry_key(model_id, version)
        with self._lock:
            self._loaded_artifacts[key] = data
            self._loaded_artifacts.move_to_end(key)
            while len(self._loaded_artifacts) > self.max_loaded_models:
                self._loaded_artifacts.popitem(last=False)

    def unload_model(self, model_id: str, version: int) -> bool:
        key = self._entry_key(model_id, version)
        with self._lock:
            return self._loaded_artifacts.pop(key, None) is not None

    def loaded_models(self) -> list[dict[str, Any]]:
        with self._lock:
            out = []
            for key in self._loaded_artifacts.keys():
                mid, _, vpart = key.partition("::v")
                out.append({"model_id": mid, "version": int(vpart) if vpart.isdigit() else 1})
            return out

    def rollback_model(self, model_id: str, target_version: int) -> dict[str, Any]:
        """Safely rolls back production to a prior registered/approved/deployed version and deprecates the faulty active version."""
        target_key = self._entry_key(model_id, target_version)
        with self._lock:
            target = self._entries.get(target_key)
            if target is None:
                raise KeyError(f"Version cible introuvable : {model_id} v{target_version}")
            if target.get("lifecycle_status") in ("FAILED", "ARCHIVED"):
                raise ValueError(f"Impossible de restaurer une version en statut '{target.get('lifecycle_status')}'.")
            for key, entry in self._entries.items():
                if entry["model_id"] == model_id and key != target_key and entry.get("is_active_production"):
                    entry["is_active_production"] = False
                    entry["lifecycle_status"] = "DEPRECATED"
                    entry["deployment_status"] = "STOPPED"
                    self._loaded_artifacts.pop(key, None)
            target["lifecycle_status"] = "DEPLOYED"
            target["deployment_status"] = "DEPLOYED"
            target["enabled"] = True
            target["is_active_production"] = True
            self._persist_index()
            return self._public_view(target)

    def list_models(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        with self._lock:
            for key in sorted(self._entries.keys()):
                seen_keys.add(key)
                out.append(self._public_view(self._entries[key]))
        # Also include any legacy disk-only artifacts not yet indexed
        for p in sorted(self.models_dir.glob("*_v*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            k = self._entry_key(str(data.get("name")), int(data.get("version", 1)))
            if k not in seen_keys:
                out.append({
                    "model_id": data.get("name"),
                    "name": data.get("name"),
                    "version": data.get("version"),
                    "saved_at_utc": data.get("saved_at_utc"),
                    "lifecycle_status": "TRAINED",
                    "deployment_status": "NOT_DEPLOYED",
                    "metrics": data.get("metrics"),
                    "evaluation_metrics": data.get("metrics"),
                })
        return out

    def summary(self) -> dict[str, Any]:
        models = self.list_models()
        by_domain: dict[str, int] = {}
        by_algorithm: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_deployment: dict[str, int] = {}
        total_exec = 0
        total_fail = 0
        last_exec: Optional[str] = None
        for m in models:
            dom = str(m.get("domain") or "unknown")
            alg = str(m.get("algorithm") or "unknown")
            st = str(m.get("lifecycle_status") or "REGISTERED")
            dep = str(m.get("deployment_status") or "NOT_DEPLOYED")
            by_domain[dom] = by_domain.get(dom, 0) + 1
            by_algorithm[alg] = by_algorithm.get(alg, 0) + 1
            by_status[st] = by_status.get(st, 0) + 1
            by_deployment[dep] = by_deployment.get(dep, 0) + 1
            total_exec += int(m.get("execution_count") or 0)
            total_fail += int(m.get("failure_count") or 0)
            le = m.get("last_execution_date")
            if le and (last_exec is None or str(le) > last_exec):
                last_exec = str(le)
        stored_artifacts = len(list(self.models_dir.glob("*_v*.json")))
        durable_artifacts = 0
        try:
            with self._durable_connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM ml_model_registry WHERE artifact_json IS NOT NULL").fetchone()
                durable_artifacts = int(row[0]) if row else 0
        except Exception:
            durable_artifacts = 0
        loaded = self.loaded_models()
        return {
            "persistence_backend": "supabase_postgresql" if self._pg_url else "local_sqlite",
            "total_registered_models": len(models),
            "stored_artifacts_count": max(stored_artifacts, durable_artifacts),
            "durable_artifacts_count": durable_artifacts,
            "currently_loaded_models": loaded,
            "loaded_count": len(loaded),
            "max_loaded_models": self.max_loaded_models,
            "by_domain": by_domain,
            "by_algorithm": by_algorithm,
            "by_lifecycle_status": by_status,
            "by_deployment_status": by_deployment,
            "total_executions": total_exec,
            "total_failures": total_fail,
            "failure_rate": round(total_fail / max(1, total_exec), 4) if total_exec > 0 else 0.0,
            "last_execution_date": last_exec,
        }

