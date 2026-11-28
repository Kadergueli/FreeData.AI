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



def test_legacy_view_error_is_detected_only_for_missing_source_label():
    from src.data_loader import _is_missing_source_label_error

    class FakeResponse:
        status_code = 400
        text = '{"message":"column v_clean_markets.commodity_source_label does not exist","code":"42703"}'

    class FakeError(Exception):
        response = FakeResponse()

    assert _is_missing_source_label_error(FakeError("HTTP 400"))
    assert not _is_missing_source_label_error(RuntimeError("network timeout"))


def test_rest_loader_falls_back_to_legacy_view_without_failing(monkeypatch):
    import requests
    from src import data_loader

    class FakeResponse:
        def __init__(self, rows=None, error=False):
            self.rows = rows or []
            self.error = error
            self.status_code = 400
            self.text = '{"message":"column commodity_source_label does not exist","code":"42703"}'

        def raise_for_status(self):
            if self.error:
                exc = requests.HTTPError("400 Bad Request")
                exc.response = self
                raise exc

        def json(self):
            return self.rows

    calls = []

    def fake_get(*args, **kwargs):
        calls.append(kwargs["params"]["select"])
        if len(calls) == 1:
            return FakeResponse(error=True)
        return FakeResponse(rows=[{
            "month_date": "2025-01-01",
            "source": "FEWS NET",
            "province": "Salamat",
            "market_name": "Am Timan",
            "commodity_std": "Maize (white)",
            "price_value": 450.0,
            "is_flagged_outlier": 0,
        }])

    monkeypatch.setattr(data_loader.settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(data_loader.settings, "read_key", "test-key")
    monkeypatch.setattr(data_loader.requests, "get", fake_get)

    result = data_loader._fetch_supabase_rest_view()

    assert len(calls) == 2
    assert "commodity_source_label" in calls[0]
    assert "commodity_source_label" not in calls[1]
    assert result.loc[0, "commodity_source_label"] == "Maize (white)"
    assert result.loc[0, "value"] == 450.0
