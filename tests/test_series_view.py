import pandas as pd
import pytest

from src.ai_agent import FreeDataAIAgent
from src.series_view import collapse_near_identical, months_behind

COLS = [
    "source", "province", "market_name", "commodity_std", "last_observed_month",
    "value", "forecast_month", "forecast_t1", "ci_low_80", "ci_high_80", "hist_mae",
]


def _row(source, market, month, fmonth, value, f):
    return (source, "N'Djamena", market, "Millet", month, value, fmonth, f, f * 0.86, f * 1.14, 10.0)


@pytest.fixture()
def ndjamena_millet():
    """Valeurs réelles observées dans table_ml_forecasts (millet, N'Djamena, nov. 2026)."""
    return pd.DataFrame(
        [
            _row("WFP", "Dembe", "2026-06", "2026-07", 229.34, 271.58),
            _row("WFP", "N'Djamena (Marche A Mil)", "2026-06", "2026-07", 229.31, 271.57),
            _row("WFP", "N'Djamena (Atrone)", "2026-06", "2026-07", 220.2, 262.1),
            _row("FEWS NET", "N'Djamena, Atrone", "2026-08", "2026-09", 243.8, 241.2),
            _row("FEWS NET", "N'Djamena, Dembe", "2026-08", "2026-09", 250.0, 248.9),
        ],
        columns=COLS,
    )


def test_months_behind():
    assert months_behind("2026-06", "2026-08") == 2
    assert months_behind("2026-08", "2026-08") == 0


def test_collapse_groups_near_identical_without_dropping_any(ndjamena_millet):
    groups = collapse_near_identical(ndjamena_millet)
    assert sum(len(g) for g in groups) == len(ndjamena_millet)  # rien n'est supprimé
    merged = [g for g in groups if len(g) > 1]
    assert len(merged) == 1
    assert {r["market_name"] for r in merged[0]} == {"Dembe", "N'Djamena (Marche A Mil)"}


def test_collapse_never_merges_across_sources_or_months():
    df = pd.DataFrame(
        [
            _row("WFP", "A", "2026-06", "2026-07", 200.0, 250.0),
            _row("FEWS NET", "B", "2026-06", "2026-07", 200.0, 250.0),  # autre source
            _row("WFP", "C", "2026-05", "2026-06", 200.0, 250.0),  # autre mois
        ],
        columns=COLS,
    )
    assert all(len(g) == 1 for g in collapse_near_identical(df))


def test_collapse_keeps_genuinely_different_prices_apart():
    df = pd.DataFrame(
        [
            _row("WFP", "A", "2026-06", "2026-07", 229.3, 271.6),
            _row("WFP", "B", "2026-06", "2026-07", 220.2, 262.1),  # 4 % d'écart
        ],
        columns=COLS,
    )
    assert all(len(g) == 1 for g in collapse_near_identical(df))


def test_answer_merges_duplicate_flags_lag_and_lists_freshest_first(ndjamena_millet, gold_tables):
    _, cp_gold = gold_tables
    agent = FreeDataAIAgent(ndjamena_millet, ndjamena_millet, cp_gold)
    text = agent.tool_get_forecast("N'Djamena", "Millet")

    assert "Dembe / N'Djamena (Marche A Mil)" in text
    assert text.count("272 XAF/kg") == 1  # le doublon n'apparaît plus qu'une fois
    assert "arrêtées en 2026-06 (2 mois de retard" in text
    # La source la plus récente (FEWS NET, 2026-08) est listée avant les WFP de 2026-06.
    assert text.index("FEWS NET") < text.index("(WFP)")
    # Aucun avertissement de retard sur les séries à jour.
    fews_lines = [l for l in text.splitlines() if "(FEWS NET)" in l]
    assert fews_lines and all("retard" not in l for l in fews_lines)
