from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd


def _parse_month_period(val: object) -> Optional[pd.Period]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, pd.Period):
        return val.asfreq("M")
    text = str(val).strip()
    if not text or text.lower() in ("nan", "nat", "none"):
        return None
    try:
        return pd.Period(text[:7], freq="M") if len(text) >= 7 and text[4] == "-" else pd.Period(text, freq="M")
    except Exception:
        return None


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds")


def filter_fresh(
    df: pd.DataFrame,
    month_col: str,
    max_months: int,
    reference_month: Optional[pd.Period] = None,
) -> tuple[pd.DataFrame, int]:
    """Écarte les lignes dont le mois est trop en retard sur le mois de référence (ou le plus récent de `df`).

    - `month_col` contient des mois au format 'YYYY-MM' (str) ou des pandas.Period.
    - Retourne (dataframe filtré, nombre de lignes écartées).
    - `max_months <= 0` désactive le filtre.
    """
    if df.empty or max_months is None or max_months <= 0:
        return df, 0
    months = pd.PeriodIndex(df[month_col].astype(str), freq="M")
    ref = reference_month.asfreq("M") if reference_month is not None else months.max()
    keep = np.asarray(months >= (ref - max_months))
    return df[keep].copy(), int((~keep).sum())


def assess_dataset_freshness(
    df: Optional[pd.DataFrame],
    month_col: str,
    max_staleness_months: int = 3,
    now_utc: Optional[datetime] = None,
    last_successful_computation_at: Optional[datetime] = None,
    last_publication_at: Optional[datetime] = None,
) -> dict:
    """Évalue la fraîcheur réelle d'un jeu de données par rapport à la date UTC courante."""
    ref_dt = now_utc or datetime.now(timezone.utc)
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=timezone.utc)
    else:
        ref_dt = ref_dt.astimezone(timezone.utc)
    current_period = pd.Period(f"{ref_dt.year:04d}-{ref_dt.month:02d}", freq="M")

    comp_iso = _iso_utc(last_successful_computation_at)
    pub_iso = _iso_utc(last_publication_at)

    if df is None or df.empty or month_col not in df.columns:
        return {
            "latest_observation_month": None,
            "last_successful_computation_at": comp_iso,
            "last_publication_at": pub_iso,
            "data_age_months": None,
            "freshness_status": "unavailable",
        }

    parsed = [_parse_month_period(v) for v in df[month_col].tolist()]
    valid = [p for p in parsed if p is not None]
    if not valid:
        return {
            "latest_observation_month": None,
            "last_successful_computation_at": comp_iso,
            "last_publication_at": pub_iso,
            "data_age_months": None,
            "freshness_status": "unavailable",
        }

    latest_period = max(valid)
    age_months = max(
        0,
        (current_period.year - latest_period.year) * 12 + (current_period.month - latest_period.month),
    )
    threshold = max(1, int(max_staleness_months))
    if age_months < threshold:
        status = "fresh"
    elif age_months == threshold:
        status = "aging"
    else:
        status = "stale"

    return {
        "latest_observation_month": str(latest_period),
        "last_successful_computation_at": comp_iso,
        "last_publication_at": pub_iso,
        "data_age_months": int(age_months),
        "freshness_status": status,
    }
