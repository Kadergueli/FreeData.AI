import pandas as pd
import pytest

from src.market_pro import compute_farm_operating_account


def _compute(**overrides):
    args = {
        "province": "Salamat",
        "crop_id": "millet",
        "area_hectares": 2.0,
        "hist_df": pd.DataFrame([
            {"commodity_std": "Millet", "province": "Salamat", "year_month": "2025-01", "value": 100.0, "source": "FEWS NET"},
            {"commodity_std": "Millet", "province": "Salamat", "year_month": "2026-09", "value": 200.0, "source": "FEWS NET"},
            {"commodity_std": "Millet", "province": "Salamat", "year_month": "2026-10", "value": 300.0, "source": "WFP"},
            {"commodity_std": "Millet", "province": "N'Djamena", "year_month": "2026-10", "value": 900.0, "source": "WFP"},
        ]),
        "forecast_df": pd.DataFrame([
            {"commodity_std": "Millet", "province": "Salamat", "forecast_month": "2026-10", "forecast_t1": 800.0, "source": "model-a"},
            {"commodity_std": "Millet", "province": "Salamat", "forecast_month": "2026-11", "forecast_t1": 300.0, "source": "model-a"},
            {"commodity_std": "Millet", "province": "Salamat", "forecast_month": "2026-11", "forecast_t1": 320.0, "source": "model-b"},
            {"commodity_std": "Millet", "province": "N'Djamena", "forecast_month": "2026-11", "forecast_t1": 990.0, "source": "model-c"},
        ]),
        "target_yield_kg_ha": 1000.0,
        "seed_cost_per_ha_xaf": 10000.0,
        "loan_amount_xaf": 50000.0,
        "interest_rate_pct": 12.0,
    }
    args.update(overrides)
    return compute_farm_operating_account(**args)


def test_farm_account_uses_latest_forecast_month_and_local_history_window():
    result = _compute()
    assert result["forecast_reference_month"] == "2026-11"
    assert result["forecast_rows_used"] == 2
    assert result["forecast_data_scope"] == "province"
    assert result["history_reference_month"] == "2026-10"
    assert result["history_data_scope"] == "province"
    assert result["history_rows_used"] == 2
    central = next(s for s in result["scenarios"] if s["id"] == "central_ml")
    assert central["market_price_xaf_kg"] == 310.0
    historical = next(s for s in result["scenarios"] if s["id"] == "storage_median")
    assert historical["market_price_xaf_kg"] == 250.0


def test_farm_account_discloses_national_fallback_and_missing_yield_source():
    result = _compute(
        hist_df=pd.DataFrame([
            {"commodity_std": "Millet", "province": "Mandoul", "year_month": "2026-10", "value": 250.0, "source": "WFP"},
        ]),
        forecast_df=pd.DataFrame([
            {"commodity_std": "Millet", "province": "Mandoul", "forecast_month": "2026-11", "forecast_t1": 300.0, "source": "model"},
        ]),
        target_yield_kg_ha=None,
        national_agro_rows=[],
    )
    assert result["history_data_scope"] == "national_fallback"
    assert result["forecast_data_scope"] == "national_fallback"
    assert result["yield_source_type"] == "technical_fallback"
    assert any("repli national" in note.lower() for note in result["investor_readiness_notes"])
    assert any("valeur technique de repli" in note.lower() for note in result["investor_readiness_notes"])


def test_farm_account_does_not_claim_dscr_without_repayment_schedule():
    result = _compute()
    assert result["debt_service_xaf"] is None
    assert result["dscr_available"] is False
    assert all(s["dscr"] is None for s in result["scenarios"])
    assert any("DSCR non calculé" in note for note in result["investor_readiness_notes"])


@pytest.mark.parametrize("area", [0, -1, 500001])
def test_farm_account_rejects_invalid_area(area):
    with pytest.raises(ValueError, match="superficie"):
        _compute(area_hectares=area)


def test_farm_account_rejects_negative_costs():
    with pytest.raises(ValueError, match="coûts"):
        _compute(seed_cost_per_ha_xaf=-1)
