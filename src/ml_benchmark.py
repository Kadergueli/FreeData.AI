"""Phase 12 — Admin-Controlled Multi-Algorithm CSV Benchmark Engine (Pure NumPy/Pandas, CPU-only).

Supports:
- Forecasting: naive_last, seasonal_naive, moving_average_3, ridge_causal_lags (strict chronological split)
- Regression: naive_mean, linear_ols, ridge_l2
- Classification: majority_class, logistic_l2, knn_euclidean (stratified split when possible)
- Clustering: kmeans_k3, kmeans_k4, kmeans_k5 (inertia + silhouette)

All successful candidates are registered in ModelRegistry with status=EVALUATION (never auto-deployed).
Global benchmarks are restricted strictly to `dataset_scope == "platform_public"`.
"""
from __future__ import annotations

import hashlib
import io
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import numpy as np
import pandas as pd

from src.domains import DomainRegistry
from src.ml_engine import (
    KMeansMarketClusterer,
    ModelRegistry,
    RidgePriceRegressor,
    RiskGradeClassifier,
    build_lag_features,
)

MAX_CSV_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_CSV_ROWS = 50_000
ALGORITHM_IMPL_VERSION = "1.0"
ALLOWED_TASK_TYPES = ("forecasting", "regression", "classification", "clustering")
ALLOWED_DATASET_SCOPES = ("platform_public",)


def _check_deadline(deadline: Optional[float], cancel_event: Optional[threading.Event] = None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TimeoutError("Benchmark annulé.")
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError("Benchmark interrompu : délai maximal dépassé.")


def reconstruct_and_predict(artifact: dict[str, Any], X: np.ndarray) -> np.ndarray:
    """Safely reconstructs a pure-JSON model artifact (zero pickle/eval) and runs deterministic inference."""
    if not isinstance(artifact, dict) or not artifact.get("model_type"):
        raise ValueError("Artefact ML invalide : 'model_type' manquant.")
    mtype = str(artifact["model_type"])
    arr = np.asarray(X, dtype=float)

    if mtype in ("RidgePriceRegressor", "LinearOLS"):
        model = RidgePriceRegressor.from_dict(artifact)
        return model.predict(arr)
    if mtype == "NaiveMean":
        return np.full((len(arr),), float(artifact["mean_value"]), dtype=float)
    if mtype == "NaiveLast":
        return arr[:, 0] if arr.ndim == 2 else arr
    if mtype == "MovingAverage":
        w = max(1, int(artifact.get("window", 3)))
        return np.mean(arr[:, :w], axis=1) if arr.ndim == 2 else np.array([float(np.mean(arr[-w:]))])
    if mtype == "SeasonalNaive":
        return arr[:, -1] if arr.ndim == 2 else arr
    if mtype == "MajorityClass":
        return np.full((len(arr),), int(artifact["majority_class"]), dtype=int)
    if mtype == "RiskGradeClassifier":
        weights = np.array(artifact["weights"], dtype=float)
        bias = float(artifact["bias"])
        mean = np.array(artifact["feat_mean"], dtype=float)
        std = np.array(artifact["feat_std"], dtype=float)
        xs = (arr - mean) / np.where(std > 1e-8, std, 1.0)
        probs = RiskGradeClassifier._sigmoid(bias + xs @ weights)
        return (probs >= 0.5).astype(int)
    if mtype == "KMeansMarketClusterer":
        centroids = np.array(artifact["centroids"], dtype=float)
        mean = np.array(artifact["feat_mean"], dtype=float)
        std = np.array(artifact["feat_std"], dtype=float)
        xs = (arr - mean) / np.where(std > 1e-8, std, 1.0)
        dists = np.linalg.norm(xs[:, None, :] - centroids[None, :, :], axis=2)
        return np.argmin(dists, axis=1).astype(int)
    raise ValueError(f"Type d'artefact non reconnu ou non autorisé : '{mtype}'.")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_float(val: Any, digits: int = 4) -> Optional[float]:
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, digits)
    except (TypeError, ValueError):
        return None


@dataclass
class DatasetSpec:
    domain: str
    task_type: Literal["forecasting", "regression", "classification", "clustering"]
    feature_columns: list[str]
    target_column: Optional[str] = None
    time_column: Optional[str] = None
    dataset_name: str = "uploaded_dataset.csv"
    dataset_provenance: dict[str, Any] = field(default_factory=dict)
    dataset_scope: str = "platform_public"
    dataset_hash: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.dataset_scope not in ALLOWED_DATASET_SCOPES:
            raise PermissionError(
                f"Portée de dataset refusée ('{self.dataset_scope}'). "
                "Seuls les jeux de données autorisés ('platform_public') peuvent entraîner des modèles globaux."
            )
        if self.domain not in DomainRegistry.MODULES:
            raise ValueError(f"Domaine inconnu : '{self.domain}'.")
        if self.task_type not in ALLOWED_TASK_TYPES:
            raise ValueError(f"Type de tâche invalide : '{self.task_type}'. Attendu : {ALLOWED_TASK_TYPES}.")
        if self.task_type != "clustering":
            if not self.target_column or not self.target_column.strip():
                raise ValueError(f"La colonne cible (target_column) est obligatoire pour la tâche '{self.task_type}'.")
        if self.task_type == "forecasting":
            if not self.time_column or not self.time_column.strip():
                raise ValueError("La colonne temporelle (time_column) est obligatoire pour 'forecasting'.")
        if self.task_type in ("regression", "classification", "clustering"):
            if not self.feature_columns:
                raise ValueError(f"Au moins une colonne explicative (feature_columns) est requise pour '{self.task_type}'.")
        # Target leakage guard
        if self.target_column and self.target_column in set(self.feature_columns):
            raise ValueError(
                f"Fuite de cible détectée : la colonne cible '{self.target_column}' ne peut pas figurer dans feature_columns."
            )
        if len(set(self.feature_columns)) != len(self.feature_columns):
            raise ValueError("Colonnes dupliquées détectées dans feature_columns.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_and_validate_csv(csv_bytes: bytes, spec: DatasetSpec) -> tuple[pd.DataFrame, DatasetSpec]:
    """Strictly validates CSV size, encoding, headers, duplicate columns, row count, and schema compatibility."""
    spec.validate()
    if not csv_bytes:
        raise ValueError("Fichier CSV vide.")
    if len(csv_bytes) > MAX_CSV_BYTES:
        raise ValueError(f"Fichier CSV trop volumineux ({len(csv_bytes)} octets > limite de 5 Mo).")

    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Encodage CSV invalide : UTF-8 requis.") from exc

    # Check raw header line for duplicate column names before pandas auto-renames them
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError("Le CSV doit contenir un en-tête et au moins une ligne de données.")
    raw_headers = [h.strip().strip('"').strip("'") for h in lines[0].split(",")]
    if len(set(raw_headers)) != len(raw_headers):
        raise ValueError("Colonnes en double détectées dans l'en-tête CSV.")

    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as exc:
        raise ValueError(f"Lecture CSV impossible : {type(exc).__name__}") from exc

    if df.empty:
        raise ValueError("Le CSV ne contient aucune ligne exploitable.")
    if len(df) > MAX_CSV_ROWS:
        raise ValueError(f"Trop de lignes ({len(df)} > limite maximale de {MAX_CSV_ROWS}).")

    cols = set(df.columns.astype(str))
    needed: list[str] = list(spec.feature_columns)
    if spec.target_column:
        needed.append(spec.target_column)
    if spec.time_column:
        needed.append(spec.time_column)
    missing_cols = [c for c in needed if c not in cols]
    if missing_cols:
        raise ValueError(f"Colonnes absentes du CSV : {', '.join(missing_cols)}")

    # Validate numeric compatibility & drop missing rows on required columns
    numeric_cols = list(spec.feature_columns)
    if spec.task_type in ("forecasting", "regression") and spec.target_column:
        numeric_cols.append(spec.target_column)

    work = df.copy()
    for col in numeric_cols:
        work[col] = pd.to_numeric(work[col], errors="coerce")
        if work[col].isna().all():
            raise ValueError(f"La colonne '{col}' ne contient aucune valeur numérique valide.")

    if spec.task_type == "classification" and spec.target_column:
        work[spec.target_column] = pd.to_numeric(work[spec.target_column], errors="coerce")
        if work[spec.target_column].isna().all():
            raise ValueError(f"La colonne cible '{spec.target_column}' doit contenir des classes numériques (0/1).")

    if spec.time_column:
        work[spec.time_column] = work[spec.time_column].astype(str).str.strip()
        work = work[work[spec.time_column] != ""]
        work = work.sort_values(spec.time_column, kind="mergesort")

    req_non_null = list(numeric_cols)
    if spec.task_type == "classification" and spec.target_column:
        req_non_null.append(spec.target_column)
    clean = work.dropna(subset=req_non_null).reset_index(drop=True)

    min_rows = 6 if spec.task_type == "clustering" else 10
    if len(clean) < min_rows:
        raise ValueError(f"Échantillon insuffisant après nettoyage ({len(clean)} lignes < {min_rows} requises).")

    if spec.task_type == "classification" and spec.target_column:
        uniq = sorted(clean[spec.target_column].astype(int).unique().tolist())
        if len(uniq) < 2 or not set(uniq).issubset({0, 1}):
            raise ValueError(
                f"La classification binaire requiert exactement deux classes {{0, 1}} (trouvé : {uniq})."
            )

    dataset_hash = hashlib.sha256(csv_bytes).hexdigest()
    spec.dataset_hash = dataset_hash
    spec.input_schema = {
        "feature_columns": list(spec.feature_columns),
        "target_column": spec.target_column,
        "time_column": spec.time_column,
        "dtypes": {c: str(clean[c].dtype) for c in needed if c in clean.columns},
        "clean_rows": int(len(clean)),
    }
    return clean, spec


# ---------------------------------------------------------------------------
# Fair Metrics Helpers (Zero Fabrication, Explicit Zero-Denominator Guards)
# ---------------------------------------------------------------------------

def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    err = y_true - y_pred
    mae = _safe_float(np.mean(np.abs(err)), 4)
    rmse = _safe_float(np.sqrt(np.mean(err ** 2)), 4)
    metrics: dict[str, Any] = {}
    if mae is not None:
        metrics["mae"] = mae
    if rmse is not None:
        metrics["rmse"] = rmse
    nonzero = np.abs(y_true) > 1e-8
    if np.any(nonzero):
        mape = _safe_float(np.mean(np.abs(err[nonzero] / y_true[nonzero])) * 100.0, 2)
        if mape is not None:
            metrics["mape_pct"] = mape
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    if ss_tot > 1e-12:
        r2 = _safe_float(1.0 - float(np.sum(err ** 2)) / ss_tot, 4)
        if r2 is not None:
            metrics["r2"] = r2
    return metrics


def _classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    tp = int(np.sum((y_pred == 1) & (y_true == 1)))
    fp = int(np.sum((y_pred == 1) & (y_true == 0)))
    fn = int(np.sum((y_pred == 0) & (y_true == 1)))
    tn = int(np.sum((y_pred == 0) & (y_true == 0)))
    total = max(1, len(y_true))
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {
        "accuracy": round((tp + tn) / total, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
    }


def _silhouette_score_numpy(X: np.ndarray, labels: np.ndarray, *, max_samples: int = 1000, seed: int = 42) -> Optional[float]:
    uniq = np.unique(labels)
    if len(uniq) < 2 or len(uniq) >= len(X):
        return None
    if len(X) > max_samples:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(X), size=max_samples, replace=False)
        X = X[idx]
        labels = labels[idx]
        uniq = np.unique(labels)
        if len(uniq) < 2:
            return None
    # Pairwise Euclidean distance matrix
    diff = X[:, None, :] - X[None, :, :]
    dists = np.sqrt(np.sum(diff ** 2, axis=2))
    scores = []
    for i in range(len(X)):
        same = labels == labels[i]
        same[i] = False
        a_i = float(np.mean(dists[i, same])) if np.any(same) else 0.0
        b_i = float("inf")
        for c in uniq:
            if c == labels[i]:
                continue
            other = labels == c
            if np.any(other):
                b_i = min(b_i, float(np.mean(dists[i, other])))
        denom = max(a_i, b_i)
        scores.append((b_i - a_i) / denom if denom > 1e-12 else 0.0)
    return _safe_float(np.mean(scores), 4)


def _stratified_split_indices(y: np.ndarray, test_ratio: float = 0.25, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    tr_idx: list[int] = []
    te_idx: list[int] = []
    for cls in np.unique(y):
        cls_idx = np.where(y == cls)[0]
        rng.shuffle(cls_idx)
        n_te = max(1, int(round(len(cls_idx) * test_ratio))) if len(cls_idx) >= 2 else 0
        te_idx.extend(cls_idx[:n_te].tolist())
        tr_idx.extend(cls_idx[n_te:].tolist())
    if not te_idx or not tr_idx:
        idx = np.arange(len(y))
        rng.shuffle(idx)
        split = max(1, int(len(y) * (1.0 - test_ratio)))
        return idx[:split], idx[split:]
    return np.array(tr_idx, dtype=int), np.array(te_idx, dtype=int)


# ---------------------------------------------------------------------------
# Modular Benchmark Runners by Task Type
# ---------------------------------------------------------------------------

def _benchmark_forecasting(df: pd.DataFrame, spec: DatasetSpec) -> list[dict[str, Any]]:
    y_all = df[spec.target_column].to_numpy(dtype=float)
    n = len(y_all)
    split = max(4, int(n * 0.7))
    if n - split < 2:
        raise ValueError("Historique insuffisant pour un split chronologique 70/30.")
    y_test = y_all[split:]
    protocol = f"chronological_70_30 (train={split}, test={len(y_test)})"
    results: list[dict[str, Any]] = []

    # 1. Naive last-value baseline
    t0 = time.perf_counter()
    preds_naive = y_all[split - 1 : n - 1]
    results.append({
        "algorithm": "naive_last",
        "hyperparameters": {"lag": 1},
        "metrics": _regression_metrics(y_test, preds_naive),
        "artifact": {"model_type": "NaiveLast", "lag": 1},
        "train_samples": split,
        "test_samples": len(y_test),
        "protocol": protocol,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "status": "evaluated",
    })

    # 2. Moving Average 3 (strictly causal)
    t0 = time.perf_counter()
    preds_ma3 = np.array([float(np.mean(y_all[max(0, t - 3) : t])) for t in range(split, n)], dtype=float)
    results.append({
        "algorithm": "moving_average_3",
        "hyperparameters": {"window": 3},
        "metrics": _regression_metrics(y_test, preds_ma3),
        "artifact": {"model_type": "MovingAverage", "window": 3},
        "train_samples": split,
        "test_samples": len(y_test),
        "protocol": protocol,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "status": "evaluated",
    })

    # 3. Seasonal Naive (lag 12) when sufficient history exists
    if split >= 12:
        t0 = time.perf_counter()
        preds_snaive = y_all[split - 12 : n - 12]
        results.append({
            "algorithm": "seasonal_naive_12",
            "hyperparameters": {"season_period": 12},
            "metrics": _regression_metrics(y_test, preds_snaive),
            "artifact": {"model_type": "SeasonalNaive", "season_period": 12},
            "train_samples": split,
            "test_samples": len(y_test),
            "protocol": protocol,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "status": "evaluated",
        })

    # 4. Ridge L2 on strictly causal lag features
    X_lag, y_lag = build_lag_features(y_all)
    # Align test window with split: y_lag[i] corresponds to y_all[i + 3]
    lag_split = max(3, split - 3)
    if len(X_lag) > lag_split + 1:
        X_tr, y_tr = X_lag[:lag_split], y_lag[:lag_split]
        X_te, y_te = X_lag[lag_split:], y_lag[lag_split:]
        for alpha in (1.0, 10.0):
            t0 = time.perf_counter()
            model = RidgePriceRegressor(alpha=alpha).fit(X_tr, y_tr)
            preds = model.predict(X_te)
            results.append({
                "algorithm": f"ridge_causal_lags_a{int(alpha)}",
                "hyperparameters": {"alpha": alpha, "lags": [1, 2, 3]},
                "metrics": _regression_metrics(y_te, preds),
                "artifact": model.to_dict(),
                "train_samples": int(len(X_tr)),
                "test_samples": int(len(X_te)),
                "protocol": protocol,
                "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
                "status": "evaluated",
            })

    return results


def _benchmark_regression(df: pd.DataFrame, spec: DatasetSpec, seed: int = 42) -> list[dict[str, Any]]:
    X = df[spec.feature_columns].to_numpy(dtype=float)
    y = df[spec.target_column].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    idx = np.arange(len(X))
    rng.shuffle(idx)
    split = max(3, int(len(X) * 0.75))
    tr, te = idx[:split], idx[split:]
    X_tr, y_tr, X_te, y_te = X[tr], y[tr], X[te], y[te]
    protocol = f"holdout_75_25_seed{seed} (train={len(tr)}, test={len(te)})"
    results: list[dict[str, Any]] = []

    # 1. Naive mean baseline
    t0 = time.perf_counter()
    mean_y = float(np.mean(y_tr))
    results.append({
        "algorithm": "naive_mean",
        "hyperparameters": {},
        "metrics": _regression_metrics(y_te, np.full_like(y_te, mean_y)),
        "artifact": {"model_type": "NaiveMean", "mean_value": mean_y},
        "train_samples": len(tr),
        "test_samples": len(te),
        "protocol": protocol,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "status": "evaluated",
    })

    # 2. Linear OLS (Ridge with alpha=0.0)
    t0 = time.perf_counter()
    ols = RidgePriceRegressor(alpha=0.0).fit(X_tr, y_tr)
    results.append({
        "algorithm": "linear_ols",
        "hyperparameters": {"alpha": 0.0},
        "metrics": _regression_metrics(y_te, ols.predict(X_te)),
        "artifact": {**ols.to_dict(), "model_type": "LinearOLS"},
        "train_samples": len(tr),
        "test_samples": len(te),
        "protocol": protocol,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "status": "evaluated",
    })

    # 3. Ridge L2
    t0 = time.perf_counter()
    ridge = RidgePriceRegressor(alpha=1.0).fit(X_tr, y_tr)
    results.append({
        "algorithm": "ridge_l2",
        "hyperparameters": {"alpha": 1.0},
        "metrics": _regression_metrics(y_te, ridge.predict(X_te)),
        "artifact": ridge.to_dict(),
        "train_samples": len(tr),
        "test_samples": len(te),
        "protocol": protocol,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "status": "evaluated",
    })

    return results


def _benchmark_classification(df: pd.DataFrame, spec: DatasetSpec, seed: int = 42) -> list[dict[str, Any]]:
    X = df[spec.feature_columns].to_numpy(dtype=float)
    y = df[spec.target_column].to_numpy(dtype=int)
    tr, te = _stratified_split_indices(y, test_ratio=0.25, seed=seed)
    X_tr, y_tr, X_te, y_te = X[tr], y[tr], X[te], y[te]
    protocol = f"stratified_holdout_75_25_seed{seed} (train={len(tr)}, test={len(te)})"
    results: list[dict[str, Any]] = []

    # 1. Majority-class baseline
    t0 = time.perf_counter()
    maj = 1 if int(np.sum(y_tr == 1)) >= int(np.sum(y_tr == 0)) else 0
    results.append({
        "algorithm": "majority_class",
        "hyperparameters": {},
        "metrics": _classification_metrics(y_te, np.full_like(y_te, maj)),
        "artifact": {"model_type": "MajorityClass", "majority_class": maj},
        "train_samples": len(tr),
        "test_samples": len(te),
        "protocol": protocol,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "status": "evaluated",
    })

    # 2. Logistic Regression L2 (strict out-of-sample evaluation)
    t0 = time.perf_counter()
    clf = RiskGradeClassifier(lr=0.2, epochs=300, l2=0.05)
    fit_res = clf.fit_and_evaluate(X_tr, y_tr)
    if fit_res.get("status") == "evaluated" and clf.weights is not None:
        Xs_te = (X_te - clf.feat_mean) / clf.feat_std
        preds = (clf._sigmoid(clf.bias + Xs_te @ clf.weights) >= 0.5).astype(int)
        results.append({
            "algorithm": "logistic_l2",
            "hyperparameters": {"lr": 0.2, "epochs": 300, "l2": 0.05},
            "metrics": _classification_metrics(y_te, preds),
            "artifact": {
                "model_type": "RiskGradeClassifier",
                "bias": clf.bias,
                "weights": clf.weights.tolist(),
                "feat_mean": clf.feat_mean.tolist(),
                "feat_std": clf.feat_std.tolist(),
            },
            "train_samples": len(tr),
            "test_samples": len(te),
            "protocol": protocol,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "status": "evaluated",
        })

    # 3. k-NN (k=5, pure NumPy standardized Euclidean)
    k = min(5, len(X_tr))
    if k >= 1:
        t0 = time.perf_counter()
        mean_x = X_tr.mean(axis=0)
        std_x = np.where(X_tr.std(axis=0) > 1e-8, X_tr.std(axis=0), 1.0)
        Xtr_s = (X_tr - mean_x) / std_x
        Xte_s = (X_te - mean_x) / std_x
        dists = np.linalg.norm(Xte_s[:, None, :] - Xtr_s[None, :, :], axis=2)
        nn_idx = np.argsort(dists, axis=1)[:, :k]
        preds_knn = (np.mean(y_tr[nn_idx], axis=1) >= 0.5).astype(int)
        results.append({
            "algorithm": f"knn_k{k}",
            "hyperparameters": {"k": k, "metric": "euclidean"},
            "metrics": _classification_metrics(y_te, preds_knn),
            "artifact": {
                "model_type": "KNNClassifier",
                "k": k,
                "feat_mean": mean_x.tolist(),
                "feat_std": std_x.tolist(),
            },
            "train_samples": len(tr),
            "test_samples": len(te),
            "protocol": protocol,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "status": "evaluated",
        })

    return results


def _benchmark_clustering(df: pd.DataFrame, spec: DatasetSpec, seed: int = 42) -> list[dict[str, Any]]:
    X = df[spec.feature_columns].to_numpy(dtype=float)
    mean_x = X.mean(axis=0)
    std_x = np.where(X.std(axis=0) > 1e-8, X.std(axis=0), 1.0)
    Xs = (X - mean_x) / std_x
    protocol = f"unsupervised_kmeans_seed{seed} (samples={len(df)})"
    results: list[dict[str, Any]] = []

    for k in (3, 4, 5):
        if len(df) <= k:
            continue
        t0 = time.perf_counter()
        km = KMeansMarketClusterer(k=k, max_iter=30, seed=seed)
        res = km.fit_predict(df, list(spec.feature_columns))
        if res.get("status") != "clustered":
            continue
        labels = np.array([int(r["cluster_id"]) for r in res["records"]], dtype=int)
        sil = _silhouette_score_numpy(Xs, labels, seed=seed)
        metrics: dict[str, Any] = {"inertia": res["inertia"], "k": k, "samples": res["samples"]}
        if sil is not None:
            metrics["silhouette_score"] = sil
        results.append({
            "algorithm": f"kmeans_k{k}",
            "hyperparameters": {"k": k, "max_iter": 30, "seed": seed},
            "metrics": metrics,
            "artifact": {
                "model_type": "KMeansMarketClusterer",
                "k": k,
                "centroids": km.centroids.tolist() if km.centroids is not None else [],
                "feat_mean": km.feat_mean.tolist() if km.feat_mean is not None else [],
                "feat_std": km.feat_std.tolist() if km.feat_std is not None else [],
            },
            "train_samples": len(df),
            "test_samples": 0,
            "protocol": protocol,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "status": "evaluated",
        })

    return results


def run_csv_benchmark(
    csv_bytes: bytes,
    spec: DatasetSpec,
    *,
    registry: ModelRegistry,
    seed: int = 42,
    deadline: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
) -> dict[str, Any]:
    """Validates CSV + DatasetSpec, benchmarks all compatible algorithms fairly,
    and registers every candidate in ModelRegistry with status=EVALUATION (never auto-deployed).
    """
    _check_deadline(deadline, cancel_event)
    clean_df, validated_spec = parse_and_validate_csv(csv_bytes, spec)
    _check_deadline(deadline, cancel_event)
    if validated_spec.task_type == "forecasting":
        candidates = _benchmark_forecasting(clean_df, validated_spec)
    elif validated_spec.task_type == "regression":
        candidates = _benchmark_regression(clean_df, validated_spec, seed=seed)
    elif validated_spec.task_type == "classification":
        candidates = _benchmark_classification(clean_df, validated_spec, seed=seed)
    else:
        candidates = _benchmark_clustering(clean_df, validated_spec, seed=seed)

    now = _utc_now()
    registered: list[dict[str, Any]] = []
    existing_models = registry.list_models()

    for cand in candidates:
        _check_deadline(deadline, cancel_event)
        algo = cand["algorithm"]
        model_id = f"bench_{validated_spec.domain}_{validated_spec.task_type}_{algo}"
        dedup_key = hashlib.sha256(
            (
                f"{model_id}|{ALGORITHM_IMPL_VERSION}|{validated_spec.dataset_hash}|"
                f"{validated_spec.domain}|{validated_spec.task_type}|"
                f"{validated_spec.feature_columns}|{validated_spec.target_column}|{validated_spec.time_column}|"
                f"{cand['hyperparameters']}|{cand['protocol']}"
            ).encode("utf-8")
        ).hexdigest()[:20]

        same_model = [m for m in existing_models if m.get("model_id") == model_id]
        dup = next(
            (m for m in same_model if (m.get("configuration") or {}).get("benchmark_dedup_key") == dedup_key),
            None,
        )
        if dup is not None:
            registered.append({
                "model_id": model_id,
                "version": dup["version"],
                "algorithm": algo,
                "lifecycle_status": dup.get("lifecycle_status"),
                "deduplicated": True,
                "metrics": dup.get("evaluation_metrics") or {},
                "duration_ms": cand["duration_ms"],
            })
            continue

        next_v = max((int(m.get("version", 0)) for m in same_model), default=0) + 1
        entry = registry.register_model(
            model_id=model_id,
            model_name=f"{validated_spec.domain} · {algo} ({validated_spec.task_type})",
            domain=validated_spec.domain,
            algorithm=algo,
            task_type=validated_spec.task_type,
            version=next_v,
            description=f"Candidat benchmark CSV '{validated_spec.dataset_name}' ({cand['protocol']}).",
            training_dataset_ref=f"csv:{validated_spec.dataset_name}#{validated_spec.dataset_hash[:12]}",
            evaluation_dataset_ref=cand["protocol"],
            dataset_provenance={
                **validated_spec.dataset_provenance,
                "dataset_name": validated_spec.dataset_name,
                "dataset_scope": validated_spec.dataset_scope,
                "dataset_hash": validated_spec.dataset_hash,
                "input_schema": validated_spec.input_schema,
            },
            training_date=now,
            lifecycle_status="EVALUATION",
            evaluation_metrics=cand["metrics"],
            configuration={
                "hyperparameters": cand["hyperparameters"],
                "seed": seed,
                "train_samples": cand["train_samples"],
                "test_samples": cand["test_samples"],
                "protocol": cand["protocol"],
                "input_schema": validated_spec.input_schema,
                "benchmark_dedup_key": dedup_key,
            },
            dependencies=["numpy", "pandas"],
            enabled=True,
            set_active=False,
        )
        artifact_bundle = {
            "name": model_id,
            "version": next_v,
            "saved_at_utc": now,
            "metrics": cand["metrics"],
            "artifact": {
                **cand["artifact"],
                "input_schema": validated_spec.input_schema,
                "dataset_hash": validated_spec.dataset_hash,
            },
        }
        registry._persist_artifact(model_id, next_v, artifact_bundle)
        existing_models.append(entry)
        registered.append({
            "model_id": model_id,
            "version": next_v,
            "algorithm": algo,
            "lifecycle_status": "EVALUATION",
            "deduplicated": False,
            "metrics": cand["metrics"],
            "duration_ms": cand["duration_ms"],
        })

    return {
        "dataset_hash": validated_spec.dataset_hash,
        "domain": validated_spec.domain,
        "task_type": validated_spec.task_type,
        "input_schema": validated_spec.input_schema,
        "candidates_evaluated": len(registered),
        "candidates": registered,
    }


# ---------------------------------------------------------------------------
# Garde-fou de mise en production (un benchmark ne remplace jamais silencieusement un modèle)
# ---------------------------------------------------------------------------

MIN_TOTAL_ROWS_FOR_PRODUCTION = 100
MIN_TEST_ROWS_FOR_PRODUCTION = 20
MIN_RELATIVE_IMPROVEMENT = 0.05  # régression/prévision : -5 % d'erreur ; classification : +0,05 de F1
MIN_SILHOUETTE_FOR_PRODUCTION = 0.25
BASELINE_ALGORITHMS = frozenset({"naive_last", "moving_average_3", "seasonal_naive_12", "naive_mean", "majority_class"})


def promotion_blockers(registry: ModelRegistry, model_id: str, version: int) -> list[str]:
    """Raisons pour lesquelles un candidat issu d'un benchmark CSV ne peut pas passer en production.

    Liste vide = éligible. Les modèles qui ne viennent pas du benchmark ne sont pas concernés.
    """
    entries = registry.list_models()
    entry = next(
        (m for m in entries if m.get("model_id") == model_id and int(m.get("version", 0)) == int(version)),
        None,
    )
    if entry is None:
        raise KeyError(f"Modèle introuvable : {model_id} v{version}")
    cfg = entry.get("configuration") or {}
    if "benchmark_dedup_key" not in cfg:
        return []

    blockers: list[str] = []
    prov = entry.get("dataset_provenance") or {}
    if not str(prov.get("source") or "").strip() or not str(prov.get("license") or "").strip():
        blockers.append("Provenance incomplète : la source et la licence du jeu de données sont obligatoires.")

    clean_rows = int((cfg.get("input_schema") or {}).get("clean_rows") or 0)
    test_rows = int(cfg.get("test_samples") or 0)
    if clean_rows < MIN_TOTAL_ROWS_FOR_PRODUCTION:
        blockers.append(
            f"Échantillon trop petit ({clean_rows} lignes < {MIN_TOTAL_ROWS_FOR_PRODUCTION} requises pour la production)."
        )
    if test_rows < MIN_TEST_ROWS_FOR_PRODUCTION:
        blockers.append(f"Jeu de test trop petit ({test_rows} lignes < {MIN_TEST_ROWS_FOR_PRODUCTION}).")

    task = entry.get("task_type")
    metrics = entry.get("evaluation_metrics") or {}
    algo = str(entry.get("algorithm") or "")
    if task == "clustering":
        sil = metrics.get("silhouette_score")
        if sil is None or float(sil) < MIN_SILHOUETTE_FOR_PRODUCTION:
            blockers.append(f"Silhouette insuffisante ({sil} < {MIN_SILHOUETTE_FOR_PRODUCTION}).")
        return blockers

    if algo in BASELINE_ALGORITHMS:
        blockers.append("Un modèle de référence (baseline) sert de comparaison : il ne peut pas être activé tel quel.")
        return blockers

    ds_hash = prov.get("dataset_hash")
    baselines = [
        m for m in entries
        if m.get("domain") == entry.get("domain")
        and m.get("task_type") == task
        and (m.get("dataset_provenance") or {}).get("dataset_hash") == ds_hash
        and str(m.get("algorithm") or "") in BASELINE_ALGORITHMS
    ]
    key = "f1_score" if task == "classification" else "mae"
    base_vals = [float((m.get("evaluation_metrics") or {})[key]) for m in baselines if key in (m.get("evaluation_metrics") or {})]
    cand = metrics.get(key)
    if not base_vals or cand is None:
        blockers.append("Aucune référence comparable trouvée : impossible de prouver que le modèle fait mieux.")
        return blockers
    cand = float(cand)
    if task == "classification":
        best_base = max(base_vals)
        if cand - best_base < MIN_RELATIVE_IMPROVEMENT:
            blockers.append(f"F1 {cand:.3f} ne dépasse pas la référence {best_base:.3f} d'au moins {MIN_RELATIVE_IMPROVEMENT}.")
    else:
        best_base = min(base_vals)
        if best_base <= 0 or (best_base - cand) / best_base < MIN_RELATIVE_IMPROVEMENT:
            blockers.append(
                f"MAE {cand:.4g} n'améliore pas la meilleure référence ({best_base:.4g}) d'au moins {int(MIN_RELATIVE_IMPROVEMENT * 100)} %."
            )
    return blockers


# ---------------------------------------------------------------------------
# Bounded Background Benchmark Job Manager (Max 1 Concurrent, 60s Timeout)
# ---------------------------------------------------------------------------

class BenchmarkJobManager:
    """Runs at most 1 CSV benchmark at a time in a background thread so normal chat requests are never blocked."""

    def __init__(self, max_concurrent: int = 1, timeout_seconds: float = 60.0) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._executor = ThreadPoolExecutor(max_workers=self.max_concurrent, thread_name_prefix="fd-ml-bench")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def _active_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j["status"] in ("queued", "running"))

    def submit(
        self,
        *,
        actor: str,
        csv_bytes: bytes,
        spec: DatasetSpec,
        registry: ModelRegistry,
        timeout_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        # Validate synchronously first so invalid CSVs/specs fail fast (400/403/422) without allocating a job
        clean_df, validated_spec = parse_and_validate_csv(csv_bytes, spec)
        del clean_df  # do not retain parsed DataFrame in submit scope

        eff_timeout = float(timeout_seconds) if timeout_seconds is not None else self.timeout_seconds
        with self._lock:
            if self._active_count() >= self.max_concurrent:
                raise OverflowError(
                    "Un benchmark ML est déjà en cours d'exécution. Patientez avant d'en lancer un autre."
                )
            if len(self._jobs) > 100:
                oldest = sorted(self._jobs.items(), key=lambda kv: kv[1]["created_at"])[:25]
                for k, _ in oldest:
                    self._jobs.pop(k, None)
            job_id = f"BENCH-{uuid.uuid4().hex[:10].upper()}"
            now = _utc_now()
            rec = {
                "job_id": job_id,
                "actor": actor,
                "domain": validated_spec.domain,
                "task_type": validated_spec.task_type,
                "dataset_name": validated_spec.dataset_name,
                "dataset_hash": validated_spec.dataset_hash,
                "status": "queued",
                "progress_pct": 0,
                "timeout_seconds": eff_timeout,
                "result": None,
                "error": None,
                "created_at": now,
                "updated_at": now,
            }
            self._jobs[job_id] = rec

        cancel_event = threading.Event()

        def _run() -> None:
            t0 = time.monotonic()
            deadline = t0 + eff_timeout
            with self._lock:
                self._jobs[job_id]["status"] = "running"
                self._jobs[job_id]["progress_pct"] = 20
                self._jobs[job_id]["updated_at"] = _utc_now()
            try:
                res = run_csv_benchmark(
                    csv_bytes,
                    validated_spec,
                    registry=registry,
                    deadline=deadline,
                    cancel_event=cancel_event,
                )
                elapsed = time.monotonic() - t0
                if elapsed > eff_timeout:
                    raise TimeoutError(f"Benchmark dépassé ({elapsed:.1f}s > {eff_timeout:.1f}s).")
                with self._lock:
                    self._jobs[job_id]["status"] = "completed"
                    self._jobs[job_id]["progress_pct"] = 100
                    self._jobs[job_id]["result"] = res
                    self._jobs[job_id]["updated_at"] = _utc_now()
            except TimeoutError as exc:
                cancel_event.set()
                with self._lock:
                    self._jobs[job_id]["status"] = "timed_out"
                    self._jobs[job_id]["error"] = str(exc)
                    self._jobs[job_id]["updated_at"] = _utc_now()
            except Exception as exc:
                with self._lock:
                    self._jobs[job_id]["status"] = "failed"
                    self._jobs[job_id]["error"] = f"{type(exc).__name__}: {exc}"
                    self._jobs[job_id]["updated_at"] = _utc_now()

        self._executor.submit(_run)
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise KeyError(f"Job benchmark introuvable : {job_id}")
            return dict(rec)

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            ordered = sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)
            return [dict(j) for j in ordered[:limit]]

