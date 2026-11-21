from __future__ import annotations

from pathlib import Path

from src.domains import DomainRegistry
from src.ml_engine import ModelRegistry
from src.reports.pdf_generator import render_market_study_pdf


def test_all_eight_chad_domains_route_and_isolate_correctly():
    samples = {
        "health": "Statistiques de santé, vaccination et paludisme au Tchad",
        "population": "Recensement démographique et croissance de la population",
        "environment": "Sécheresse, pluviométrie et environnement du Lac Tchad",
        "infrastructure": "Accès à l'eau potable, forage et infrastructures routières",
        "transport": "Corridor de fret, camion et coût du transport logistique",
        "economy": "Inflation, trésorerie, point mort et crédit bancaire",
        "agriculture": "Rendement des récoltes et campagne agricole au Tchad",
        "markets_and_prices": "Quel est le prix du mil à N'Djamena en XAF ?",
    }
    for expected_dom, query in samples.items():
        mod = DomainRegistry.classify_domain(query)
        assert mod.domain_id == expected_dom, f"Expected {expected_dom}, got {mod.domain_id} for {query!r}"
        assert mod.instructions and mod.allowed_tools


def test_staging_blueprint_and_sql_migration_safety():
    root = Path(__file__).resolve().parents[1]
    staging_yaml = (root / "render.staging.yaml").read_text(encoding="utf-8")
    assert "freedata-ai-api-staging" in staging_yaml
    assert 'value: "staging"' in staging_yaml
    assert "REQUIRE_SIGNED_USER_AUTH" in staging_yaml
    assert 'value: "1"' in staging_yaml
    assert "ALLOW_LOCALHOST_CORS" in staging_yaml
    assert "ENABLE_DOCS" in staging_yaml
    # Never hardcode secrets in staging blueprint
    assert "gsk_" not in staging_yaml
    assert "jina_" not in staging_yaml
    assert "postgresql://" not in staging_yaml

    mig = (root / "sql" / "14_ml_model_registry.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS freedata_app.ml_model_registry" in mig
    assert "ENABLE ROW LEVEL SECURITY" in mig
    assert "REVOKE ALL ON TABLE freedata_app.ml_model_registry" in mig


def test_pdf_generation_preserves_tables_sections_and_passes_validation():
    study_payload = {
        "title": "Étude de Marché Staging — Mil à N'Djamena",
        "subtitle": "Validation Phase 10",
        "promoter_name": "Staging QA",
        "commodity": "Millet",
        "origin_province": "Salamat",
        "dest_province": "N'Djamena",
        "capital_xaf": 2_000_000,
        "market_context": {
            "commodity": "Millet",
            "origin_province": "Salamat",
            "dest_province": "N'Djamena",
            "origin_price_xaf_kg": 280.0,
            "dest_price_xaf_kg": 410.0,
            "data_period": "2026-10",
        },
        "financial_plan": {
            "capital_xaf": 2_000_000,
            "working_capital_xaf": 1_600_000,
            "capex_xaf": 160_000,
            "reserve_xaf": 240_000,
            "monthly_net_profit_xaf": 185_000,
            "break_even_kg": 920.0,
        },
        "sections": [
            {"title": "1. Synthèse Exécutive", "content": "Analyse basée sur les données observées (XAF/kg)."},
            {"title": "2. Hypothèses & Limites", "content": "Intervalle de confiance 80 % et coûts de transport inclus."},
        ],
        "references": ["WFP/FEWSNET Chad Markets", "METHODOLOGY.md"],
    }
    pdf_bytes, val = render_market_study_pdf(study_payload, return_validation=True)
    assert isinstance(pdf_bytes, (bytes, bytearray)) and pdf_bytes[:4] == b"%PDF"
    assert val["passed"] is True
    assert val["page_count"] >= 1


def test_ml_full_lifecycle_progression_and_persistence(tmp_path: Path):
    reg = ModelRegistry(models_dir=str(tmp_path / "m"), db_path=str(tmp_path / "m.db"))
    reg.register_model(
        model_id="lifecycle_ridge",
        model_name="Lifecycle Ridge",
        domain="agriculture",
        algorithm="RidgeRegression_L2",
        task_type="forecasting",
        version=1,
        lifecycle_status="REGISTERED",
    )
    for st in ("TRAINING", "TRAINED", "EVALUATION", "APPROVED"):
        out = reg.transition_status("lifecycle_ridge", 1, st)
        assert out["lifecycle_status"] == st
        assert out["is_active_production"] is False

    deployed = reg.transition_status("lifecycle_ridge", 1, "DEPLOYED", set_active=True)
    assert deployed["lifecycle_status"] == "DEPLOYED"
    assert deployed["is_active_production"] is True
    assert reg.select_model(model_id="lifecycle_ridge")["version"] == 1
