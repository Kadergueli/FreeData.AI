import pandas as pd

from src.data_loader import standardize_raw_markets, unify_commodity_case


def test_fews_maize_source_indicators_remain_separate_series():
    raw = pd.DataFrame(
        [
            {
                "source": "FEWS NET",
                "reference_date": "2025-01-15",
                "unit": "XAF/kg",
                "value": 400.0,
                "region": "Salamat",
                "indicator": "Maize (Corn) price (retail) - Am Timan",
                "notes": "",
            },
            {
                "source": "FEWS NET",
                "reference_date": "2025-01-20",
                "unit": "XAF/kg",
                "value": 500.0,
                "region": "Salamat",
                "indicator": "Maize Grain (White) price (retail) - Am Timan",
                "notes": "",
            },
        ]
    )

    standardized = standardize_raw_markets(raw)
    preserved = unify_commodity_case(standardized)

    assert set(preserved["commodity_source_label"]) == {
        "Maize (Corn)",
        "Maize Grain (White)",
    }
    assert set(preserved["commodity_std"]) == {
        "Maize (Corn)",
        "Maize Grain (White)",
    }
    assert len(preserved) == 2
    assert preserved["value"].tolist() == [400.0, 500.0]


def test_maize_indicators_stay_separate_even_when_one_has_more_records():
    rows = []
    for day, value in [(1, 400.0), (2, 410.0), (3, 420.0)]:
        rows.append(
            {
                "source": "FEWS NET",
                "reference_date": f"2025-01-{day:02d}",
                "unit": "XAF/kg",
                "value": value,
                "region": "Salamat",
                "indicator": "Maize (Corn) price (retail) - Am Timan",
                "notes": "",
            }
        )
    rows.append(
        {
            "source": "FEWS NET",
            "reference_date": "2025-01-04",
            "unit": "XAF/kg",
            "value": 500.0,
            "region": "Salamat",
            "indicator": "Maize Grain (White) price (retail) - Am Timan",
            "notes": "",
        }
    )

    preserved = unify_commodity_case(standardize_raw_markets(pd.DataFrame(rows)))

    assert preserved["commodity_std"].value_counts().to_dict() == {
        "Maize (Corn)": 3,
        "Maize Grain (White)": 1,
    }
    assert len(preserved) == 4
