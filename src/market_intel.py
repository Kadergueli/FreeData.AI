"""Intelligence marché : fiche produit, comparateur de marchés, pouls, panier, contexte mondial, brief d'entrée.

Principe : suivre et expliquer, jamais prédire. Toutes les fonctions sont pures (DataFrame -> dict) et chaque sortie
porte ses limites : prix de détail mensuels (pas de gros), saisonnalité indicative tant que < 3 années observées,
écarts entre marchés hors coûts de transport, de stockage, de pertes et de financement. Aucun conseil d'investissement.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from src.seasonality import MONTHS_FR, seasonal_calendar

# Produits suivis. `names` : graphies de commodity_std (comparées en minuscules). `import_exposed` : produit
# majoritairement importé -> le prix dépend aussi de coûts qui ne sont pas dans nos données.
PRODUCTS: dict[str, dict[str, Any]] = {
    "millet": {"label_fr": "Mil", "names": ["millet"], "world": None},
    "sorghum": {"label_fr": "Sorgho rouge", "names": ["sorghum (red)"], "world": None},
    "maize": {"label_fr": "Maïs blanc", "names": ["maize (white)"], "world": "World price, maize"},
    "groundnut": {"label_fr": "Arachide décortiquée", "names": ["groundnuts (shelled)"], "world": "World price, groundnuts"},
    "rice_local": {"label_fr": "Riz local", "names": ["rice (local)"], "world": None},
    "rice_imported": {"label_fr": "Riz importé", "names": ["rice (imported)"], "world": "World price, rice (Thai 5%)", "import_exposed": True},
    "sesame": {"label_fr": "Sésame", "names": ["sesame"], "world": None},
    "cowpea": {"label_fr": "Niébé", "names": ["beans (niebe)"], "world": None},
    "onion": {"label_fr": "Oignon rouge", "names": ["onions (red)"], "world": None},
    "sugar": {"label_fr": "Sucre", "names": ["sugar"], "world": "World price, sugar", "import_exposed": True},
    "wheat_flour": {"label_fr": "Farine de blé", "names": ["wheat flour"], "world": "World price, wheat (US HRW)", "import_exposed": True},
}

# Variation mensuelle absolue typique (médiane) et seuil « exceptionnel » (percentile 90), en %, calibrés sur
# l'historique v_clean_markets 2024-2026 (relevés de détail). Servent à qualifier un mouvement par rapport à
# la volatilité NORMALE du produit, pas à un seuil unique arbitraire.
VOL_REF: dict[str, tuple[float, float]] = {
    "wheat_flour": (3.2, 19.1), "rice_imported": (5.1, 26.9), "sugar": (6.4, 24.2), "sesame": (7.5, 37.0),
    "rice_local": (8.0, 25.6), "maize": (8.2, 32.8), "millet": (8.7, 28.6), "groundnut": (9.1, 36.6),
    "onion": (10.1, 44.0), "cowpea": (10.2, 37.3), "sorghum": (10.4, 32.1),
}

INPUT_INDICATORS = {
    "dap": "World price, DAP (fertiliser)",
    "urea": "World price, urea (fertiliser)",
    "crude_oil": "World price, crude oil (average)",
}

MIN_MARKETS = 3

DISCLAIMER = (
    "Indicateurs d'information fondés sur des prix de détail mensuels observés ; ce n'est ni une prévision "
    "ni un conseil d'investissement. Vérifiez les prix de gros et les coûts réels avant tout engagement."
)


def list_products() -> list[dict[str, Any]]:
    return [
        {"id": pid, "label_fr": meta["label_fr"], "world_benchmark": bool(meta.get("world")),
         "import_exposed": bool(meta.get("import_exposed"))}
        for pid, meta in PRODUCTS.items()
    ]


def normalize_product(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in PRODUCTS:
        return key
    for pid, meta in PRODUCTS.items():
        if key == meta["label_fr"].lower() or key in meta["names"]:
            return pid
    raise ValueError(f"Produit non suivi : {raw!r}. Produits : {', '.join(PRODUCTS)}.")


# ----------------------------------------------------------------------------
# Préparation des séries
# ----------------------------------------------------------------------------
def _product_frame(df: Optional[pd.DataFrame], product_id: str) -> pd.DataFrame:
    """Relevés du produit, dédoublonnés par (province, marché, mois) : WFP et FEWS NET se recoupent."""
    cols = ["province", "market_name", "ym", "value"]
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(columns=cols)
    names = PRODUCTS[product_id]["names"]
    sub = df[df["commodity_std"].astype(str).str.strip().str.lower().isin(names)].copy()
    sub = sub[pd.to_numeric(sub["value"], errors="coerce") > 0]
    if sub.empty:
        return pd.DataFrame(columns=cols)
    sub["ym"] = sub["year_month"]
    sub["province"] = sub["province"].fillna("").astype(str)
    sub["market_name"] = sub["market_name"].fillna("").astype(str)
    out = sub.groupby(["province", "market_name", "ym"], as_index=False)["value"].mean()
    return out


def _wide(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    w = frame.pivot_table(index="ym", columns=["province", "market_name"], values="value", aggfunc="mean").sort_index()
    full = pd.period_range(w.index.min(), w.index.max(), freq="M")
    return w.reindex(full)  # mois manquants explicites (NaN) : pas de comparaison entre mois non consécutifs


def _national(wide: pd.DataFrame) -> pd.Series:
    """Médiane nationale par mois (au moins MIN_MARKETS marchés observés)."""
    if wide.empty:
        return pd.Series(dtype=float)
    cnt = wide.notna().sum(axis=1)
    return wide.median(axis=1).where(cnt >= MIN_MARKETS)


def _like_for_like(wide: pd.DataFrame, lag: int) -> Optional[float]:
    """Variation médiane (%) sur `lag` mois, calculée sur les marchés présents aux deux dates (évite l'effet de composition)."""
    if wide.empty or len(wide) <= lag:
        return None
    cur, prev = wide.iloc[-1], wide.iloc[-1 - lag]
    ok = cur.notna() & prev.notna()
    if int(ok.sum()) < MIN_MARKETS:
        return None
    return float(np.median((cur[ok] / prev[ok] - 1.0) * 100.0))


def _last_valid_month(nat: pd.Series) -> Optional[pd.Period]:
    nat = nat.dropna()
    return nat.index[-1] if len(nat) else None


def _ym(p: Any) -> str:
    return str(p)


def _vol_label(product_id: str, move_pct: Optional[float]) -> dict[str, Any]:
    typical, p90 = VOL_REF.get(product_id, (8.0, 30.0))
    if move_pct is None:
        return {"typical_monthly_move_pct": typical, "exceptional_move_pct": p90, "label": "indisponible"}
    a = abs(move_pct)
    label = "dans la normale" if a <= typical else ("mouvement notable" if a <= p90 else "mouvement exceptionnel")
    return {"typical_monthly_move_pct": typical, "exceptional_move_pct": p90, "label": label}


def _direction(move_pct: Optional[float], product_id: str) -> str:
    if move_pct is None:
        return "indisponible"
    typical = VOL_REF.get(product_id, (8.0, 30.0))[0]
    if abs(move_pct) <= typical * 0.5:
        return "stable"
    return "hausse" if move_pct > 0 else "baisse"


def _seasonality(df: pd.DataFrame, product_id: str) -> dict[str, Any]:
    names = PRODUCTS[product_id]["names"]
    sub = df[df["commodity_std"].astype(str).str.strip().str.lower().isin(names)]
    if sub.empty:
        return {"status": "insufficient_data"}
    commodity = str(sub["commodity_std"].iloc[0])
    try:
        cal = seasonal_calendar(sub, commodity)
    except Exception:  # noqa: BLE001 - la saisonnalité est un plus, jamais bloquante
        return {"status": "insufficient_data"}
    if cal.get("status") != "ok":
        return {"status": "insufficient_data"}
    years = int(cal.get("min_years_observed", 0))
    prof = cal["profile"]
    return {
        "status": "ok",
        "reliable": bool(cal["reliable"]),
        "label": "fiable (≥3 saisons)" if cal["reliable"] else f"indicative ({years} saison(s) observée(s))",
        "buy_months": [MONTHS_FR[m - 1] for m in cal["buy_months"]],
        "sell_months": [MONTHS_FR[m - 1] for m in cal["sell_months"]],
        "buy_month_numbers": cal["buy_months"],
        "sell_month_numbers": cal["sell_months"],
        "buy_discount_pct": round(cal["buy_discount_pct"], 1),
        "sell_premium_pct": round(cal["sell_premium_pct"], 1),
        "amplitude_pct": round(cal["amplitude_pct"], 1),
        "min_years_observed": years,
        "profile": [
            {"month": int(r.month), "index": None if pd.isna(r.index) else round(float(r.index), 3)}
            for r in prof.itertuples()
        ],
    }


def _limits(product_id: str, n_markets: int, n_months: int, seasonality: dict) -> list[str]:
    out = ["Prix de détail mensuels depuis 2024 (pas de prix de gros).", "Les prix sont en XAF/kg."]
    if PRODUCTS[product_id].get("import_exposed"):
        out.append("Produit largement importé : son prix dépend de coûts (change, transport, taxes) absents de nos données.")
    if not PRODUCTS[product_id].get("world"):
        out.append("Pas de prix mondial de référence disponible pour ce produit.")
    if seasonality.get("status") == "ok" and not seasonality.get("reliable"):
        out.append("Saisonnalité calculée sur moins de 3 années : à lire comme une tendance, pas une règle.")
    if seasonality.get("status") != "ok":
        out.append("Historique insuffisant pour une saisonnalité.")
    if n_markets < 8:
        out.append(f"Couverture limitée : {n_markets} marché(s) observé(s) le dernier mois.")
    if n_months < 24:
        out.append(f"Historique court : {n_months} mois observés.")
    return out


# ----------------------------------------------------------------------------
# 1. Fiche produit (Standard)
# ----------------------------------------------------------------------------
def product_brief(df: Optional[pd.DataFrame], product_id: str) -> dict[str, Any]:
    pid = normalize_product(product_id)
    meta = PRODUCTS[pid]
    base = {"product_id": pid, "label_fr": meta["label_fr"], "unit": "XAF/kg", "disclaimer": DISCLAIMER}
    frame = _product_frame(df, pid)
    wide = _wide(frame)
    nat = _national(wide)
    last = _last_valid_month(nat)
    if last is None:
        return {**base, "status": "insufficient_data", "limits": ["Pas assez de marchés observés pour ce produit."]}
    wide = wide.loc[:last]
    nat = nat.loc[:last]
    cur_markets = int(wide.iloc[-1].notna().sum())
    mom = _like_for_like(wide, 1)
    qoq = _like_for_like(wide, 3)
    yoy = _like_for_like(wide, 12)
    series = nat.dropna()
    last12 = series.tail(12)
    pct_rank = float((series <= series.iloc[-1]).mean() * 100.0)
    seas = _seasonality(df, pid)
    return {
        **base,
        "status": "ok",
        "as_of": _ym(last),
        "national_median_xaf_kg": round(float(series.iloc[-1]), 1),
        "n_markets": cur_markets,
        "mom_pct": None if mom is None else round(mom, 1),
        "three_month_pct": None if qoq is None else round(qoq, 1),
        "yoy_pct": None if yoy is None else round(yoy, 1),
        "direction": _direction(mom, pid),
        "volatility": _vol_label(pid, mom),
        "range_12m": {"min": round(float(last12.min()), 1), "max": round(float(last12.max()), 1)},
        "percentile_vs_history": round(pct_rank, 0),
        "history_months": int(series.shape[0]),
        "seasonality": seas,
        "series": [{"month": _ym(i), "value": round(float(v), 1)} for i, v in series.tail(24).items()],
        "world_benchmark_available": bool(meta.get("world")),
        "limits": _limits(pid, cur_markets, int(series.shape[0]), seas),
    }


# ----------------------------------------------------------------------------
# 2. Comparateur de marchés + fenêtre de stockage (PRO)
# ----------------------------------------------------------------------------
def market_comparison(
    df: Optional[pd.DataFrame],
    product_id: str,
    *,
    storage_cost_pct_month: float = 0.0,
    loss_pct: float = 0.0,
) -> dict[str, Any]:
    pid = normalize_product(product_id)
    frame = _product_frame(df, pid)
    wide = _wide(frame)
    nat = _national(wide)
    last = _last_valid_month(nat)
    base = {"product_id": pid, "label_fr": PRODUCTS[pid]["label_fr"], "unit": "XAF/kg", "disclaimer": DISCLAIMER}
    if last is None:
        return {**base, "status": "insufficient_data", "markets": []}
    wide = wide.loc[:last]
    median = float(nat.loc[last])
    rows = []
    for (prov, mkt), col in wide.items():
        recent = col.tail(2).dropna()  # relevé du dernier mois, ou du mois précédent à défaut
        if recent.empty or "agrég" in mkt.lower():
            continue
        price = float(recent.iloc[-1])
        rows.append({
            "province": prov or "—", "market": mkt, "price_xaf_kg": round(price, 1),
            "gap_vs_median_pct": round((price / median - 1.0) * 100.0, 1),
            "month": _ym(recent.index[-1]),
        })
    rows.sort(key=lambda r: r["price_xaf_kg"])
    spread = None
    if len(rows) >= 4:
        k = max(1, len(rows) // 4)
        low = float(np.mean([r["price_xaf_kg"] for r in rows[:k]]))
        high = float(np.mean([r["price_xaf_kg"] for r in rows[-k:]]))
        spread = {
            "cheapest_quartile_xaf_kg": round(low, 1), "dearest_quartile_xaf_kg": round(high, 1),
            "gross_gap_pct": round((high / low - 1.0) * 100.0, 1),
            "note": "Écart brut entre marchés, avant transport, taxes, pertes et financement.",
        }
    seas = _seasonality(df, pid)
    storage: dict[str, Any] = {"status": "insufficient_data"}
    if seas.get("status") == "ok":
        idx = {p["month"]: p["index"] for p in seas["profile"] if p["index"] is not None}
        buy = min(seas["buy_month_numbers"], key=lambda m: idx.get(m, 9))
        sell = max(seas["sell_month_numbers"], key=lambda m: idx.get(m, 0))
        months = (sell - buy) % 12 or 12
        gross = (idx[sell] / idx[buy] - 1.0) * 100.0
        net = gross - storage_cost_pct_month * months - loss_pct
        storage = {
            "status": "ok", "buy_month": MONTHS_FR[buy - 1], "sell_month": MONTHS_FR[sell - 1],
            "months_stored": months, "gross_gain_pct": round(gross, 1),
            "storage_cost_pct_month": storage_cost_pct_month, "loss_pct": loss_pct,
            "net_gain_pct": round(net, 1), "reliability": seas["label"], "reliable": seas["reliable"],
            "verdict": ("Gain brut positif après vos coûts saisis." if net > 0 else
                        "Gain nul ou négatif après vos coûts saisis : stocker n'est pas justifié par la saisonnalité seule."),
            "note": "Gain théorique moyen. Il ignore le financement, le risque de prix et les variations d'une année à l'autre.",
        }
    return {**base, "status": "ok", "as_of": _ym(last), "national_median_xaf_kg": round(median, 1),
            "markets": rows, "spread": spread, "storage_window": storage}


# ----------------------------------------------------------------------------
# 3. Pouls du marché (PRO)
# ----------------------------------------------------------------------------
def market_pulse(df: Optional[pd.DataFrame]) -> dict[str, Any]:
    items = []
    for pid, meta in PRODUCTS.items():
        b = product_brief(df, pid)
        if b["status"] != "ok":
            continue
        typical = VOL_REF.get(pid, (8.0, 30.0))[0]
        score = abs(b["mom_pct"]) / typical if b["mom_pct"] is not None else 0.0
        items.append({
            "product_id": pid, "label_fr": meta["label_fr"], "as_of": b["as_of"],
            "price_xaf_kg": b["national_median_xaf_kg"], "mom_pct": b["mom_pct"], "yoy_pct": b["yoy_pct"],
            "direction": b["direction"], "volatility_label": b["volatility"]["label"],
            "percentile_vs_history": b["percentile_vs_history"], "intensity": round(score, 2),
        })
    items.sort(key=lambda i: i["intensity"], reverse=True)
    up = sum(1 for i in items if i["direction"] == "hausse")
    down = sum(1 for i in items if i["direction"] == "baisse")
    return {
        "status": "ok" if items else "insufficient_data",
        "items": items,
        "summary": {"rising": up, "falling": down, "stable": len(items) - up - down, "tracked": len(items)},
        "headline": (items[0]["label_fr"] + " : " + items[0]["volatility_label"]) if items else None,
        "disclaimer": DISCLAIMER,
    }


# ----------------------------------------------------------------------------
# 4. Panier de matières premières (PRO)
# ----------------------------------------------------------------------------
def commodity_basket(df: Optional[pd.DataFrame], weights: Optional[dict[str, float]] = None) -> dict[str, Any]:
    weights = weights or {"millet": 1, "sorghum": 1, "maize": 1, "rice_local": 1}
    clean: dict[str, float] = {}
    for k, v in weights.items():
        pid = normalize_product(k)
        w = float(v)
        if not np.isfinite(w) or w <= 0:
            raise ValueError("Les pondérations doivent être strictement positives.")
        clean[pid] = clean.get(pid, 0.0) + w
    if len(clean) < 2 or len(clean) > 8:
        raise ValueError("Un panier contient entre 2 et 8 produits.")
    series = {}
    for pid in clean:
        s = _national(_wide(_product_frame(df, pid))).dropna()
        if len(s) >= 12:
            series[pid] = s
    if len(series) < 2:
        return {"status": "insufficient_data", "disclaimer": DISCLAIMER}
    table = pd.DataFrame(series).dropna()  # mois communs à tous les produits retenus
    if len(table) < 12:
        return {"status": "insufficient_data", "disclaimer": DISCLAIMER}
    tot = sum(clean[p] for p in table.columns)
    w = {p: clean[p] / tot for p in table.columns}
    rebased = table / table.iloc[0] * 100.0
    index = sum(rebased[p] * w[p] for p in table.columns)

    def _chg(lag: int) -> Optional[float]:
        return None if len(index) <= lag else round(float((index.iloc[-1] / index.iloc[-1 - lag] - 1) * 100), 1)

    contrib = []
    if len(table) > 12:
        for p in table.columns:
            ch = float(table[p].iloc[-1] / table[p].iloc[-13] - 1) * 100
            contrib.append({"product_id": p, "label_fr": PRODUCTS[p]["label_fr"], "weight": round(w[p], 3),
                            "change_12m_pct": round(ch, 1), "contribution_pts": round(ch * w[p], 1)})
        contrib.sort(key=lambda c: abs(c["contribution_pts"]), reverse=True)
    return {
        "status": "ok", "base_month": _ym(table.index[0]), "as_of": _ym(table.index[-1]),
        "index": round(float(index.iloc[-1]), 1), "mom_pct": _chg(1), "yoy_pct": _chg(12),
        "series": [{"month": _ym(i), "value": round(float(v), 1)} for i, v in index.tail(24).items()],
        "components": contrib, "excluded": [p for p in clean if p not in table.columns],
        "note": "Indice pondéré des médianes nationales (base 100 au premier mois commun). Les pondérations sont les vôtres.",
        "disclaimer": DISCLAIMER,
    }


# ----------------------------------------------------------------------------
# 5. Contexte mondial et intrants (PRO)
# ----------------------------------------------------------------------------
def _world_series(world: pd.DataFrame, indicator: str) -> pd.Series:
    sub = world[world["indicator"] == indicator].sort_values("month")
    return pd.Series(sub["value"].to_numpy(float), index=sub["month"].to_numpy()) if not sub.empty else pd.Series(dtype=float)


def _world_block(s: pd.Series, unit: str) -> Optional[dict[str, Any]]:
    if s.empty:
        return None
    last = s.index[-1]
    yoy = None
    prev = pd.Period(last, freq="M") - 12
    if prev in s.index and s.loc[prev] > 0:
        yoy = round(float((s.iloc[-1] / s.loc[prev] - 1) * 100), 1)
    stale = (pd.Period.now("M") - pd.Period(last, freq="M")).n > 6 if hasattr(pd.Period, "now") else False
    return {"as_of": _ym(last), "value": round(float(s.iloc[-1]), 2), "unit": unit, "yoy_pct": yoy,
            "series": [{"month": _ym(i), "value": round(float(v), 2)} for i, v in s.tail(24).items()],
            "stale": stale}


def world_context(world: Optional[pd.DataFrame], df: Optional[pd.DataFrame], product_id: Optional[str] = None) -> dict[str, Any]:
    note = ("Prix mondiaux en USD (Banque mondiale, CC BY 4.0), sans conversion en XAF. Nos tests ne montrent pas "
            "de lien fiable entre prix mondiaux et prix locaux du mois suivant : c'est un contexte, pas un signal.")
    if world is None or getattr(world, "empty", True):
        return {"status": "unavailable", "reason": "Séries mondiales indisponibles pour l'instant.", "note": note}
    out: dict[str, Any] = {"status": "ok", "note": note, "inputs": {}}
    units = world.groupby("indicator")["unit"].first().to_dict()
    for key, ind in INPUT_INDICATORS.items():
        blk = _world_block(_world_series(world, ind), units.get(ind, ""))
        if blk:
            out["inputs"][key] = blk
    if product_id:
        pid = normalize_product(product_id)
        ind = PRODUCTS[pid].get("world")
        if not ind:
            out["product"] = {"product_id": pid, "status": "no_benchmark",
                              "message": "Pas de prix mondial de référence pour ce produit."}
        else:
            blk = _world_block(_world_series(world, ind), units.get(ind, ""))
            local = product_brief(df, pid) if df is not None else {"status": "insufficient_data"}
            out["product"] = {"product_id": pid, "status": "ok" if blk else "unavailable", "world": blk,
                              "local_yoy_pct": local.get("yoy_pct") if local.get("status") == "ok" else None}
            if blk and blk["stale"]:
                out["product"]["message"] = "Série mondiale non à jour : à interpréter avec prudence."
    return out


# ----------------------------------------------------------------------------
# 6. Brief d'entrée marché (PRO)
# ----------------------------------------------------------------------------
_CHECKLIST = [
    "Quel prix de gros et quel prix au producteur pratiquent mes futurs fournisseurs et clients ?",
    "Quel est mon coût réel de transport, de stockage et de pertes jusqu'au marché visé ?",
    "Ai-je un acheteur identifié, ou dépends-je du prix du jour ?",
    "Quelle perte puis-je supporter si le prix varie d'un mois à l'autre autant qu'à l'ordinaire ?",
    "Mon financement tient-il jusqu'à la vente, y compris si je dois attendre un mois de plus ?",
]


def entry_brief(
    df: Optional[pd.DataFrame],
    product_id: str,
    *,
    province: Optional[str] = None,
    world: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    pid = normalize_product(product_id)
    brief = product_brief(df, pid)
    base = {"product_id": pid, "label_fr": PRODUCTS[pid]["label_fr"], "disclaimer": DISCLAIMER}
    if brief["status"] != "ok":
        return {**base, "status": "insufficient_data", "limits": brief.get("limits", [])}
    comp = market_comparison(df, pid)
    markets = comp.get("markets", [])
    if province:
        markets = [m for m in markets if m["province"].lower() == province.strip().lower()]
    risks = []
    vol = brief["volatility"]
    if vol["label"] != "dans la normale":
        risks.append(f"Le dernier mouvement mensuel ({brief['mom_pct']} %) sort de la normale de ce produit "
                     f"(± {vol['typical_monthly_move_pct']} % typique).")
    if brief["percentile_vs_history"] >= 85:
        risks.append("Le prix est dans le haut de son historique observé depuis 2024 : risque de retournement et d'achat cher.")
    if brief["percentile_vs_history"] <= 15:
        risks.append("Le prix est dans le bas de son historique observé : bon point d'entrée possible, mais vérifier la demande.")
    spread = comp.get("spread")
    if spread and spread["gross_gap_pct"] >= 30:
        risks.append(f"Écart brut de {spread['gross_gap_pct']} % entre marchés : opportunité apparente, mais les coûts logistiques peuvent l'absorber.")
    if PRODUCTS[pid].get("import_exposed"):
        risks.append("Produit importé : exposé au change, au transport et aux taxes non visibles dans nos données.")
    if brief["n_markets"] < 8:
        risks.append("Peu de marchés observés : la médiane nationale est moins représentative.")
    out = {
        **base, "status": "ok", "as_of": brief["as_of"], "province": province,
        "snapshot": {k: brief[k] for k in ("national_median_xaf_kg", "mom_pct", "three_month_pct", "yoy_pct",
                                           "direction", "range_12m", "percentile_vs_history", "n_markets")},
        "volatility": vol, "seasonality": brief["seasonality"],
        "where": {"cheapest": markets[:3], "dearest": markets[-3:][::-1], "spread": spread},
        "storage_window": comp.get("storage_window"),
        "risks": risks, "questions_before_committing": _CHECKLIST, "limits": brief["limits"],
        "series": brief["series"],
    }
    if world is not None:
        out["world"] = world_context(world, df, pid)
    return out
