# FreeData.AI — Data Licensing Policy

## 1. License Categories (`src/governance.py`)
- `open_data`: Explicitly licensed for open use and redistribution.
- `publicly_accessible`: Publicly readable, **not** assumed redistributable without explicit permission.
- `attribution_required`: Derived/published datasets requiring explicit source attribution.
- `restricted`: Server-only / PRO datasets (`table_ml_seasonality_studies`, `table_ml_anomalies`). Redistribution blocked.
- `unclear_licensing`: Raw source datasets (`table_public`) where upstream license terms are unverified. Redistribution blocked by `LicensingRegistry.assert_redistribution_allowed()`.

## 2. Enforcement & Attribution
- Any dataset missing from `LicensingRegistry`, marked `suspended`, or categorized as `restricted` / `unclear_licensing` is programmatically blocked from redistribution.
- Attribution notices (`get_attribution_notices()`) are preserved across processing and exposed via `GET /api/v1/governance/registry` and report *Traçabilité dynamique*.

