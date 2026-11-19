from __future__ import annotations

import shutil
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd

from src.backup import backup_model_artifacts, backup_sqlite_file, restore_sqlite_file
from src.ml_engine import (
    KMeansMarketClusterer,
    ModelRegistry,
    RidgePriceRegressor,
    evaluate_ridge_chronological,
)
from src.projects.store import ProjectStore
from src.rag_engine import HybridRAGEngine
from src.reports.jobs import ReportJobManager
from src.user_documents import UserDocumentStore


def test_ml_artifact_survives_ephemeral_disk_wipe_and_redeploy(tmp_path: Path):
    durable_db = tmp_path / "durable_registry.db"
    ephemeral_dir_1 = tmp_path / "container_1_models"
    reg1 = ModelRegistry(models_dir=str(ephemeral_dir_1), db_path=str(durable_db))

    series = np.array([300, 315, 320, 325, 340, 350, 355, 365, 370, 385, 390, 405], dtype=float)
    ev = evaluate_ridge_chronological(series)
    assert ev["status"] == "evaluated"
    model: RidgePriceRegressor = ev["model"]

    reg1.save_model(
        "ridge_durable",
        model.to_dict(),
        {"mae": ev["ridge_mae_xaf_kg"], "rmse": ev["ridge_rmse_xaf_kg"]},
        domain="agriculture",
        algorithm="RidgeRegression_L2",
        task_type="forecasting",
        training_dataset_ref="table_ml_forecasts",
    )
    reg1.transition_status("ridge_durable", 1, "DEPLOYED", set_active=True)

    # Simulate Render container replacement: wipe ephemeral_dir_1 completely!
    shutil.rmtree(ephemeral_dir_1)
    assert not ephemeral_dir_1.exists()

    # Boot fresh container with empty local models dir but same durable DB
    ephemeral_dir_2 = tmp_path / "container_2_models"
    reg2 = ModelRegistry(models_dir=str(ephemeral_dir_2), db_path=str(durable_db))
    selected = reg2.select_model(domain="agriculture", task_type="forecasting")
    assert selected["model_id"] == "ridge_durable"
    assert selected["version"] == 1
    assert selected["is_active_production"] is True

    hydrated = reg2.load_version("ridge_durable", 1)
    rebuilt = RidgePriceRegressor.from_dict(hydrated["artifact"])
    assert rebuilt.weights is not None and len(rebuilt.weights) == 6
    assert reg2.summary()["durable_artifacts_count"] == 1


def test_staging_backup_and_recovery_drill_measured(tmp_path: Path):
    # 1. Populate staging stores (projects, user docs, ML registry)
    proj_db = tmp_path / "staging_projects.db"
    docs_db = tmp_path / "staging_docs.db"
    ml_db = tmp_path / "staging_ml.db"
    ml_dir = tmp_path / "staging_models"

    p_store = ProjectStore(db_path=str(proj_db))
    proj = p_store.create_project("owner_drill", "Projet Staging Drill")

    d_store = UserDocumentStore(db_path=str(docs_db))
    doc = d_store.ingest_document(
        owner_id="owner_drill",
        filename="rapport_mil_2026.txt",
        content_bytes="Le prix du mil à N'Djamena atteint 420 XAF/kg en octobre 2026.".encode("utf-8"),
        mime_type="text/plain",
        project_id=proj["project_id"],
    )

    m_reg = ModelRegistry(models_dir=str(ml_dir), db_path=str(ml_db))
    m_reg.save_model("drill_model", {"weights": [1.2, -0.4]}, {"mae": 15.0})
    m_reg.transition_status("drill_model", 1, "DEPLOYED", set_active=True)

    # 2. Execute backups
    bak_root = tmp_path / "backups"
    t0 = time.perf_counter()
    b_proj = backup_sqlite_file(proj_db, bak_root)
    b_docs = backup_sqlite_file(docs_db, bak_root)
    b_ml = backup_sqlite_file(ml_db, bak_root)
    b_art = backup_model_artifacts(ml_dir, bak_root)
    backup_ms = round((time.perf_counter() - t0) * 1000, 2)

    assert b_proj["integrity_ok"] and b_docs["integrity_ok"] and b_ml["integrity_ok"]
    assert b_art["status"] == "verified"

    # 3. Restore onto clean recovery target & verify 0% data loss
    rec_root = tmp_path / "recovered"
    t1 = time.perf_counter()
    restore_sqlite_file(Path(b_proj["backup_path"]), rec_root / "projects.db")
    restore_sqlite_file(Path(b_docs["backup_path"]), rec_root / "docs.db")
    restore_sqlite_file(Path(b_ml["backup_path"]), rec_root / "ml.db")
    restore_ms = round((time.perf_counter() - t1) * 1000, 2)

    rec_p = ProjectStore(db_path=str(rec_root / "projects.db"))
    rec_d = UserDocumentStore(db_path=str(rec_root / "docs.db"))
    rec_m = ModelRegistry(models_dir=str(rec_root / "empty_models"), db_path=str(rec_root / "ml.db"))

    assert len(rec_p.list_projects("owner_drill")) == 1
    hits = rec_d.retrieve_for_owner("owner_drill", "prix du mil N'Djamena", project_id=proj["project_id"])
    assert len(hits) >= 1 and hits[0]["doc_id"] == doc["doc_id"]
    assert rec_m.select_model(model_id="drill_model")["version"] == 1
    assert rec_m.load_version("drill_model", 1)["artifact"]["weights"] == [1.2, -0.4]
    print(f"[DRILL] backup_ms={backup_ms} restore_ms={restore_ms} data_loss=0")


def test_performance_acceptance_measurements(tmp_path: Path):
    tracemalloc.start()

    # 1. ML Ridge backtest + inference latency
    series = np.linspace(300.0, 480.0, 36) + np.sin(np.arange(36)) * 12.0
    t0 = time.perf_counter()
    ev = evaluate_ridge_chronological(series)
    ridge_ms = round((time.perf_counter() - t0) * 1000, 2)
    assert ev["status"] == "evaluated"

    # 2. K-Means clustering latency (120 markets)
    df = pd.DataFrame({
        "market": [f"M{i}" for i in range(120)],
        "price": np.linspace(200, 700, 120),
        "cv": np.linspace(4, 30, 120),
    })
    t0 = time.perf_counter()
    cl = KMeansMarketClusterer(k=3, seed=42).fit_predict(df, ["price", "cv"])
    kmeans_ms = round((time.perf_counter() - t0) * 1000, 2)
    assert cl["status"] == "clustered"

    # 3. Model artifact lazy load latency
    reg = ModelRegistry(models_dir=str(tmp_path / "perf_models"))
    reg.save_model("perf_ridge", ev["model"].to_dict(), {"mae": ev["ridge_mae_xaf_kg"]})
    t0 = time.perf_counter()
    reg.load_version("perf_ridge", 1)
    load_ms = round((time.perf_counter() - t0) * 1000, 2)

    # 4. Hybrid RAG ingest & retrieval latency
    rag = HybridRAGEngine()
    rag_dir = tmp_path / "rag_docs"
    rag_dir.mkdir(parents=True, exist_ok=True)
    for i in range(25):
        fp = rag_dir / f"doc_{i}.md"
        fp.write_text(f"Marché Tchad {i}: prix du mil {350 + i} XAF/kg, sorgho {300 + i} XAF/kg.", encoding="utf-8")
        rag.ingest_file(fp, source=f"doc_{i}.md")
    t0 = time.perf_counter()
    hits = rag.search("prix du mil Tchad", top_k=5)
    rag_ms = round((time.perf_counter() - t0) * 1000, 2)
    assert len(hits) >= 1

    # 5. Background job throughput (4 jobs)
    mgr = ReportJobManager(max_workers=2)
    t0 = time.perf_counter()
    jids = [mgr.submit("u_perf", lambda p: {"pdf_bytes": b"%PDF-1.4"})["job_id"] for _ in range(4)]
    for jid in jids:
        for _ in range(50):
            if mgr.get_status("u_perf", jid)["status"] == "completed":
                break
            time.sleep(0.01)
    jobs_ms = round((time.perf_counter() - t0) * 1000, 2)

    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mb = round(peak_bytes / (1024 * 1024), 2)
    print(
        f"[PERF] ridge_ms={ridge_ms} kmeans_ms={kmeans_ms} model_load_ms={load_ms} "
        f"rag_search_ms={rag_ms} jobs_4x_ms={jobs_ms} peak_mem_mb={peak_mb}"
    )
    assert ridge_ms < 500
    assert kmeans_ms < 500
    assert load_ms < 200
    assert rag_ms < 500
