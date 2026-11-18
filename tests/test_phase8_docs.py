"""Phase 8 documentation quality checks: existence, link integrity, API route parity, and formula parity."""
import re
from pathlib import Path

from api import server
from src.business_engine import CAPEX_SHARE, REINVEST_RATE, RESERVE_SHARE, WORKING_CAPITAL_SHARE

ROOT = Path(__file__).resolve().parents[1]


def test_required_documentation_files_exist():
    required = [
        "README.md",
        "ARCHITECTURE.md",
        "DATA_CATALOG.md",
        "METHODOLOGY.md",
        "DATA_GOVERNANCE.md",
        "USER_GUIDE.md",
        "API.md",
        "SECURITY.md",
        "DEPLOYMENT.md",
    ]
    for name in required:
        p = ROOT / name
        assert p.is_file(), f"Missing documentation file: {name}"
        assert p.stat().st_size > 200, f"Documentation file unexpectedly empty: {name}"


def test_no_broken_local_markdown_links():
    link_re = re.compile(r"\[[^\]]+\]\(([^)#]+)\)")
    for md_name in ("README.md", "ARCHITECTURE.md", "DATA_CATALOG.md", "METHODOLOGY.md", "DATA_GOVERNANCE.md", "USER_GUIDE.md", "API.md", "SECURITY.md", "DEPLOYMENT.md"):
        text = (ROOT / md_name).read_text(encoding="utf-8")
        for target in link_re.findall(text):
            if target.startswith(("http://", "https://", "file:///")):
                continue
            assert (ROOT / target).exists(), f"Broken link '{target}' in {md_name}"


def test_api_docs_match_registered_routes_and_methodology_constants():
    registered_paths = {getattr(r, "path", "") for r in server.app.routes}
    api_doc = (ROOT / "API.md").read_text(encoding="utf-8")
    for documented_route in (
        "/api/v1/health",
        "/api/v1/metadata",
        "/api/v1/forecasts",
        "/api/v1/chat",
        "/api/v1/reports/market-study",
        "/api/v1/reports/market-study/pdf",
        "/api/v1/reports/jobs",
        "/api/v1/projects",
        "/api/v1/metrics",
        "/api/v1/refresh",
    ):
        assert documented_route in api_doc
        assert documented_route in registered_paths, f"Documented route missing from FastAPI app: {documented_route}"

    meth_doc = (ROOT / "METHODOLOGY.md").read_text(encoding="utf-8")
    assert f"{int(WORKING_CAPITAL_SHARE * 100)}%" in meth_doc
    assert f"{int(CAPEX_SHARE * 100)}%" in meth_doc
    assert f"{int(RESERVE_SHARE * 100)}%" in meth_doc
    assert f"{int(REINVEST_RATE * 100)}%" in meth_doc

