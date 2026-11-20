"""Garde-fous du Studio ML : provenance obligatoire et conditions de mise en production."""
import base64

import numpy as np
import pytest
from fastapi import HTTPException

from api import server
from src.ml_benchmark import DatasetSpec, promotion_blockers, run_csv_benchmark
from src.ml_engine import ModelRegistry


def _csv(n: int) -> bytes:
    rng = np.random.default_rng(7)
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    y = 3.0 * x1 - 2.0 * x2 + rng.normal(scale=0.3, size=n)
    rows = ["x1,x2,y"] + [f"{a:.5f},{b:.5f},{c:.5f}" for a, b, c in zip(x1, x2, y)]
    return ("\n".join(rows)).encode()


def _run(tmp_path, n, provenance):
    reg = ModelRegistry(models_dir=str(tmp_path / "models"), db_path=str(tmp_path / "reg.db"))
    spec = DatasetSpec(
        domain="finance", task_type="regression", target_column="y", feature_columns=["x1", "x2"],
        dataset_provenance=provenance,
    )
    res = run_csv_benchmark(_csv(n), spec, registry=reg)
    return reg, {c["algorithm"]: c for c in res["candidates"]}


def test_endpoint_requires_source_and_license():
    req = server.AdminBenchmarkRequest(
        domain="finance", task_type="regression", target_column="y", feature_columns=["x1"],
        csv_base64=base64.b64encode(_csv(50)).decode(), dataset_provenance={"description": "sans source"},
    )
    with pytest.raises(HTTPException) as exc:
        server.admin_ai_launch_benchmark_endpoint(req, actor_info=("a", "platform_admin"), admin=server.get_admin_service())
    assert exc.value.status_code == 422


def test_large_dataset_better_than_baseline_is_eligible(tmp_path):
    reg, cands = _run(tmp_path, 300, {"source": "Jeu synthétique", "license": "CC0"})
    ridge = cands["ridge_l2"]
    assert promotion_blockers(reg, "bench_finance_regression_ridge_l2", ridge["version"]) == []


def test_baseline_cannot_be_activated(tmp_path):
    reg, cands = _run(tmp_path, 300, {"source": "Jeu synthétique", "license": "CC0"})
    b = promotion_blockers(reg, "bench_finance_regression_naive_mean", cands["naive_mean"]["version"])
    assert any("référence" in x for x in b)


def test_small_sample_and_missing_provenance_are_blocked(tmp_path):
    reg, cands = _run(tmp_path, 40, {})
    b = promotion_blockers(reg, "bench_finance_regression_ridge_l2", cands["ridge_l2"]["version"])
    assert any("Provenance" in x for x in b)
    assert any("trop petit" in x for x in b)


def test_unknown_model_raises_key_error(tmp_path):
    reg = ModelRegistry(models_dir=str(tmp_path / "m"), db_path=str(tmp_path / "r.db"))
    with pytest.raises(KeyError):
        promotion_blockers(reg, "nope", 1)
