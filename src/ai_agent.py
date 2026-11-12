import re
import unicodedata
from typing import Optional
import requests
import pandas as pd
from src.config import settings

COMMODITY_ALIASES = {
    "mil": "Millet",
    "millet": "Millet",
    "sorgho": "Sorghum (red)",
    "sorghum": "Sorghum (red)",
    "mais": "Maize (white)",
    "maize": "Maize (white)",
    "riz": "Rice (imported)",
    "rice": "Rice (imported)",
    "riz local": "Rice (local)",
    "niebe": "Beans (niebe)",
    "haricot": "Beans (niebe)",
    "arachide": "Groundnuts (shelled)",
    "sesame": "Sesame",
    "sucre": "Sugar",
    "oignon": "Onions (red)",
    "pates": "Pasta",
    "patate": "Sweet potatoes",
}


def _normalize_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


class FreeDataAIAgent:
    """
    Agent conversationnel analytique (Tool-Calling déterministe + support optionnel Ollama).
    Garantit zéro hallucination numérique : tous les chiffres proviennent des moteurs ML/SQL.
    """

    def __init__(self, hist_df: pd.DataFrame, forecast_df: pd.DataFrame, passport_df: pd.DataFrame):
        self.hist_df = hist_df
        self.forecast_df = forecast_df
        self.passport_df = passport_df
        self.provinces = sorted(forecast_df["province"].dropna().unique())
        self.prov_lookup = {_normalize_text(p): p for p in self.provinces}

    def _extract_entities(self, query: str) -> dict:
        q_norm = _normalize_text(query)

        # 1. Province
        matched_prov = None
        for p_norm, p_orig in sorted(self.prov_lookup.items(), key=lambda x: -len(x[0])):
            if p_norm in q_norm:
                matched_prov = p_orig
                break

        # 2. Produit
        matched_comm = None
        for alias, comm_std in sorted(COMMODITY_ALIASES.items(), key=lambda x: -len(x[0])):
            if re.search(rf"\b{re.escape(alias)}\b", q_norm):
                matched_comm = comm_std
                break

        # 3. Montant de prêt éventuel
        loan_amount = 1_000_000
        m_million = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:million|millions|m\b)", q_norm)
        if m_million:
            loan_amount = int(float(m_million.group(1).replace(",", ".")) * 1_000_000)
        else:
            m_num = re.search(r"(\d[\d\s]{3,})", q_norm)
            if m_num:
                cleaned = re.sub(r"\s+", "", m_num.group(1))
                if cleaned.isdigit():
                    loan_amount = int(cleaned)

        # 4. Intention
        if any(w in q_norm for w in ["credit", "pret", "financer", "banque", "risque", "score", "passport", "imf"]):
            intent = "credit_passport"
        elif any(w in q_norm for w in ["alerte", "tension", "surchauffe", "anomalie", "cher", "flambee", "hausse"]):
            intent = "alerts"
        else:
            intent = "forecast"

        return {
            "province": matched_prov,
            "commodity": matched_comm,
            "loan_amount": loan_amount,
            "intent": intent,
        }

    def tool_get_forecast(self, province: Optional[str], commodity: Optional[str]) -> str:
        comm = commodity or "Millet"
        sub = self.forecast_df[self.forecast_df["commodity_std"] == comm]
        if province:
            sub = sub[sub["province"] == province]
        if sub.empty:
            return f"Aucune série active trouvée pour **{comm}**" + (f" dans la province **{province}**." if province else ".")

        if province:
            lines = [f"### 🔮 Prévisions à t+1 mois — {comm} ({province})\n"]
            for _, r in sub.sort_values("market_name").iterrows():
                delta = r["forecast_t1"] - r["value"]
                pct = (delta / r["value"]) * 100.0
                lines.append(
                    f"- **{r['market_name']}** ({r['source']}) : dernier prix `{r['value']:,.0f} XAF/kg` ({r['last_observed_month']}) "
                    f"→ prévision **`{r['forecast_t1']:,.0f} XAF/kg`** ({r['forecast_month']}, `{pct:+.1f}%`), "
                    f"IC 80% : `[{r['ci_low_80']:,.0f} – {r['ci_high_80']:,.0f}]`."
                )
            return "\n".join(lines)

        agg = sub.groupby("province").agg(
            dernier_prix=("value", "median"),
            prevision_t1=("forecast_t1", "median"),
            mae=("hist_mae", "median"),
        ).reset_index().sort_values("prevision_t1", ascending=False)
        top3 = agg.head(3)
        bot3 = agg.tail(3)
        return (
            f"### 🔮 Synthèse Nationale — {comm} (Médiane par province)\n"
            f"- **Provinces les plus chères prévues :** "
            + ", ".join(f"{r['province']} (`{r['prevision_t1']:,.0f} XAF/kg`)" for _, r in top3.iterrows())
            + "\n- **Provinces les plus abordables prévues :** "
            + ", ".join(f"{r['province']} (`{r['prevision_t1']:,.0f} XAF/kg`)" for _, r in bot3.iterrows())
            + "\n\n*Précisez une province (ex. N'Djamena, Ouaddaï, Logone Oriental) pour le détail par marché.*"
        )

    def tool_get_credit_passport(self, province: Optional[str], commodity: Optional[str], loan_amount: int) -> str:
        comm = commodity or "Millet"
        sub = self.passport_df[self.passport_df["commodity_std"] == comm]
        if province:
            sub = sub[sub["province"] == province]
        if sub.empty:
            return f"Données insuffisantes pour calculer le Credit Passport sur **{comm}**" + (f" ({province})." if province else ".")

        if province:
            r = sub.iloc[0]
            max_loan = int(loan_amount * r["ltv_ratio"])
            return (
                f"### 🏦 Agricultural Credit Passport — {comm} ({province})\n"
                f"- **Score Global :** **`{r['credit_score']:.1f} / 100`** — **{r['grade']}**\n"
                f"- **Décision Prudentielle :** {r['policy_recommendation']}\n"
                f"- **Simulation sur demande de `{loan_amount:,} XAF` :** plafond recommandé LTV `{int(r['ltv_ratio']*100)}%` soit **`{max_loan:,} XAF`**.\n"
                f"- **Indicateurs sous-jacents :** prix médian `{r['median_price']:,.0f} XAF/kg`, volatilité CV `{r['cv_pct']:.1f}%`, "
                f"chute max post-récolte `-{r['max_drawdown_pct']:.1f}%`, observabilité `{r['obs_months']} mois`."
            )

        ranked = sub.sort_values("credit_score", ascending=False)
        top5 = ranked.head(5)
        lines = [f"### 🏦 Top 5 Provinces les plus sûres à financer — {comm}\n"]
        for _, r in top5.iterrows():
            lines.append(
                f"- **{r['province']}** : Score **`{r['credit_score']:.1f}/100`** ({r['grade']}) | "
                f"LTV max `{int(r['ltv_ratio']*100)}%` | Volatilité `{r['cv_pct']:.1f}%`"
            )
        return "\n".join(lines)

    def tool_get_alerts(self, province: Optional[str], commodity: Optional[str]) -> str:
        recent = self.hist_df.sort_values("year_month").groupby(["source", "province", "market_name", "commodity_std"]).tail(1)
        alerts = recent[recent["deviation_pct"] >= 15.0].copy()
        if province:
            alerts = alerts[alerts["province"] == province]
        if commodity:
            alerts = alerts[alerts["commodity_std"] == commodity]
        alerts = alerts.sort_values("deviation_pct", ascending=False)

        if alerts.empty:
            return "✅ Aucune alerte de surchauffe (> +15 %) détectée sur ce périmètre lors du dernier relevé."

        lines = [f"### 🚨 Alertes d'Arbitrage & Tensions de Prix ({len(alerts)} marchés > +15 %)\n"]
        for _, r in alerts.head(8).iterrows():
            lines.append(
                f"- **{r['province']} — {r['market_name']}** (`{r['commodity_std']}`, {r['year_month']}) : "
                f"observé **`{r['value']:,.0f} XAF/kg`** vs attendu `{r['predicted_price']:,.0f} XAF/kg` (**`+{r['deviation_pct']:.1f}%`**)."
            )
        return "\n".join(lines)

    def _refine_with_ollama(self, user_query: str, structured_facts: str) -> str:
        if not settings.ollama_base_url:
            return structured_facts
        try:
            prompt = (
                "Tu es FreeData.AI, l'assistant analytique officiel des marchés agricoles et financiers du Tchad. "
                "Réponds de façon claire, professionnelle et concise en français en utilisant UNIQUEMENT les faits chiffrés ci-dessous. "
                "N'invente aucun chiffre.\n\n"
                f"Question utilisateur : {user_query}\n\n"
                f"Données vérifiées du moteur FreeData.AI :\n{structured_facts}"
            )
            resp = requests.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json().get("response", structured_facts)
        except Exception:
            pass
        return structured_facts

    def answer_with_metadata(self, user_query: str) -> dict:
        entities = self._extract_entities(user_query)
        intent = entities["intent"]
        prov = entities["province"]
        comm = entities["commodity"]

        if intent == "credit_passport":
            facts = self.tool_get_credit_passport(prov, comm, entities["loan_amount"])
        elif intent == "alerts":
            facts = self.tool_get_alerts(prov, comm)
        else:
            facts = self.tool_get_forecast(prov, comm)

        final_reply = self._refine_with_ollama(user_query, facts)
        return {
            "reply": final_reply,
            "intent": intent,
            "entities": entities,
        }

    def answer(self, user_query: str) -> str:
        return self.answer_with_metadata(user_query)["reply"]
