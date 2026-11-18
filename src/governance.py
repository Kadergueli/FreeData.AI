"""Enforceable Data Governance, Dataset Licensing Registry, Lineage, Privacy, and Admin Audit."""
from __future__ import annotations

import copy
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_KEY_RE = re.compile(r"\b(?:gsk_|sk-|eyJ)[A-Za-z0-9_\-.]{8,}\b")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class LicenseEntry:
    dataset_id: str
    original_publisher: str
    original_source_url: str
    license_name: str
    license_version: str
    license_category: str  # open_data | publicly_accessible | attribution_required | restricted | unclear_licensing
    attribution_required: bool
    attribution_text: str
    redistribution_allowed: bool
    commercial_use_allowed: bool
    modification_allowed: bool
    access_restrictions: str
    last_verified_date: str
    publication_status: str = "approved"  # approved | suspended | pending_review

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LineageRecord:
    derived_dataset_id: str
    original_dataset_id: str
    source_version: str
    collection_timestamp: str
    transformation_operations: list[str]
    cleaning_operations: list[str]
    aggregation_methods: list[str]
    derived_dataset_version: str
    processing_software_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LicensingRegistry:
    """Backend-enforced registry of dataset licenses, redistribution rules, and admin audit log."""

    def __init__(self) -> None:
        self._entries: dict[str, LicenseEntry] = {
            "table_public": LicenseEntry(
                dataset_id="table_public",
                original_publisher="FreeData.td / WFP / Partenaires marchés Tchad",
                original_source_url="https://freedata.td",
                license_name="Source-specific / Unverified Redistribution",
                license_version="N/A",
                license_category="unclear_licensing",
                attribution_required=True,
                attribution_text="Source primaire telle qu'enregistrée dans le champ `source` (ex. WFP, FreeData.td).",
                redistribution_allowed=False,
                commercial_use_allowed=False,
                modification_allowed=True,
                access_restrictions="Usage interne d'analyse ; redistribution brute bloquée tant que la licence source n'est pas vérifiée.",
                last_verified_date="2026-11-18",
                publication_status="approved",
            ),
            "v_clean_markets": LicenseEntry(
                dataset_id="v_clean_markets",
                original_publisher="FreeData.AI (dérivé de table_public)",
                original_source_url="https://freedata.td",
                license_name="Derived Analytical View — Attribution Required",
                license_version="1.0",
                license_category="attribution_required",
                attribution_required=True,
                attribution_text="FreeData.AI Silver View (données sources FreeData.td / WFP).",
                redistribution_allowed=False,
                commercial_use_allowed=True,
                modification_allowed=False,
                access_restrictions="Lecture API interne uniquement.",
                last_verified_date="2026-11-18",
                publication_status="approved",
            ),
            "table_ml_forecasts": LicenseEntry(
                dataset_id="table_ml_forecasts",
                original_publisher="FreeData.AI Forecasting Engine",
                original_source_url="https://freedata-ai.onrender.com/api/v1/forecasts",
                license_name="Derived Statistical Output — Attribution Required",
                license_version="1.0",
                license_category="attribution_required",
                attribution_required=True,
                attribution_text="Prévisions FreeData.AI (calculées à partir des relevés marchés vérifiés).",
                redistribution_allowed=True,
                commercial_use_allowed=True,
                modification_allowed=False,
                access_restrictions="Lecture publique (`anon`/`authenticated`) avec attribution obligatoire.",
                last_verified_date="2026-11-18",
                publication_status="approved",
            ),
            "table_ml_credit_passport": LicenseEntry(
                dataset_id="table_ml_credit_passport",
                original_publisher="FreeData.AI Risk Engine",
                original_source_url="https://freedata-ai.onrender.com/api/v1/metadata",
                license_name="Derived Risk Index — Attribution Required",
                license_version="1.0",
                license_category="attribution_required",
                attribution_required=True,
                attribution_text="FreeData.AI Agricultural Market Risk & Stability Index (indicatif uniquement).",
                redistribution_allowed=True,
                commercial_use_allowed=True,
                modification_allowed=False,
                access_restrictions="Lecture publique (`anon`/`authenticated`) ; ne constitue pas une décision de crédit.",
                last_verified_date="2026-11-18",
                publication_status="approved",
            ),
            "table_ml_seasonality_studies": LicenseEntry(
                dataset_id="table_ml_seasonality_studies",
                original_publisher="FreeData.AI",
                original_source_url="https://freedata-ai.onrender.com",
                license_name="PRO Restricted Derived Dataset",
                license_version="1.0",
                license_category="restricted",
                attribution_required=True,
                attribution_text="FreeData.AI PRO Seasonality Studies.",
                redistribution_allowed=False,
                commercial_use_allowed=True,
                modification_allowed=False,
                access_restrictions="Accès restreint `service_role` + clé PRO (`sql/09_lock_premium_tables_rls.sql`).",
                last_verified_date="2026-11-18",
                publication_status="approved",
            ),
            "table_ml_anomalies": LicenseEntry(
                dataset_id="table_ml_anomalies",
                original_publisher="FreeData.AI",
                original_source_url="https://freedata-ai.onrender.com",
                license_name="PRO Restricted Derived Dataset",
                license_version="1.0",
                license_category="restricted",
                attribution_required=True,
                attribution_text="FreeData.AI PRO Market Anomalies.",
                redistribution_allowed=False,
                commercial_use_allowed=True,
                modification_allowed=False,
                access_restrictions="Accès restreint `service_role` + clé PRO (`sql/09_lock_premium_tables_rls.sql`).",
                last_verified_date="2026-11-18",
                publication_status="approved",
            ),
        }
        self._audit_log: list[dict[str, Any]] = []

    def list_entries(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(e.to_dict()) for e in self._entries.values()]

    def get_entry(self, dataset_id: str) -> LicenseEntry:
        if dataset_id not in self._entries:
            raise KeyError(f"Jeu de données sans licence enregistrée : {dataset_id}")
        return self._entries[dataset_id]

    def register_entry(self, entry: LicenseEntry, actor: str = "admin") -> dict[str, Any]:
        self._entries[entry.dataset_id] = entry
        self._audit_log.append({
            "timestamp_utc": _utc_now(),
            "actor": actor,
            "action": "register_license",
            "dataset_id": entry.dataset_id,
            "decision": entry.publication_status,
            "reason": f"Licence enregistrée ({entry.license_category})",
        })
        return entry.to_dict()

    def check_redistribution_allowed(self, dataset_id: str) -> bool:
        try:
            entry = self.get_entry(dataset_id)
        except KeyError:
            return False
        if entry.publication_status != "approved":
            return False
        if entry.license_category in ("restricted", "unclear_licensing"):
            return False
        return bool(entry.redistribution_allowed)

    def assert_redistribution_allowed(self, dataset_id: str) -> None:
        if dataset_id not in self._entries:
            raise PermissionError(f"Redistribution bloquée : licence manquante pour '{dataset_id}'.")
        entry = self._entries[dataset_id]
        if entry.publication_status != "approved":
            raise PermissionError(f"Redistribution bloquée : jeu de données '{dataset_id}' non approuvé ({entry.publication_status}).")
        if entry.license_category in ("restricted", "unclear_licensing") or not entry.redistribution_allowed:
            raise PermissionError(
                f"Redistribution bloquée pour '{dataset_id}' (catégorie: {entry.license_category}, redistribution_allowed={entry.redistribution_allowed})."
            )

    def get_attribution_notices(self, dataset_ids: list[str]) -> list[str]:
        notices: list[str] = []
        for did in dataset_ids:
            entry = self._entries.get(did)
            if entry and entry.attribution_required and entry.attribution_text not in notices:
                notices.append(entry.attribution_text)
        return notices

    def admin_decision(
        self,
        dataset_id: str,
        *,
        action: str,
        actor: str,
        reason: str = "",
        license_category: Optional[str] = None,
        redistribution_allowed: Optional[bool] = None,
    ) -> dict[str, Any]:
        entry = self.get_entry(dataset_id)
        if action == "approve_publication":
            entry.publication_status = "approved"
        elif action == "suspend_dataset":
            entry.publication_status = "suspended"
            entry.redistribution_allowed = False
        elif action == "review_license":
            entry.last_verified_date = _utc_now()[:10]
            if license_category:
                entry.license_category = license_category
            if redistribution_allowed is not None:
                entry.redistribution_allowed = redistribution_allowed
        elif action == "record_quality_issue":
            pass
        else:
            raise ValueError(f"Action de gouvernance invalide : {action}")

        record = {
            "timestamp_utc": _utc_now(),
            "actor": actor,
            "action": action,
            "dataset_id": dataset_id,
            "decision": entry.publication_status,
            "reason": reason,
        }
        self._audit_log.append(record)
        return {"entry": entry.to_dict(), "audit_record": record}

    def get_audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit_log)


def build_default_lineage() -> list[dict[str, Any]]:
    """Documents end-to-end lineage from raw collection to Gold published tables."""
    return [
        LineageRecord(
            derived_dataset_id="v_clean_markets",
            original_dataset_id="table_public",
            source_version="monthly-snapshot",
            collection_timestamp="dynamic (last_observed_month)",
            transformation_operations=["Standardisation noms de produits (commodity_std)", "Normalisation provinces"],
            cleaning_operations=["Conversion des unités (sac/tass/kg) vers XAF/kg", "Filtrage valeurs nulles ou <= 0"],
            aggregation_methods=["Médiane provinciale par marché et mois"],
            derived_dataset_version="sql/01_silver_v_clean_markets.sql",
            processing_software_version="1.2.0",
        ).to_dict(),
        LineageRecord(
            derived_dataset_id="table_ml_forecasts",
            original_dataset_id="v_clean_markets",
            source_version="silver-v1",
            collection_timestamp="dynamic (last_observed_month)",
            transformation_operations=["Prévision t+1", "Calcul intervalle de confiance 80 %"],
            cleaning_operations=["Exclusion séries obsolètes (> MAX_STALENESS_MONTHS)", "Calcul MAE historique"],
            aggregation_methods=["Série temporelle par (province, market_name, commodity_std)"],
            derived_dataset_version="sql/02_03_06",
            processing_software_version="1.2.0",
        ).to_dict(),
        LineageRecord(
            derived_dataset_id="table_ml_credit_passport",
            original_dataset_id="v_clean_markets",
            source_version="silver-v1",
            collection_timestamp="dynamic (last_observed_month)",
            transformation_operations=["Score stabilité 0-100", "Classe A-D et LTV indicatif"],
            cleaning_operations=["Calcul CV % et max drawdown historique"],
            aggregation_methods=["Agrégation (province, commodity_std)"],
            derived_dataset_version="sql/02_gold_ml_tables.sql",
            processing_software_version="1.2.0",
        ).to_dict(),
    ]


class PrivacyController:
    """Privacy-aware log redaction and user-initiated secure data deletion."""

    @staticmethod
    def redact_sensitive_text(text: str) -> str:
        redacted = _EMAIL_RE.sub("[EMAIL_REDACTED]", text or "")
        redacted = _KEY_RE.sub("[KEY_REDACTED]", redacted)
        return redacted

    @staticmethod
    def delete_user_data(store: Any, owner_id: str) -> dict[str, Any]:
        """Deletes all projects, contexts, conversations, messages, studies, and PDF artifacts for owner_id."""
        projects = store.list_projects(owner_id, include_archived=True, limit=200, offset=0)
        deleted_projects = 0
        for p in projects:
            store.delete_project(owner_id, p["project_id"])
            deleted_projects += 1

        import hashlib
        owner_hash = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:16]
        owner_art_dir = Path(store.artifacts_dir) / owner_hash
        deleted_artifacts = False
        if owner_art_dir.exists():
            shutil.rmtree(owner_art_dir, ignore_errors=True)
            deleted_artifacts = True

        return {
            "owner_id_hash": owner_hash,
            "deleted_projects": deleted_projects,
            "deleted_artifacts_dir": deleted_artifacts,
            "deleted_at_utc": _utc_now(),
        }

