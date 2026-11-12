import numpy as np
import pandas as pd
import pytest

from scripts.update_predictions import build_exports, _records
from src.forecasting import run_forecasting_pipeline
from src.credit_passport import compute_credit_passport


def make_synthetic_markets() -> pd.DataFrame:
    """36 mois, 3 provinces x 2 produits.

    - Salamat / Millet : pic de +30 % au dernier mois (doit déclencher une alerte).
    - Lac / Maize (white) : série périmée, s'arrête fin 2023.
    """
    rng = np.random.default_rng(0)
    months = pd.period_range("2023-01", "2025-12", freq="M")
    rows = []
    for prov in ["Lac", "Salamat", "N'Djamena"]:
        for comm in ["Millet", "Maize (white)"]:
            base = 300 + rng.integers(0, 100)
            for i, m in enumerate(months):
                v = base * (1 + 0.1 * np.sin(i / 3)) * (1 + rng.normal(0, 0.03))
                rows.append(("WFP", prov, f"{prov} marche", comm, m, v))
    df = pd.DataFrame(rows, columns=["source", "province", "market_name", "commodity_std", "year_month", "value"])
    spike = (df.province == "Salamat") & (df.commodity_std == "Millet") & (df.year_month == months[-1])
    df.loc[spike, "value"] *= 1.30
    stale = (df.province == "Lac") & (df.commodity_std == "Maize (white)") & (df.year_month > pd.Period("2023-12"))
    return df[~stale].reset_index(drop=True)


@pytest.fixture(scope="session")
def pipeline_outputs():
    kg = make_synthetic_markets()
    hist, forecast = run_forecasting_pipeline(kg)
    passport = compute_credit_passport(kg)
    return kg, hist, forecast, passport


@pytest.fixture(scope="session")
def gold_tables(pipeline_outputs):
    """Ce que Supabase renverrait après scripts/update_predictions.py."""
    _, _, forecast, passport = pipeline_outputs
    fc_export, cp_export = build_exports(forecast, passport)
    return pd.DataFrame(_records(fc_export)), pd.DataFrame(_records(cp_export))
