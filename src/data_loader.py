import logging
from pathlib import Path
from typing import Optional
import requests
import pandas as pd
from src.config import settings

logger = logging.getLogger("freedata.data")

COMMODITY_NORM = {
    "Millet (Pearl)": "Millet",
    "Sorghum (Red)": "Sorghum (red)",
    "Rice (5% Broken)": "Rice (imported)",
}


def _is_missing_source_label_error(exc: Exception) -> bool:
    """Recognizes only the missing-column error for the compatibility field."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    detail = str(exc).lower()
    if response is not None:
        try:
            detail += " " + response.text.lower()
        except Exception:
            pass
    markers = ("does not exist", "undefined column", "could not find", "schema cache", "42703", "pgrst204")
    return "commodity_source_label" in detail and any(marker in detail for marker in markers) and (
        status is None or status in (400, 404, 422)
    )


def _fetch_supabase_rest_view() -> pd.DataFrame:
    """Read v_clean_markets, including temporary compatibility with the old view schema."""
    base = settings.supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/v_clean_markets"
    headers = {
        "apikey": settings.read_key,
        "Authorization": f"Bearer {settings.read_key}",
        "Accept": "application/json",
    }
    all_rows = []
    offset = 0
    batch_size = 1000
    has_source_label = True

    while True:
        columns = "month_date,source,province,market_name,commodity_std,price_value,is_flagged_outlier"
        if has_source_label:
            columns = "month_date,source,province,market_name,commodity_source_label," + columns.split("market_name,", 1)[1]
        params = {
            "select": columns,
            "unit_clean": "eq.xaf/kg",
            # Ordre stable obligatoire : sans lui, limit/offset peut dupliquer ou sauter des lignes.
            "order": "id",
            "limit": batch_size,
            "offset": offset,
        }
        resp = requests.get(endpoint, headers=headers, params=params, timeout=30)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            if has_source_label and offset == 0 and _is_missing_source_label_error(exc):
                logger.warning(
                    "Legacy v_clean_markets view detected: falling back to commodity_std. "
                    "Distinct source indicators already merged by the old view cannot be recovered."
                )
                has_source_label = False
                continue
            raise
        batch = resp.json()
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size

    if not all_rows:
        raise ValueError("La vue v_clean_markets est vide ou inaccessible sur Supabase.")

    df_clean = pd.DataFrame(all_rows).rename(columns={"price_value": "value"})
    if "commodity_source_label" not in df_clean.columns:
        df_clean["commodity_source_label"] = df_clean["commodity_std"]
    df_clean["year_month"] = pd.to_datetime(df_clean["month_date"]).dt.to_period("M")
    return df_clean


def _load_clean_markets_raw(csv_path: Optional[str] = None) -> pd.DataFrame:
    """
    Charge et standardise les séries de marchés (unité homogène xaf/kg).
    Priorité : 1) API HTTPS Supabase, 2) PostgreSQL direct, 3) CSV local.
    """
    # Un chemin de CSV passé explicitement est toujours respecté (sinon `--csv` serait ignoré dès que Supabase est configuré).
    if csv_path is None and settings.data_backend == "supabase_rest":
        return _fetch_supabase_rest_view()

    if csv_path is None and settings.data_backend == "supabase":
        from sqlalchemy import create_engine
        engine = create_engine(settings.supabase_db_url)
        query = """
            SELECT month_date, source, province, market_name, commodity_source_label,
                   commodity_std, price_value AS value, is_flagged_outlier
            FROM public.v_clean_markets
            WHERE unit_clean = 'xaf/kg'
        """
        df_clean = pd.read_sql(query, engine)
        df_clean["year_month"] = pd.to_datetime(df_clean["month_date"]).dt.to_period("M")
        return df_clean

    target_csv = csv_path or settings.csv_path
    if not Path(target_csv).is_file():
        raise FileNotFoundError(f"Fichier CSV introuvable : {target_csv} (dossier courant : {Path.cwd()})")
    return standardize_raw_markets(pd.read_csv(target_csv))


def standardize_raw_markets(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise les relevés bruts (colonnes du CSV / de table_public) en séries XAF/kg homogènes.

    Colonnes attendues : source, reference_date, unit, value, region, indicator, notes.
    Même logique que la vue v_clean_markets.
    """
    markets = df[df["source"].isin(["WFP", "FEWS NET"])].copy()
    markets["reference_date"] = pd.to_datetime(markets["reference_date"])
    markets["year_month"] = markets["reference_date"].dt.to_period("M")

    markets["unit_clean"] = markets["unit"].str.strip().str.lower()
    mask_500g = markets["unit_clean"] == "xaf/500_g"
    markets.loc[mask_500g, "value"] *= 2.0
    markets.loc[mask_500g, "unit_clean"] = "xaf/kg"

    mask_400g = markets["unit_clean"] == "xaf/400_g"
    markets.loc[mask_400g, "value"] *= 2.5
    markets.loc[mask_400g, "unit_clean"] = "xaf/kg"

    is_wfp = markets["source"] == "WFP"
    markets.loc[is_wfp, "province"] = markets.loc[is_wfp, "region"].str.extract(r"\(([^()]+)\)$")[0]
    markets.loc[is_wfp, "market_name"] = markets.loc[is_wfp, "region"].str.replace(r"\s*\([^()]+\)$", "", regex=True)
    markets.loc[is_wfp, "commodity"] = markets.loc[is_wfp, "indicator"].str.replace(r"\s+retail price \(WFP\)$", "", regex=True)
    markets.loc[is_wfp & (markets["commodity"] == "Sorghum"), "commodity"] = "Sorghum (red)"

    is_fews = markets["source"] == "FEWS NET"
    extracted = markets.loc[is_fews, "indicator"].str.extract(r"^(.*?)\s+price\s+\(retail\)(?:\s+-\s+(.*))?$")
    markets.loc[is_fews, "province"] = markets.loc[is_fews, "region"]
    markets.loc[is_fews, "commodity"] = extracted[0]
    markets.loc[is_fews, "market_name"] = extracted[1].fillna(markets.loc[is_fews, "region"] + " (Agrégé)")

    markets["is_flagged_outlier"] = markets["notes"].str.contains("OUTLIER", na=False).astype(int)
    # Preserve the source label for auditability and distinct market-price series.
    markets["commodity_source_label"] = markets["commodity"]
    markets["commodity_std"] = markets["commodity"].replace(COMMODITY_NORM)

    return markets[markets["unit_clean"] == "xaf/kg"].copy()


def drop_flagged_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """Retire les relevés marqués comme aberrants. Ne modifie aucune autre valeur."""
    if "is_flagged_outlier" not in df.columns:
        return df
    flagged = pd.to_numeric(df["is_flagged_outlier"], errors="coerce").fillna(0) > 0
    return df[~flagged].copy()


KEY_COLS = ["source", "province", "market_name", "commodity_std", "year_month"]


def unify_commodity_case(df: pd.DataFrame) -> pd.DataFrame:
    """Fusionne les noms de produit qui ne diffèrent que par la casse (« Wheat Flour » / « Wheat flour »).

    Ils désignent le même produit mais coupaient l'historique en deux. Le nom retenu est la graphie la plus fréquente.
    Si, après fusion, un même (source, marché, mois) apparaît deux fois, les valeurs sont moyennées.
    """
    if "commodity_std" not in df.columns or df.empty:
        return df
    names = df["commodity_std"].dropna().astype(str)
    counts = names.value_counts()
    canon = {}
    for name in counts.index:  # du plus fréquent au moins fréquent
        canon.setdefault(name.strip().lower(), name)
    mapping = {name: canon[name.strip().lower()] for name in counts.index}
    if all(k == v for k, v in mapping.items()):
        return df
    df = df.copy()
    df["commodity_std"] = df["commodity_std"].map(mapping).fillna(df["commodity_std"])
    if {"value", *KEY_COLS} <= set(df.columns) and df.duplicated(KEY_COLS).any():
        other = [c for c in df.columns if c not in KEY_COLS + ["value"]]
        agg = {"value": "mean", **{c: "max" if c == "is_flagged_outlier" else "first" for c in other}}
        df = df.groupby(KEY_COLS, as_index=False, dropna=False).agg(agg)
    return df


def load_clean_markets(csv_path: Optional[str] = None) -> pd.DataFrame:
    """Charge les séries XAF/kg puis (par défaut) écarte les relevés aberrants avant le modèle."""
    df = unify_commodity_case(_load_clean_markets_raw(csv_path))
    if settings.exclude_flagged_outliers:
        before = len(df)
        df = drop_flagged_outliers(df)
        removed = before - len(df)
        if removed:
            logger.info("%d relevés marqués OUTLIER écartés avant le modèle.", removed)
    return df
