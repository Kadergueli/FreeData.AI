"""Famille B — anomalies de prix (chat).

Calcul hors ligne : src/anomalies.py, scripts/update_anomalies.py. Stockage : table_ml_anomalies.
Cette famille ne fait que présenter les signaux déjà détectés : ce sont des SIGNAUX À VÉRIFIER, jamais un verdict.
"""
from __future__ import annotations

import re

import pandas as pd

from src.chat.lexicon import fr_commodity
from src.families.base import FamilySpec

PATTERN = re.compile(
    r"\b(?:anomalie|anomalies|anormal|anormale|anormaux|anormales|anormalement|inhabituel|inhabituelle|inhabituels|"
    r"inhabituelles|aberrant|aberrante|aberrants|aberrantes|suspect|suspecte|suspects|suspectes|"
    r"prix\s+(?:fige|figes|bloque|bloques|etrange|bizarre)|saut\s+de\s+prix|"
    r"ne\s+bouge\s+plus|ne\s+bougent\s+plus|marche\s+qui\s+(?:diverge|decroche|s\s+ecarte))\b"
)

MONTHS_WINDOW = 3
MAX_ROWS = 6

_KIND_FR = {
    "jump": "Saut de prix",
    "divergence": "Écart avec les autres marchés",
    "jump+divergence": "Saut et écart avec les autres marchés",
    "regional": "Épisode régional (plusieurs marchés à la fois : événement ou changement d'unité/de source ?)",
}


def _recent(df: pd.DataFrame, months: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    last = pd.Period(str(df["month"].max()), freq="M")
    return df[df["month"] >= str(last - (months - 1))]


def select(provider, province, commodity, months: int = MONTHS_WINDOW) -> dict:
    """Anomalies récentes filtrées ; `status` 'empty' si aucune n'est enregistrée sur la période."""
    df = _recent(getattr(provider, "anomalies_df", None), months)
    if province and not df.empty:
        df = df[df["province"] == province]
    if commodity and not df.empty:
        df = df[df["commodity_std"] == commodity]
    if df.empty:
        return {"status": "empty", "province": province, "commodity": commodity, "months": months, "items": [],
                "n_total": 0, "n_strong": 0, "quality": []}
    df = df.copy()
    df["_abs"] = df["score"].abs()
    movement = df[df["kind"].isin(_KIND_FR)].copy()
    movement["_sev"] = (movement["severity"] == "forte").astype(int)
    movement = movement.sort_values(["_sev", "_abs"], ascending=False)
    quality = df[df["kind"].isin(["stale", "stopped"])]
    return {
        "status": "ok", "province": province, "commodity": commodity, "months": months,
        "n_total": int(len(df)), "n_strong": int((df["severity"] == "forte").sum()),
        "items": movement.head(MAX_ROWS).drop(columns=["_abs", "_sev"]).to_dict(orient="records"),
        "n_movement": int(len(movement)),
        "quality": quality.head(MAX_ROWS).drop(columns=["_abs"]).to_dict(orient="records"),
        "n_quality": int(len(quality)),
    }


def _scope(d: dict) -> str:
    parts = []
    if d.get("commodity"):
        parts.append(f"du {fr_commodity(d['commodity']).lower()}")
    if d.get("province"):
        parts.append(f"à {d['province']}")
    return (" " + " ".join(parts)) if parts else ""


def format_anomalies(agent, d: dict) -> str:
    scope = _scope(d)
    if d["status"] != "ok":
        return (f"Je n'ai enregistré **aucune anomalie de prix**{scope} sur les {d['months']} derniers mois. "
                "Cela ne garantit pas que tout est normal : l'historique est court et les seuils sont prudents.")
    lines = [f"### Anomalies de prix{scope} — {d['months']} derniers mois", "",
             f"**{d['n_total']} signal(aux)** repéré(s), dont **{d['n_strong']} fort(s)**. "
             "Ce sont des signaux **à vérifier**, pas des erreurs avérées.", ""]
    if d["items"]:
        lines += ["| Produit (marché) | Mois | Type | Observé vs attendu | Écart |", "| :--- | :---: | :--- | :---: | ---: |"]
        for r in d["items"]:
            month = agent._fr_month_label(r["month"]) or r["month"]
            flag = " ⚠️" if r["severity"] == "forte" else ""
            lines.append(
                f"| **{fr_commodity(r['commodity_std'])}** ({r['province']} — {r['market_name']}) | {month} | "
                f"{_KIND_FR[r['kind']]}{flag} | {r['value']:.0f} vs {r['reference']:.0f} XAF/kg | {r['change_pct']:+.0f} % |")
        if d.get("n_movement", 0) > len(d["items"]):
            lines.append(f"\n*{d['n_movement'] - len(d['items'])} autre(s) signal(aux) de moindre intensité non affiché(s).*")
        lines.append("")
        if d.get("province") or len(d["items"]) <= 2:
            r0 = d["items"][0]
            c_fr = fr_commodity(r0["commodity_std"])
            kind = r0["kind"]
            if kind in ("divergence", "jump+divergence"):
                lines.append(
                    f"**Pourquoi cet écart de {r0['change_pct']:+.0f} % ({r0['market_name']}) ?** "
                    f"Le détecteur compare l'évolution mensuelle de **{r0['market_name']}** à la médiane des autres marchés suivis "
                    f"pour le **{c_fr}**. Le prix observé (**{r0['value']:.0f} XAF/kg**) s'écarte de **{r0['change_pct']:+.0f} %** "
                    f"du niveau attendu s'il avait suivi ses pairs (**{r0['reference']:.0f} XAF/kg**). "
                    "Causes fréquentes : arrivage ou récolte locale, variation de demande, ou erreur de relevé/d'unité."
                )
            elif kind == "jump":
                lines.append(
                    f"**Pourquoi ce saut de {r0['change_pct']:+.0f} % ({r0['market_name']}) ?** "
                    f"Le prix du **{c_fr}** est passé à **{r0['value']:.0f} XAF/kg** (vs **{r0['reference']:.0f} XAF/kg** le mois précédent), "
                    "une variation mensuelle atypique par rapport à l'historique propre de ce marché."
                )
            elif kind == "regional":
                lines.append(
                    f"**Pourquoi cet épisode régional ({r0['province']}) ?** "
                    f"Plusieurs marchés de la province ont varié dans le même sens ({r0['change_pct']:+.0f} %) sur le **{c_fr}** : "
                    "vérifiez un choc d'offre régional, une contrainte logistique ou un changement de source."
                )
            lines.append("")
    if d["quality"]:
        lines.append("**Qualité des données** (peut fausser les prévisions de ces séries) :")
        for r in d["quality"]:
            who = f"{fr_commodity(r['commodity_std'])} ({r['province']} — {r['market_name']})"
            if r["kind"] == "stopped":
                lines.append(f"- {who} : plus de relevé depuis {int(r['score'])} mois.")
            else:
                lines.append(f"- {who} : prix identique depuis {int(r['score'])} mois.")
        lines.append("")
    lines.append("Un saut peut venir d'un vrai choc (pénurie, route coupée) comme d'une erreur de relevé : "
                 "vérifiez sur le marché avant d'agir.")
    return "\n".join(lines)


def run(agent, entities: dict) -> tuple[str, dict]:
    d = select(agent.provider, entities.get("province"), entities.get("commodity"))
    return format_anomalies(agent, d), d


def intro(entities: dict, what: str, where: str) -> str:
    return f"Voici les anomalies de prix repérées{what}{where} par notre détection."


SPEC = FamilySpec(
    name="anomalies",
    label="Famille B — Anomalies de prix",
    intent="anomalies",
    pattern=PATTERN,
    router_hint="anomalies: prix anormaux, inhabituels, sauts brusques, marchés qui divergent, séries figées",
    run=run,
    intro=intro,
    gold_tables=("table_ml_anomalies",),
    offline_script="scripts/update_anomalies.py",
)
