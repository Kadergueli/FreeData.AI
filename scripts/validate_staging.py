"""Live Staging End-to-End Acceptance Script for FreeData.AI.

Usage (against dedicated STAGING only — never run against production):
    STAGING_API_URL=https://freedata-ai-api-staging.onrender.com \
    STAGING_ADMIN_TOKEN=<optional_staging_admin_token> \
    python scripts/validate_staging.py
"""
from __future__ import annotations

import os
import secrets
import sys
import time
import requests


def _check(name: str, ok: bool, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    base = (os.getenv("STAGING_API_URL") or "").strip().rstrip("/")
    if not base:
        print("ERROR: Set STAGING_API_URL (e.g. https://freedata-ai-api-staging.onrender.com).")
        return 2
    if "freedata-ai.onrender.com" in base and "staging" not in base:
        print("REFUSED: STAGING_API_URL looks like production. Aborting for safety.")
        return 2

    admin_token = (os.getenv("STAGING_ADMIN_TOKEN") or "").strip()
    all_ok = True

    # 1. Health check
    t0 = time.perf_counter()
    r = requests.get(f"{base}/api/v1/health", timeout=20)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    all_ok &= _check("GET /api/v1/health", r.status_code == 200, f"status={r.status_code} ({ms} ms)")

    # 2. Unsigned X-User-Id MUST be rejected with 401 when REQUIRE_SIGNED_USER_AUTH=1
    fake_uid = "u" + secrets.token_hex(16)
    r_unsigned = requests.get(f"{base}/api/v1/projects", headers={"X-User-Id": fake_uid}, timeout=15)
    all_ok &= _check(
        "Unsigned X-User-Id rejected (REQUIRE_SIGNED_USER_AUTH=1)",
        r_unsigned.status_code == 401,
        f"status={r_unsigned.status_code}",
    )

    # 3. Register -> /me -> /refresh -> old token revoked -> projects CRUD -> /logout
    email = f"staging_{secrets.token_hex(6)}@example.com"
    password = f"Staging!{secrets.token_hex(6)}"
    r_reg = requests.post(
        f"{base}/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "Staging Probe"},
        timeout=20,
    )
    ok_reg = r_reg.status_code == 200 and bool(r_reg.json().get("token"))
    all_ok &= _check("POST /api/v1/auth/register", ok_reg, f"status={r_reg.status_code}")
    if not ok_reg:
        return 1

    tok1 = r_reg.json()["token"]
    h1 = {"Authorization": f"Bearer {tok1}"}

    r_me = requests.get(f"{base}/api/v1/auth/me", headers=h1, timeout=15)
    all_ok &= _check("GET /api/v1/auth/me", r_me.status_code == 200, f"status={r_me.status_code}")

    r_ref = requests.post(f"{base}/api/v1/auth/refresh", headers=h1, timeout=15)
    ok_ref = r_ref.status_code == 200 and r_ref.json().get("token") != tok1
    all_ok &= _check("POST /api/v1/auth/refresh", ok_ref, f"status={r_ref.status_code}")
    tok2 = r_ref.json().get("token", tok1) if ok_ref else tok1
    h2 = {"Authorization": f"Bearer {tok2}"}

    if ok_ref:
        r_old = requests.get(f"{base}/api/v1/auth/me", headers=h1, timeout=15)
        all_ok &= _check("Revoked old token rejected", r_old.status_code == 401, f"status={r_old.status_code}")

    # 4. Multi-domain discovery
    r_dom = requests.get(f"{base}/api/v1/domains", headers=h2, timeout=15)
    dom_count = len(r_dom.json().get("domains", [])) if r_dom.status_code == 200 else 0
    all_ok &= _check("GET /api/v1/domains (>=8 Chad domains)", r_dom.status_code == 200 and dom_count >= 8, f"count={dom_count}")

    # 5. Project create + delete cleanup
    r_proj = requests.post(f"{base}/api/v1/projects", headers=h2, json={"name": "Staging Smoke Project"}, timeout=15)
    ok_proj = r_proj.status_code == 200 and bool(r_proj.json().get("project_id"))
    all_ok &= _check("POST /api/v1/projects (Bearer)", ok_proj, f"status={r_proj.status_code}")
    if ok_proj:
        pid = r_proj.json()["project_id"]
        requests.delete(f"{base}/api/v1/projects/{pid}?confirm=true", headers=h2, timeout=15)

    # 6. Logout & verify token revocation
    r_out = requests.post(f"{base}/api/v1/auth/logout", headers=h2, timeout=15)
    all_ok &= _check("POST /api/v1/auth/logout", r_out.status_code == 200, f"status={r_out.status_code}")
    r_after = requests.get(f"{base}/api/v1/auth/me", headers=h2, timeout=15)
    all_ok &= _check("Logged-out token rejected", r_after.status_code == 401, f"status={r_after.status_code}")

    # 7. Optional Admin Control Center live probe
    if admin_token:
        r_adm = requests.get(
            f"{base}/api/v1/admin/overview?live_probe=true",
            headers={"X-Admin-Token": admin_token},
            timeout=25,
        )
        ok_adm = r_adm.status_code == 200
        detail = f"status={r_adm.status_code}"
        if ok_adm:
            body = r_adm.json()
            high_w = [w["code"] for w in body.get("operational_warnings", []) if w.get("severity") == "high"]
            ml_be = (body.get("ml_registry_summary") or {}).get("persistence_backend")
            detail = f"env={body.get('deployment_info', {}).get('environment')} ml_backend={ml_be} high_warnings={high_w}"
            ok_adm = len(high_w) == 0 and ml_be == "supabase_postgresql"
        all_ok &= _check("Admin overview live_probe (0 HIGH warnings + PG ML)", ok_adm, detail)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

