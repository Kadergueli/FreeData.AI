"""Persistent structured StudyContext and natural-language instruction extractor for FreeData.AI."""
from __future__ import annotations

import copy
import json
import re
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

_SENSITIVE_KEY_RE = re.compile(r"(?:api_key|secret|token|password|credential|x[-_]premium[-_]key|authorization)", re.IGNORECASE)
_CORRECTION_RE = re.compile(
    r"\b(?:finalement|en\s+fait|rectification|corrige[zr]?|plutot|au\s+lieu\s+de|remplace[zr]?|mets\s+plutot)\b"
)
_PDF_REQUEST_RE = re.compile(r"\b(?:pdf|telecharge[zr]?|exporter\s+en\s+pdf|generer\s+le\s+pdf|dossier\s+pro)\b")

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SWOT", re.compile(r"\bswot\b|\bforces?\s*(?:et|\/)\s*faiblesses?\b")),
    ("PESTEL", re.compile(r"\bpestel\b")),
    ("competitor_analysis", re.compile(r"\b(?:concurren(?:ce|ts?|tielle)|competitor)\b")),
    ("operational_recommendations", re.compile(r"\brecommandations?\s+operationnelles?\b")),
    ("market_study", re.compile(r"\betude\s+de\s+(?:marche|prefaisabilite|faisabilite)\b")),
    ("business_plan", re.compile(r"\bbusiness\s*plan\b|\bplan\s+d['’]?affaires?\b")),
    ("field_validation", re.compile(r"\b(?:validation\s+terrain|checklist\s+terrain)\b")),
    ("stress_tests", re.compile(r"\bstress[-\s]?tests?\b|\btests?\s+de\s+resistance\b")),
    ("six_month_projection", re.compile(r"\b(?:projection\s+6\s+mois|compte\s+d['’]?exploitation)\b")),
    ("marketing", re.compile(r"\bmarketing\b")),
]

_ADD_VERB_RE = re.compile(r"\b(?:inclure|inclus|ajoute[zr]?|avec|integre[zr]?|rajoute[zr]?|mets|mettre)\b")
_REMOVE_VERB_RE = re.compile(r"\b(?:exclure|exclus|retire[zr]?|supprime[zr]?|enleve[zr]?|sans|pas\s+de|omets|omettre)\b")

_OBJECTIVE_RE = re.compile(
    r"\b(?:mon\s+objectif\s+est|objectif\s*:|je\s+vise|viser|obtenir\s+un\s+financement|bancable|rentabilite)\b"
)
_CUSTOMER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("détaillants", re.compile(r"\bdetaillants?\b")),
    ("grossistes", re.compile(r"\bgrossistes?\b")),
    ("demi-grossistes", re.compile(r"\bdemi[-\s]?grossistes?\b")),
    ("restaurateurs", re.compile(r"\brestaurateurs?\b")),
    ("cantines", re.compile(r"\bcantines?\b")),
    ("ménages", re.compile(r"\bmenages?\b")),
    ("ONG / institutions", re.compile(r"\b(?:ong|institutions?|pam|wfp)\b")),
    ("transformateurs locaux", re.compile(r"\btransformateurs?\b")),
]
_SOURCE_PREF_RE = re.compile(
    r"\b(?:source\s+wfp|fews\s*net|donnees\s+verifiees|zero\s+chiffre\s+invente|pas\s+d['’]?extrapolation|uniquement\s+les\s+donnees)\b"
)


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_unique(target: list[str], item: str) -> None:
    cleaned = item.strip()
    if cleaned and cleaned not in target:
        target.append(cleaned)


def _remove_item(target: list[str], item: str) -> None:
    if item in target:
        target.remove(item)


@dataclass
class StudyContext:
    """Structured, serializable, versioned study context independent of short chat history."""

    study_id: str = field(default_factory=lambda: f"FD-CTX-{uuid.uuid4().hex[:8].upper()}")
    project_profile: str = "general"
    promoter_info: dict[str, Optional[str]] = field(
        default_factory=lambda: {"name": None, "organization": None, "role": None}
    )
    product_activity: dict[str, Any] = field(
        default_factory=lambda: {
            "commodity": None,
            "excluded_commodities": [],
            "activity_type": None,
            "quantity_kg": None,
        }
    )
    geography: dict[str, Any] = field(
        default_factory=lambda: {
            "origin_province": None,
            "dest_province": None,
            "provinces_mentioned": [],
            "excluded_provinces": [],
            "markets": [],
        }
    )
    budget_and_assumptions: dict[str, Any] = field(
        default_factory=lambda: {
            "capital_xaf": None,
            "transport_cost_per_kg": None,
            "loss_rate_pct": 5.0,
            "monthly_fixed_costs_xaf": 35000.0,
            "reinvest": True,
            "zero_capex": False,
        }
    )
    objectives: list[str] = field(default_factory=list)
    target_customers: list[str] = field(default_factory=list)
    operational_constraints: list[str] = field(default_factory=list)
    user_instructions: list[str] = field(default_factory=list)
    required_sections: list[str] = field(default_factory=list)
    excluded_sections: list[str] = field(default_factory=list)
    sources_and_evidence_preferences: list[str] = field(default_factory=list)
    report_format: str = "chat"
    report_language: str = "fr"
    missing_information: list[str] = field(default_factory=list)
    contradictions: list[dict[str, str]] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_questions: list[str] = field(default_factory=list)
    context_version: int = 1
    created_at_utc: str = field(default_factory=_utc_now_iso)
    updated_at_utc: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary stripped of any accidental credential keys."""
        raw = asdict(self)
        return _strip_sensitive_keys(raw)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "StudyContext":
        if not isinstance(data, dict):
            return cls()
        ctx = cls()
        clean = _strip_sensitive_keys(data)
        for key in (
            "study_id",
            "project_profile",
            "report_format",
            "report_language",
            "needs_clarification",
            "context_version",
            "created_at_utc",
            "updated_at_utc",
        ):
            if key in clean and clean[key] is not None:
                setattr(ctx, key, clean[key])
        for dict_key in ("promoter_info", "product_activity", "geography", "budget_and_assumptions"):
            if isinstance(clean.get(dict_key), dict):
                merged = copy.deepcopy(getattr(ctx, dict_key))
                merged.update(clean[dict_key])
                setattr(ctx, dict_key, merged)
        for list_key in (
            "objectives",
            "target_customers",
            "operational_constraints",
            "user_instructions",
            "required_sections",
            "excluded_sections",
            "sources_and_evidence_preferences",
            "missing_information",
            "contradictions",
            "clarification_questions",
        ):
            if isinstance(clean.get(list_key), list):
                setattr(ctx, list_key, list(clean[list_key]))
        return ctx

    @classmethod
    def from_json(cls, payload: str) -> "StudyContext":
        return cls.from_dict(json.loads(payload))

    def to_client_state_dict(self) -> dict[str, Any]:
        """Backward-compatible projection matching extract_client_state()."""
        known_params = {
            "commodity": self.product_activity.get("commodity"),
            "origin_province": self.geography.get("origin_province"),
            "dest_province": self.geography.get("dest_province"),
            "capital_xaf": self.budget_and_assumptions.get("capital_xaf"),
            "transport_cost_per_kg": self.budget_and_assumptions.get("transport_cost_per_kg"),
            "quantity_kg": self.product_activity.get("quantity_kg"),
            "promoter_name": self.promoter_info.get("name"),
        }
        return {
            "user_profile": self.project_profile,
            "known_params": known_params,
            "user_instructions": list(self.user_instructions),
            "missing_fields": list(self.missing_information),
            "study_context": self.to_dict(),
        }


def _strip_sensitive_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _strip_sensitive_keys(v)
            for k, v in obj.items()
            if not _SENSITIVE_KEY_RE.search(str(k))
        }
    if isinstance(obj, list):
        return [_strip_sensitive_keys(v) for v in obj]
    return obj


def extract_structured_instructions(text: str) -> dict[str, Any]:
    """Extract structured report/constraint instructions from a single natural-language message."""
    raw = (text or "").strip()
    norm = _norm(raw)
    is_correction = bool(_CORRECTION_RE.search(norm))

    add_sections: list[str] = []
    remove_sections: list[str] = []
    for clause in re.split(r"[.!?\n;,]+", raw):
        c_norm = _norm(clause)
        if not c_norm:
            continue
        has_add = bool(_ADD_VERB_RE.search(c_norm))
        has_remove = bool(_REMOVE_VERB_RE.search(c_norm))
        for sec_name, sec_re in _SECTION_PATTERNS:
            if not sec_re.search(c_norm):
                continue
            if has_remove and not has_add:
                _append_unique(remove_sections, sec_name)
            elif has_add and not has_remove:
                _append_unique(add_sections, sec_name)
            elif has_remove and has_add:
                # e.g., "sans marketing mais inclure SWOT" -> check local window around section
                m = sec_re.search(c_norm)
                prefix = c_norm[max(0, m.start() - 25):m.start()] if m else ""
                if _REMOVE_VERB_RE.search(prefix):
                    _append_unique(remove_sections, sec_name)
                else:
                    _append_unique(add_sections, sec_name)
            else:
                _append_unique(add_sections, sec_name)

    objectives: list[str] = []
    constraints: list[str] = []
    source_prefs: list[str] = []
    for clause in re.split(r"[.!?\n;]+", raw):
        c_clean = clause.strip(" -•\t")
        c_norm = _norm(c_clean)
        if not c_norm:
            continue
        if _OBJECTIVE_RE.search(c_norm):
            _append_unique(objectives, c_clean[:200])
        if _SOURCE_PREF_RE.search(c_norm):
            _append_unique(source_prefs, c_clean[:200])
        if any(
            kw in c_norm
            for kw in (
                "sans reinvestissement",
                "bfr constant",
                "sans equipement",
                "capex = 0",
                "capex=0",
                "capex 0",
                "sans capex",
                "perissable",
                "flux tendu",
                "sans stockage",
                "delai",
                "uniquement",
                "evite",
            )
        ):
            _append_unique(constraints, c_clean[:200])

    customers: list[str] = []
    for label, pat in _CUSTOMER_PATTERNS:
        if pat.search(norm):
            _append_unique(customers, label)

    report_format: Optional[str] = None
    if _PDF_REQUEST_RE.search(norm):
        report_format = "pdf"

    report_language: Optional[str] = None
    if re.search(r"\b(?:in\s+english|en\s+anglais|english\s+report)\b", norm):
        report_language = "en"
    elif re.search(r"\b(?:en\s+francais|in\s+french)\b", norm):
        report_language = "fr"

    reinvest_override: Optional[bool] = None
    if "sans reinvestissement" in norm or "bfr constant" in norm or "sans reinjection" in norm:
        reinvest_override = False
    elif re.search(r"\b(?:avec\s+reinvestissement|reinvestir\s+75|reinvestir\s+les\s+benefices)\b", norm):
        reinvest_override = True

    zero_capex_override: Optional[bool] = None
    if (
        "sans equipement" in norm
        or "pas d'equipement" in norm
        or "capex = 0" in norm
        or "capex=0" in norm
        or "capex 0" in norm
        or "sans capex" in norm
    ):
        zero_capex_override = True
    elif re.search(r"\b(?:avec\s+equipement|inclure\s+capex|capex\s+8)\b", norm):
        zero_capex_override = False

    loss_rate_pct: Optional[float] = None
    m_loss = re.search(r"\bpertes?\s*(?:de|a|:|=)?\s*(\d+(?:[.,]\d+)?)\s*%", norm)
    if m_loss:
        loss_rate_pct = float(m_loss.group(1).replace(",", "."))

    fixed_costs_xaf: Optional[float] = None
    m_fixed = re.search(r"\b(?:charges?\s+fixes?|couts?\s+fixes?)\s*(?:de|a|:|=)?\s*(\d[\d .]*)\s*(?:xaf|fcfa)?", norm)
    if m_fixed:
        digits = re.sub(r"[^\d]", "", m_fixed.group(1))
        if digits:
            fixed_costs_xaf = float(digits)

    return {
        "is_correction": is_correction,
        "add_sections": add_sections,
        "remove_sections": remove_sections,
        "objectives": objectives,
        "constraints": constraints,
        "source_prefs": source_prefs,
        "customers": customers,
        "report_format": report_format,
        "report_language": report_language,
        "reinvest_override": reinvest_override,
        "zero_capex_override": zero_capex_override,
        "loss_rate_pct": loss_rate_pct,
        "fixed_costs_xaf": fixed_costs_xaf,
    }


def apply_structured_update(
    ctx: StudyContext,
    raw_message: str,
    *,
    parsed: Optional[dict[str, Any]] = None,
    excluded_commodities: Optional[list[str]] = None,
    excluded_provinces: Optional[list[str]] = None,
    instruction_clauses: Optional[list[str]] = None,
) -> StudyContext:
    """Safely apply a partial update from a user turn to StudyContext without erasing unrelated fields."""
    info = parsed or extract_structured_instructions(raw_message)
    is_correction = bool(info["is_correction"])

    for sec in info["add_sections"]:
        if sec in info["remove_sections"]:
            ctx.contradictions.append({
                "field": "sections",
                "previous": sec,
                "new": f"exclude:{sec}",
                "message": f"Instruction contradictoire détectée dans le même message pour la section '{sec}'.",
            })
            _append_unique(
                ctx.clarification_questions,
                f"Souhaitez-vous inclure ou exclure la section « {sec} » ?",
            )
            ctx.needs_clarification = True
            continue
        if sec in ctx.excluded_sections and not is_correction:
            ctx.contradictions.append({
                "field": "sections",
                "previous": f"exclude:{sec}",
                "new": sec,
                "message": f"La section '{sec}' était précédemment exclue puis demandée.",
            })
            _append_unique(
                ctx.clarification_questions,
                f"Vous aviez exclu « {sec} » puis demandé son inclusion : confirmez-vous de l'inclure ?",
            )
            ctx.needs_clarification = True
        _remove_item(ctx.excluded_sections, sec)
        _append_unique(ctx.required_sections, sec)

    for sec in info["remove_sections"]:
        if sec in info["add_sections"]:
            continue
        if sec in ctx.required_sections and not is_correction:
            ctx.contradictions.append({
                "field": "sections",
                "previous": sec,
                "new": f"exclude:{sec}",
                "message": f"La section '{sec}' était précédemment demandée puis exclue.",
            })
            _append_unique(
                ctx.clarification_questions,
                f"Vous aviez demandé « {sec} » puis son exclusion : confirmez-vous de la retirer ?",
            )
            ctx.needs_clarification = True
        _remove_item(ctx.required_sections, sec)
        _append_unique(ctx.excluded_sections, sec)

    for obj in info["objectives"]:
        _append_unique(ctx.objectives, obj)
    for cust in info["customers"]:
        _append_unique(ctx.target_customers, cust)
    for con in info["constraints"]:
        _append_unique(ctx.operational_constraints, con)
    for src in info["source_prefs"]:
        _append_unique(ctx.sources_and_evidence_preferences, src)
    for cl in instruction_clauses or []:
        _append_unique(ctx.user_instructions, cl)

    if info["report_format"]:
        ctx.report_format = info["report_format"]
    if info["report_language"]:
        ctx.report_language = info["report_language"]
    if info["reinvest_override"] is not None:
        ctx.budget_and_assumptions["reinvest"] = info["reinvest_override"]
    if info["zero_capex_override"] is not None:
        ctx.budget_and_assumptions["zero_capex"] = info["zero_capex_override"]
    if info["loss_rate_pct"] is not None:
        ctx.budget_and_assumptions["loss_rate_pct"] = min(max(info["loss_rate_pct"], 0.0), 50.0)
    if info["fixed_costs_xaf"] is not None:
        ctx.budget_and_assumptions["monthly_fixed_costs_xaf"] = max(info["fixed_costs_xaf"], 0.0)

    for comm in excluded_commodities or []:
        _append_unique(ctx.product_activity["excluded_commodities"], comm)
        if ctx.product_activity.get("commodity") == comm and not is_correction:
            ctx.contradictions.append({
                "field": "commodity",
                "previous": comm,
                "new": f"exclude:{comm}",
                "message": f"Produit '{comm}' sélectionné mais aussi exclu.",
            })
            _append_unique(
                ctx.clarification_questions,
                f"Vous avez mentionné « {comm} » mais aussi son exclusion : quel produit retenir ?",
            )
            ctx.needs_clarification = True

    for prov in excluded_provinces or []:
        _append_unique(ctx.geography["excluded_provinces"], prov)
        if ctx.geography.get("origin_province") == prov or ctx.geography.get("dest_province") == prov:
            if not is_correction:
                ctx.contradictions.append({
                    "field": "geography",
                    "previous": prov,
                    "new": f"exclude:{prov}",
                    "message": f"Province '{prov}' présente dans le corridor mais aussi exclue.",
                })
                _append_unique(
                    ctx.clarification_questions,
                    f"La province « {prov} » est dans le corridor mais vous avez demandé son exclusion : confirmez-vous ?",
                )
                ctx.needs_clarification = True

    ctx.context_version += 1
    ctx.updated_at_utc = _utc_now_iso()
    return ctx
