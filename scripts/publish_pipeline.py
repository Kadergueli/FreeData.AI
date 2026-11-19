"""Point d'entrée CLI du pipeline mensuel de publication FreeData.AI."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data_loader import load_clean_markets
from src.ml_engine import ModelRegistry
from src.publication_pipeline import run_publication_pipeline


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=None, help="Chemin vers un CSV local (sinon config par défaut)")
    ap.add_argument("--dry-run", action="store_true", help="Exécute extraction/validation/calculs sans publier")
    ap.add_argument("--api-url", default=os.getenv("API_BASE_URL", ""), help="URL de l'API à rafraîchir")
    ap.add_argument("--report", default="reports/last_publication_report.json", help="Chemin du rapport JSON")
    ap.add_argument("--skip-registry", action="store_true", help="Désactive l'enregistrement dans ModelRegistry")
    args = ap.parse_args(argv)

    loader = (lambda: load_clean_markets(args.csv)) if args.csv else load_clean_markets
    report = run_publication_pipeline(
        loader_fn=loader,
        api_base_url=args.api_url or None,
        dry_run=args.dry_run,
        report_path=args.report,
        model_registry=None if args.skip_registry else ModelRegistry(),
        allow_auto_deploy=False,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pipeline_status"] in ("succeeded", "partial_refresh_pending") else 1


if __name__ == "__main__":
    raise SystemExit(main())

