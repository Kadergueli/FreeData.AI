# FreeData.AI — Developer Guide & SDK Reference

Base URL: `https://freedata-ai.onrender.com` (OpenAPI docs available at `/docs` when `ENABLE_DOCS=true`).

## Authentication & Rate Limits
- **Public Data Endpoints** (`/api/v1/products`, `/api/v1/forecasts`, `/api/v1/analytics/*`, `/api/v1/governance/registry`): `120 req/min` per IP.
- **Authenticated AI & ML Services** (`/api/v1/chat`, `/api/v1/ml/predict`, `/api/v1/reports/*`): Require `X-Api-Key` (`fd_...` issued via `/api/v1/developer/keys`) or `X-Premium-Key` (`20 req/min` per IP + daily key quota).
- **Error Codes**: `401` (missing auth), `403` (invalid/revoked key or license-restricted dataset), `404` (resource not found), `422` (validation or QA gate blocked), `429` (rate limit or daily quota exceeded).

## Python SDK (`sdk/python/freedata_client.py`)
```python
from sdk.python.freedata_client import FreeDataClient

client = FreeDataClient("https://freedata-ai.onrender.com", api_key="fd_...")
products = client.list_products()
pred = client.predict_prices([200, 205, 210, 215, 220, 225, 230, 235])
hits = client.rag_search("point mort sacherie")
```

## JavaScript Example (`fetch`)
```javascript
const res = await fetch("https://freedata-ai.onrender.com/api/v1/products");
const { products } = await res.json();

const ml = await fetch("https://freedata-ai.onrender.com/api/v1/ml/predict", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-Api-Key": "fd_..." },
  body: JSON.stringify({ series_prices: [200, 205, 210, 215, 220, 225, 230, 235] }),
});
```

