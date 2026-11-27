from types import SimpleNamespace

from scripts import ingest_nasa_power_climate as climate


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_service_role_fetch_uses_stable_primary_key_cursor(monkeypatch):
    calls = []
    first_page = [{"id": i} for i in range(1, 1001)]
    second_page = [{"id": 1001}]

    def fake_get(endpoint, *, headers, params, timeout):
        calls.append(dict(params))
        return _Response(first_page if len(calls) == 1 else second_page)

    monkeypatch.setattr(
        climate,
        "settings",
        SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_service_key="server-only-test-key",
        ),
    )
    monkeypatch.setattr(climate.requests, "get", fake_get)

    rows = climate._fetch_source_rows_service_role()

    assert len(rows) == 1001
    assert [row["id"] for row in rows] == list(range(1, 1002))
    assert calls[0]["order"] == "id.asc"
    assert "id" not in calls[0]
    assert calls[1]["order"] == "id.asc"
    assert calls[1]["id"] == "gt.1000"
    assert "offset" not in calls[0] and "offset" not in calls[1]


def test_service_role_fetch_rejects_non_advancing_cursor(monkeypatch):
    page = [{"id": i} for i in range(1, 1001)]

    def fake_get(endpoint, *, headers, params, timeout):
        return _Response(page)

    monkeypatch.setattr(
        climate,
        "settings",
        SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_service_key="server-only-test-key",
        ),
    )
    monkeypatch.setattr(climate.requests, "get", fake_get)

    # The mocked API ignores the id> cursor and returns the same page.
    with __import__("pytest").raises(RuntimeError, match="Pagination Supabase non monotone"):
        climate._fetch_source_rows_service_role()
