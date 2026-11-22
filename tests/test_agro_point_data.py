from __future__ import annotations

import pytest

from src.agro_point_data import fetch_nasa_power_point


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _payload():
    months = {
        "JAN": 0.1, "FEB": 0.2, "MAR": 0.3, "APR": 0.4,
        "MAY": 0.5, "JUN": 0.6, "JUL": 0.7, "AUG": 0.8,
        "SEP": 0.9, "OCT": 0.4, "NOV": 0.3, "DEC": 0.2,
    }
    return {
        "header": {"time": "1991-2020 climatology"},
        "properties": {"parameter": {
            "GWETROOT": months,
            "GWETTOP": months,
            "IMERG_PRECTOT": months,
            "T2M": {key: value * 10 for key, value in months.items()},
        }},
    }


def test_point_climatology_extracts_values_and_provenance():
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(_payload())

    result = fetch_nasa_power_point(8.5, 16.1, http_get=fake_get)

    assert result is not None
    assert result["source"] == "NASA POWER"
    assert result["latitude"] == 8.5
    assert result["longitude"] == 16.1
    assert result["growing_season"]["root_zone_wetness_mean"] == 0.75
    assert result["growing_season"]["surface_wetness_mean"] == 0.75
    assert result["provenance"]["reference_period"] == "1991-2020 climatology"
    assert calls[0][1]["params"]["community"] == "HY"


def test_point_climatology_returns_none_when_coordinates_are_missing():
    assert fetch_nasa_power_point(None, None, http_get=lambda *_a, **_k: None) is None


def test_point_climatology_returns_none_when_provider_fails():
    def fail(*_args, **_kwargs):
        raise RuntimeError("network unavailable")

    # requests exceptions are intentionally converted to None by the production adapter.
    import requests

    def request_error(*_args, **_kwargs):
        raise requests.Timeout("timeout")

    assert fetch_nasa_power_point(8.5, 16.1, http_get=request_error) is None


def test_point_climatology_rejects_invalid_coordinates():
    with pytest.raises(ValueError):
        fetch_nasa_power_point(95.0, 16.1, http_get=lambda *_a, **_k: _Response(_payload()))


def test_cache_reuses_successful_fetch(monkeypatch):
    import src.agro_point_data as apd

    apd._cache.clear()
    calls = []

    def fake_get(*_a, **_k):
        calls.append(1)
        return _Response(_payload())

    monkeypatch.setattr(apd.requests, "get", fake_get)
    monkeypatch.setattr(apd, "fetch_nasa_power_point", apd.fetch_nasa_power_point)
    # le wrapper compare http_get à requests.get : on appelle avec la valeur patchée
    first = apd.fetch_nasa_power_point(8.501, 16.101, http_get=apd.requests.get)
    second = apd.fetch_nasa_power_point(8.504, 16.104, http_get=apd.requests.get)
    assert first is not None and second == first
    assert len(calls) == 1
    apd._cache.clear()
