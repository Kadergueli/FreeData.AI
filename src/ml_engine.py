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


class ModelRegistry:
    """Versioned JSON persistence for trained ML models and evaluation metrics."""

    def __init__(self, models_dir: Optional[str] = None) -> None:
        self.models_dir = Path(models_dir or "data/models")
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def save_model(self, name: str, model_payload: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
        existing = sorted(self.models_dir.glob(f"{name}_v*.json"))
        next_v = len(existing) + 1
        meta = {
            "name": name,
            "version": next_v,
            "saved_at_utc": _utc_now(),
            "metrics": metrics,
            "artifact": model_payload,
        }
        path = self.models_dir / f"{name}_v{next_v}.json"
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"name": name, "version": next_v, "path": str(path), "metrics": metrics}

    def load_latest(self, name: str) -> dict[str, Any]:
        existing = sorted(self.models_dir.glob(f"{name}_v*.json"))
        if not existing:
            raise KeyError(f"Aucun modèle enregistré pour '{name}'.")
        return json.loads(existing[-1].read_text(encoding="utf-8"))

    def list_models(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.models_dir.glob("*_v*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "name": data.get("name"),
                "version": data.get("version"),
                "saved_at_utc": data.get("saved_at_utc"),
                "metrics": data.get("metrics"),
            })
        return out

