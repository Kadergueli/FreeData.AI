"""Phase 11 tests: Data Products, licensing enforcement, API key revocation/quotas, ML inference, and SDK."""
from dataclasses import replace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi import HTTPException

from api import server
from sdk.python.freedata_client import FreeDataClient
from src.api_keys import ApiKeyManager
from src.data_products import DataProductCatalog
from src.governance import LicensingRegistry


def _state_with_data(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, premium_api_keys="pro-key-1234567890", admin_token="adm-11"))
    fc = pd.DataFrame([
        {"source": "WFP", "province": "Lac", "market_name": "Bol", "commodity_std": "Millet", "last_observed_month": "2026-10", "last_observed_price": 210.0, "forecast_month": "2026-11", "forecast_t1": 220.0},
    ])
    cp = pd.DataFrame([{"province": "Lac", "commodity_std": "Millet", "credit_score": 82.0, "grade": "A", "cv_pct": 8.5, "ltv_ratio": 0.8}])
    return {"forecast_df": fc, "passport_df": cp}


def test_data_products_catalog_and_license_blocking(monkeypatch):
    st = _state_with_data(monkeypatch)
    reg = LicensingRegistry()
    cat = DataProductCatalog()

    products = cat.list_products(reg, st["forecast_df"])
    assert len(products) == 4

    # Attribution-required forecast export succeeds
    exp = server.export_data_product_endpoint("commodity_forecasts_v1", format="json", limit=10, offset=0, state=st, registry=reg)
    assert exp["total"] == 1
    assert len(exp["attribution"]) >= 1

    # Unclear-licensing raw table export is blocked with 403
    with pytest.raises(HTTPException) as exc:
        server.export_data_product_endpoint("raw_market_observations_restricted", format="json", limit=10, offset=0, state=st, registry=reg)
    assert exc.value.status_code == 403


def test_api_key_issuance_quotas_revocation_and_ml_predict(monkeypatch):
    _state_with_data(monkeypatch)
    km = ApiKeyManager()

    issued = server.issue_developer_key_endpoint(
        server.DeveloperKeyCreateRequest(owner_id="dev:alice", label="ci", daily_quota=2),
        x_admin_token="adm-11",
        km=km,
    )
    raw_key = issued["api_key"]
    key_id = issued["key_id"]

    # Consume 1st and 2nd quota slots via ML inference
    req = server.MLPredictRequest(series_prices=[200, 205, 210, 215, 220, 225, 230, 235, 240, 245])
    caller1 = server._require_developer_or_premium_key(x_api_key=raw_key, x_premium_key=None, km=km)
    assert caller1 == "dev:alice"
    pred = server.ml_predict_endpoint(req, _caller=caller1)
    assert pred["prediction_xaf_kg"] > 230.0
    assert pred["ci_low_80"] <= pred["prediction_xaf_kg"] <= pred["ci_high_80"]

    server._require_developer_or_premium_key(x_api_key=raw_key, x_premium_key=None, km=km)
    # 3rd call exceeds daily_quota=2 -> 429
    with pytest.raises(HTTPException) as exc_quota:
        server._require_developer_or_premium_key(x_api_key=raw_key, x_premium_key=None, km=km)
    assert exc_quota.value.status_code == 429

    # Revoke key -> 403
    server.revoke_developer_key_endpoint(key_id, x_admin_token="adm-11", km=km)
    with pytest.raises(HTTPException) as exc_rev:
        server._require_developer_or_premium_key(x_api_key=raw_key, x_premium_key=None, km=km)
    assert exc_rev.value.status_code == 403


def test_python_sdk_client(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {"products": [{"product_id": "commodity_forecasts_v1"}]}
    monkeypatch.setattr("sdk.python.freedata_client.requests.get", lambda *a, **kw: mock_resp)

    client = FreeDataClient("https://freedata-ai.onrender.com", api_key="fd_test")
    prods = client.list_products()
    assert prods[0]["product_id"] == "commodity_forecasts_v1"

