"""Mise en forme des réponses du chat (faits formatés en Markdown)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from src import families
from src.chat.lexicon import (
    fr_commodity,
    _CITY_CANONICAL_HINTS,
    _fmt_int,
    _fmt_num,
    _fmt_pct,
    _fmt_signed_int,
    _normalize_text,
)
from src.chat.patterns import _SMALLTALK_HOW_RE, _SMALLTALK_IDENTITY_RE, _SMALLTALK_THANKS_RE
from src.disclaimers import CREDIT_PASSPORT_DISCLAIMER


class FormattersMixin:
    """Méthodes de formatage et d'outils de présentation, partagées par l'agent."""

    @staticmethod
    def _fr_month_label(ym: Optional[str]) -> Optional[str]:
        months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                  "août", "septembre", "octobre", "novembre", "décembre"]
        try:
            year, month = str(ym).split("-")[:2]
            return f"{months[int(month) - 1]} {year}"
        except (ValueError, IndexError, AttributeError):
            return None

    def tool_get_greeting(self, now: Optional[datetime] = None) -> str:
        """Message d'accueil professionnel : salutation selon l'heure (Tchad, UTC+1), périmètre réel des données, pistes."""
        ov = self.provider.get_overview()
        local = now or datetime.now(timezone(timedelta(hours=1)))
        hello = "Bonjour" if local.hour < 18 else "Bonsoir"
        intro = f"**{hello} et bienvenue sur FreeData.AI.**\n\n"
        if ov.get("status") != "ok":
            scope = "Je vous accompagne dans l'analyse des marchés agricoles du Tchad."
        else:
            sources = " et ".join(ov["sources"]) if ov.get("sources") else "sources publiques"
            fresh = self._fr_month_label(ov.get("period_end"))
            fresh_txt = f", dernier relevé : {fresh}" if fresh else ""
            scope = (
                f"Je suis votre assistant d'analyse des marchés agricoles du Tchad. "
                f"Je m'appuie sur **{ov['series_count']} séries de prix** ({sources}) couvrant "
                f"**{len(ov['provinces'])} provinces**{fresh_txt}."
            )
        return (
            f"{intro}{scope}\n\n"
            f"**Ce que je peux faire pour vous**\n"
            f"- **Anticiper** l'évolution du prix d'un produit (mil, sorgho, maïs, riz…)\n"
            f"- **Détecter** les hausses de prix inhabituelles\n"
            f"- **Évaluer** le risque d'un financement agricole (Credit Passport)\n"
            f"- **Estimer** la marge d'une opération d'achat-revente entre deux provinces\n\n"
            f"**Pour commencer, vous pouvez demander :**\n"
            + "".join(f"- *{q}*\n" for q in self.provider.example_questions())
            + f"\nQuel sujet souhaitez-vous aborder ?"
        )

    def tool_handle_smalltalk(self, query: str) -> str:
        q_norm = _normalize_text(query)
        if _SMALLTALK_HOW_RE.search(q_norm):
            return (
                "Je vous remercie, tout va bien. Je suis prêt à vous accompagner sur l'analyse des marchés agricoles, "
                "les marges commerciales ou l'évaluation de financement au Tchad.\n\n"
                "Sur quelle ville, province ou produit souhaitez-vous que je vous aide ?"
            )
        if _SMALLTALK_IDENTITY_RE.search(q_norm):
            ov = self.provider.get_overview()
            return (
                f"Je suis **FreeData.AI**, votre assistant économique et agricole spécialisé sur le Tchad "
                f"({ov['series_count']} séries de prix suivies sur {len(ov['provinces'])} provinces).\n\n"
                f"Vous pouvez discuter avec moi naturellement, par exemple :\n"
                + "".join(f"- *{q}*\n" for q in self.provider.example_questions())
                + "- *« Quel est le risque de financer ce produit dans cette province ? »*"
            )
        if _SMALLTALK_THANKS_RE.search(q_norm) and not re.search(r"\b(salut|bonjour|bonsoir|hello|hey|coucou|aide|help)\b", q_norm):
            return (
                "Avec plaisir. Je reste à votre disposition pour comparer d'autres marchés, estimer une marge "
                "sur un volume ou analyser un dossier de financement. Souhaitez-vous poursuivre ?"
            )
        return self.tool_get_greeting()

    def tool_get_overview(self) -> str:
        return self._format_overview(self.provider.get_overview())

    @staticmethod
    def _format_overview(ov: dict) -> str:
        if ov.get("status") != "ok":
            return "Aucune série active n'est actuellement chargée dans le catalogue."
        provinces = ov["provinces"]
        commodities = ov["commodities_fr"]
        sources = ov["sources"]
        period_str = (
            f"{ov['period_start']} à {ov['period_end']}"
            if ov.get("period_start") and ov.get("period_end")
            else "non précisée"
        )
        return (
            f"### Couverture des données FreeData.AI\n\n"
            f"| Dimension | Détail |\n"
            f"| :--- | :--- |\n"
            f"| Séries actives suivies | **{_fmt_int(ov['series_count'])}** séries sur **{_fmt_int(ov['markets_count'])}** marchés |\n"
            f"| Période observée | {period_str} |\n"
            f"| Sources | {', '.join(sources) if sources else 'Non précisées'} |\n\n"
            f"**Provinces ({len(provinces)}) :** {', '.join(provinces)}\n\n"
            f"**Produits suivis ({len(commodities)}) :** {', '.join(commodities)}"
        )

    def tool_get_forecast(
        self,
        province: Optional[str],
        commodity: Optional[str],
        focus_city: Optional[str] = None,
    ) -> str:
        comm = commodity or "Millet"
        data = self.provider.get_forecasts(province=province, commodity=comm, focus_city=focus_city)
        return self._format_forecasts(data, province=province, commodity=comm, focus_city=focus_city)

    @staticmethod
    def _format_forecasts(
        data: dict,
        province: Optional[str],
        commodity: Optional[str],
        focus_city: Optional[str] = None,
        city_commodities: Optional[dict] = None,
    ) -> str:
        comm_fr = data.get("commodity_fr") or fr_commodity(commodity or "Millet")
        if data.get("status") != "ok":
            return f"Aucune série active trouvée pour **{comm_fr}**" + (f" dans la province **{province}**." if province else ".")

        if province:
            records = data["records"]
            focus = records[0]
            focus_hint = _CITY_CANONICAL_HINTS.get(_normalize_text(focus_city or ""), _normalize_text(focus_city or ""))
            focus_matches = bool(focus_hint and focus_hint in _normalize_text(focus["market_name"]))
            heading = (
                f"### Prévisions — {comm_fr} à {focus['market_name']} ({province})"
                if focus_matches
                else f"### Prévisions — {comm_fr} ({province})"
            )

            lines = [heading, ""]
            obs_str = f"{_fmt_int(focus.get('last_observed_price'))} XAF/kg"
            fc_str = f"{_fmt_int(focus.get('forecast_t1'))} XAF/kg"
            sac_str = f"{_fmt_int(focus.get('sac_100kg_xaf'))} XAF"
            pct_str = _fmt_pct(focus.get("delta_pct"))

            lines.append("**En bref :**")
            lines.append(
                f"- **{focus['market_name']} :** **{obs_str}** ({focus['last_observed_month']}) → "
                f"**{fc_str}** prévus en {focus['forecast_month']} (**{pct_str}**, soit **{sac_str}** / sac de 100 kg)"
            )

            ps = data.get("province_summary") or {}
            if len(records) >= 2 and ps.get("spread_xaf", 0) > 0:
                lines.append(
                    f"- **Fourchette dans la province ({len(records)} marchés) :** "
                    f"de **{_fmt_int(ps['min_forecast_xaf'])} XAF/kg** ({ps['min_market']}) "
                    f"à **{_fmt_int(ps['max_forecast_xaf'])} XAF/kg** ({ps['max_market']}) "
                    f"— écart de **{_fmt_int(ps['spread_sac_100kg_xaf'])} XAF** par sac de 100 kg"
                )

            lines.append("")
            if len(records) >= 2:
                lines.append(f"**Détail par marché ({comm_fr})** *(XAF/kg · prévision {focus['forecast_month']})*")
                lines.append("")
                lines.append("| Marché | Actuel → Prévu | Sac 100 kg |")
                lines.append("| :--- | :---: | ---: |")
                for idx, r in enumerate(records):
                    mkt_label = f"**{r['market_name']}**" if idx == 0 else r["market_name"]
                    obs_v = _fmt_int(r.get("last_observed_price"))
                    fc_v = _fmt_int(r.get("forecast_t1"))
                    pct_v = _fmt_pct(r.get("delta_pct"))
                    sac_v = _fmt_int(r.get("sac_100kg_xaf"))
                    lines.append(f"| {mkt_label} | {obs_v} → **{fc_v}** ({pct_v}) | {sac_v} XAF |")
            else:
                lines.append(f"| Indicateur ({focus['market_name']}) | Valeur |")
                lines.append("| :--- | ---: |")
                lines.append(f"| Dernier prix observé ({focus['last_observed_month']}) | **{obs_str}** |")
                lines.append(f"| Prévision ({focus['forecast_month']}) | **{fc_str}** ({pct_str}) |")
                lines.append(f"| Prix du sac (100 kg) | **{sac_str}** |")

            if city_commodities and city_commodities.get("status") == "ok" and city_commodities.get("records"):
                lines.extend(
                    [
                        "",
                        f"**Autres produits suivis à {city_commodities['scope_label']}** *(prix en XAF/kg)*",
                        "",
                        "| Produit | Actuel → Prévu | Sac 100 kg |",
                        "| :--- | :---: | ---: |",
                    ]
                )
                for cr in city_commodities["records"]:
                    obs_c = _fmt_int(cr.get("last_observed_price"))
                    fc_c = _fmt_int(cr.get("forecast_t1"))
                    pct_c = _fmt_pct(cr.get("delta_pct"))
                    sac_c = _fmt_int(cr.get("sac_100kg_xaf"))
                    lines.append(f"| **{cr['commodity_fr']}** | {obs_c} → **{fc_c}** ({pct_c}) | {sac_c} XAF |")

            # Repères statistiques regroupés une seule fois
            sources_list = sorted({r["source"] for r in records if r.get("source")})
            sources_str = ", ".join(sources_list) if sources_list else "Source suivie"
            stats_parts = []
            tr = data.get("track_record")
            if tr:
                span = f"Sur les {tr['months']} derniers mois, nos prévisions du {comm_fr.lower()}"
                if tr["verdict"] == "better":
                    stats_parts.append(f"- Fiabilité : {span} ont été en moyenne **{abs(tr['vs_naive_pct']):.0f} % plus justes** "
                                       "que « le prix reste celui du mois dernier ».")
                elif tr["verdict"] == "worse":
                    stats_parts.append(f"- ⚠️ Fiabilité : {span} ont été **{abs(tr['vs_naive_pct']):.0f} % moins justes** "
                                       "que « le prix reste celui du mois dernier » : à prendre avec beaucoup de prudence.")
                else:
                    stats_parts.append(f"- Fiabilité : {span} ont été **équivalentes** à « le prix reste celui du mois dernier » : "
                                       "prudence sur le détail.")
            if focus.get("reduced_quality"):
                stats_parts.append(
                    "- ⚠️ Prévision à **confiance réduite** : il manque le relevé du mois précédant le dernier relevé, "
                    "l'estimation est donc plus simple et plus incertaine."
                )
            if focus.get("ci_low_80") is not None and focus.get("ci_high_80") is not None:
                stats_parts.append(
                    f"- Fourchette probable à 80 % ({focus['market_name']}) : "
                    f"**{_fmt_int(focus['ci_low_80'])} – {_fmt_int(focus['ci_high_80'])} XAF/kg** *(IC 80%)*"
                )
            mae_vals = [r["hist_mae"] for r in records if r.get("hist_mae") is not None]
            cv_vals = [r["cv_pct"] for r in records if r.get("cv_pct") is not None]
            sub_metrics = []
            if mae_vals:
                if max(mae_vals) - min(mae_vals) < 0.2:
                    sub_metrics.append(f"Erreur moyenne historique (MAE) : **{mae_vals[0]:.1f} XAF/kg**")
                else:
                    sub_metrics.append(f"Erreur moyenne (MAE {focus['market_name']}) : **{focus['hist_mae']:.1f} XAF/kg**")
            if cv_vals:
                if max(cv_vals) - min(cv_vals) < 0.2:
                    sub_metrics.append(f"Volatilité (CV) : **{cv_vals[0]:.1f}%**")
                else:
                    sub_metrics.append(f"Volatilité (CV) : **{focus['cv_pct']:.1f}%**")
            if sub_metrics:
                stats_parts.append("- " + " · ".join(sub_metrics))

            if stats_parts:
                lines.extend(["", f"**Repères statistiques ({sources_str}) :**", *stats_parts])

            return "\n".join(lines)

        summary = data.get("national_summary") or {}
        top3 = summary.get("most_expensive_provinces") or []
        bot3 = summary.get("most_affordable_provinces") or []
        med_fc = summary.get("median_forecast_xaf")
        lines = [f"### Prévisions — Synthèse Nationale ({comm_fr})", ""]
        if med_fc is not None:
            lines.append(
                f"**En bref :** sur **{summary['provinces_count']} provinces** ({summary['series_count']} séries), "
                f"la médiane nationale prévue est de **{_fmt_int(med_fc)} XAF/kg** "
                f"*(**{_fmt_int(med_fc * 100)} XAF** / sac de 100 kg)*."
            )
            lines.append("")

        def _append_nat_table(title: str, rows: list[dict]) -> None:
            if not rows:
                return
            lines.extend([title, "", "| Province | Actuel → Prévu | Sac 100 kg |", "| :--- | :---: | ---: |"])
            for r in rows:
                obs_m = _fmt_int(r.get("median_last_observed_xaf"))
                fc_m = r.get("median_forecast_xaf")
                sac_m = _fmt_int(fc_m * 100.0 if fc_m is not None else None)
                lines.append(f"| **{r['province']}** | {obs_m} → **{_fmt_int(fc_m)} XAF** | {sac_m} XAF |")
            lines.append("")

        _append_nat_table("**Provinces les plus chères prévues :**", top3)
        _append_nat_table("**Provinces les plus abordables prévues :**", bot3)
        lines.append("*Précisez une province ou une ville (ex. Moundou, N'Djamena, Abéché, Kélo) pour le détail par marché.*")
        return "\n".join(lines)

    def tool_get_credit_passport(self, province: Optional[str], commodity: Optional[str], loan_amount: int) -> str:
        comm = commodity or "Millet"
        data = self.provider.get_credit_passport(province=province, commodity=comm, loan_amount=loan_amount)
        return self._format_credit_passport(data, province=province, commodity=comm, loan_amount=loan_amount)

    @staticmethod
    def _format_credit_passport(
        data: dict, province: Optional[str], commodity: Optional[str], loan_amount: int, loan_given: bool = True
    ) -> str:
        comm_fr = data.get("commodity_fr") or fr_commodity(commodity or "Millet")
        if data.get("status") != "ok":
            return f"Données insuffisantes pour calculer le Credit Passport sur **{comm_fr}**" + (
                f" ({province})." if province else "."
            )

        if province:
            r = data["records"][0]
            if loan_given:
                amount_rows = (
                    f"| Montant demandé | **{_fmt_int(loan_amount)} XAF** |\n"
                    f"| Plafond recommandé (LTV {r['ltv_pct']}%) | **{_fmt_int(r['recommended_max_loan_xaf'])} XAF** |\n"
                )
                closing = ""
            else:
                amount_rows = f"| Financement maximal conseillé (LTV) | **{r['ltv_pct']}%** de la valeur du stock |\n"
                closing = (
                    "\n\n**Quel montant souhaitez-vous financer ?** Indiquez-le et je vérifierai s'il respecte "
                    "le plafond recommandé pour cette filière."
                )
            return (
                f"### Agricultural Credit Passport — {comm_fr} ({province})\n\n"
                f"**Décision prudentielle :** {r['policy_recommendation']}\n\n"
                f"| Indicateur clé | Résultat |\n"
                f"| :--- | ---: |\n"
                f"| Score global | **{r['credit_score']:.1f}/100** ({r['grade']}) |\n"
                f"{amount_rows}"
                f"| Prix médian de référence | {_fmt_int(r['median_price'])} XAF/kg |\n"
                f"| Volatilité (CV) | {r['cv_pct']:.1f}% |\n"
                f"| Chute max post-récolte | -{r['max_drawdown_pct']:.1f}% |\n"
                f"| Historique observé | {r['obs_months']} mois |"
                f"{closing}"
            )

        lines = [
            f"### Agricultural Credit Passport — Top 5 Provinces ({comm_fr})",
            "",
            "| Province | Score | LTV max | Volatilité |",
            "| :--- | :---: | :---: | ---: |",
        ]
        for r in data["records"][:5]:
            lines.append(
                f"| **{r['province']}** | **{r['credit_score']:.1f}/100** ({r['grade']}) | {r['ltv_pct']}% | {r['cv_pct']:.1f}% |"
            )
        return "\n".join(lines)

    def tool_get_alerts(self, province: Optional[str], commodity: Optional[str]) -> str:
        data = self.provider.get_alerts(province=province, commodity=commodity)
        return self._format_alerts(data)

    @staticmethod
    def _format_alerts(data: dict) -> str:
        if data.get("status") != "ok":
            return "✅ Aucune alerte de surchauffe (> +15%) détectée sur ce périmètre lors du dernier relevé."

        records = data["records"]
        top = records[0]
        lines = [
            f"### Alertes d'Arbitrage & Tensions de Prix ({len(records)} marchés > +15%)",
            "",
            f"**Tension la plus forte :** **{top['province']} — {top['market_name']}** ({top['commodity_fr']}) "
            f"à **{_fmt_int(top.get('observed_price'))} XAF/kg** au lieu de {_fmt_int(top.get('predicted_price'))} XAF/kg "
            f"(**+{top['deviation_pct']:.1f}%** en {top['month']}).",
            "",
            "| Marché & Produit | Observé vs Attendu | Écart |",
            "| :--- | :---: | ---: |",
        ]
        for r in records[:8]:
            obs = f"{_fmt_int(r.get('observed_price'))}" if r.get("observed_price") is not None else "n/d"
            pred = f"{_fmt_int(r.get('predicted_price'))}" if r.get("predicted_price") is not None else "n/d"
            dev = r.get("deviation_pct") or 0.0
            lines.append(
                f"| **{r['province']} — {r['market_name']}** ({r['commodity_fr']}) | "
                f"**{obs}** vs {pred} XAF | **+{dev:.1f}%** |"
            )
        return "\n".join(lines)

    def tool_get_business_opportunities(
        self, province: Optional[str] = None, commodity: Optional[str] = None
    ) -> str:
        return self._format_opportunities(self.provider.get_business_opportunities(province=province, commodity=commodity))

    def _format_snapshot(self, d: dict) -> str:
        def table(rows: list[dict]) -> str:
            lines = ["| Produit (province) | Actuel → Prévu | Variation |", "| :--- | :---: | ---: |"]
            for r in rows:
                lines.append(f"| **{r['commodity_fr']}** ({r['province']}) | {r['last']:.0f} → **{r['forecast']:.0f}** XAF/kg | {r['delta_pct']:+.1f} % |")
            return "\n".join(lines)

        month = self._fr_month_label(d.get("forecast_month"))
        out = [f"### Faits marquants du marché{f' — prévisions de {month}' if month else ''}", "",
               f"Sur **{d['n_series']} séries** ({d['n_products']} produits, {d['n_provinces']} provinces), voici où les prix "
               "devraient le plus bouger :", ""]
        if d["rises"]:
            out += ["**Hausses attendues**", "", table(d["rises"]), ""]
        if d["falls"]:
            out += ["**Baisses attendues**", "", table(d["falls"]), ""]
        if not d["rises"] and not d["falls"]:
            out.append("Aucun mouvement notable n'est attendu : les prix devraient rester proches de leur niveau actuel.\n")
        ex = self.provider.example_questions()[0]
        out.append(f"Pour le détail, indiquez-moi un **produit** ou une **province** — par exemple {ex}")
        return "\n".join(out)

    @staticmethod
    def _format_opportunities(data: dict) -> str:
        if data.get("status") != "ok":
            return "Données insuffisantes pour identifier des opportunités commerciales sur ce périmètre."

        title_scope = f" — {data['commodity_fr']}" if data.get("commodity_fr") else ""
        lines = [f"### Opportunités Commerciales & Stratégie Marchés{title_scope}", ""]

        corridors = data.get("corridors") or []
        top_cp = data.get("top_credit_passports") or []
        if corridors or top_cp:
            lines.append("**En bref :**")
            if corridors:
                best = corridors[0]
                lines.append(
                    f"- **Meilleur écart brut :** **{best['commodity_fr']}** entre {best['low_province']} "
                    f"({_fmt_int(best['low_price'])} XAF/kg) et {best['high_province']} "
                    f"({_fmt_int(best['high_price'])} XAF/kg) soit **+{_fmt_int(best['spread_xaf'])} XAF/kg** "
                    f"(+{best['spread_pct']:.1f}%)"
                )
            if top_cp:
                safest = top_cp[0]
                lines.append(
                    f"- **Dossier le plus solide (Credit Passport) :** **{safest['province']} — {safest['commodity_fr']}** "
                    f"(**{safest['credit_score']:.1f}/100**, LTV max {safest['ltv_pct']}%)"
                )
            lines.append("")

        if data["local_focus"]:
            lines.extend(
                [
                    f"**Focus local ({data['province']}) :**",
                    "",
                    "| Produit | Actuel → Prévu | Marchés |",
                    "| :--- | :---: | ---: |",
                ]
            )
            for r in data["local_focus"]:
                lines.append(
                    f"| **{r['commodity_fr']}** | {_fmt_int(r['observed_median_xaf'])} → "
                    f"**{_fmt_int(r['forecast_median_xaf'])} XAF/kg** | {r['markets_count']} |"
                )
            lines.append("")

        lines.extend(
            [
                "**Top 3 zones d'approvisionnement (prix prévu médian le plus bas) :**",
                "",
                "| Province (Produit) | Actuel → Prévu |",
                "| :--- | ---: |",
            ]
        )
        for r in data["cheapest_zones"]:
            lines.append(
                f"| **{r['province']}** ({r['commodity_fr']}) | "
                f"{_fmt_int(r['observed_median_xaf'])} → **{_fmt_int(r['forecast_median_xaf'])} XAF/kg** |"
            )

        lines.extend(
            [
                "",
                "**Top 3 marchés de revente à plus forte valeur (prix prévu médian le plus élevé) :**",
                "",
                "| Province (Produit) | Actuel → Prévu |",
                "| :--- | ---: |",
            ]
        )
        for r in data["highest_zones"]:
            lines.append(
                f"| **{r['province']}** ({r['commodity_fr']}) | "
                f"{_fmt_int(r['observed_median_xaf'])} → **{_fmt_int(r['forecast_median_xaf'])} XAF/kg** |"
            )

        if corridors:
            lines.extend(
                [
                    "",
                    "**Écarts de prix bruts par produit (avant frais de transport) :**",
                    "",
                    "| Produit | Trajet | Écart brut |",
                    "| :--- | :--- | ---: |",
                ]
            )
            for c in corridors:
                lines.append(
                    f"| **{c['commodity_fr']}** | {c['low_province']} ({_fmt_int(c['low_price'])}) → "
                    f"{c['high_province']} ({_fmt_int(c['high_price'])}) | "
                    f"**+{_fmt_int(c['spread_xaf'])} XAF/kg** (+{c['spread_pct']:.1f}%) |"
                )

        if top_cp:
            lines.extend(
                [
                    "",
                    "**Top 3 couples (Province, Produit) les plus solides (Credit Passport) :**",
                    "",
                    "| Province — Produit | Score Credit Passport | LTV / Volatilité |",
                    "| :--- | :---: | ---: |",
                ]
            )
            for r in top_cp:
                cv = r.get("cv_pct")
                cv_str = f" · CV {cv:.1f}%" if cv is not None else ""
                lines.append(
                    f"| **{r['province']} — {r['commodity_fr']}** | **{r['credit_score']:.1f}/100** ({r['grade']}) | "
                    f"LTV {r['ltv_pct']}%{cv_str} |"
                )

        return "\n".join(lines)

    def _format_compare_sell(self, data: dict) -> str:
        if data.get("status") == "needs_commodity":
            names = " et ".join(data.get("provinces") or [])
            return (
                f"Pour comparer vos revenus entre {names}, quel **produit** souhaitez-vous vendre "
                f"(mil, sorgho, maïs, riz, oignons…) ?"
            )
        comm = fr_commodity(data["commodity"])
        rows, missing = data.get("rows") or [], data.get("missing") or []
        lines = [f"### Comparaison de vente — {comm} : {' vs '.join(data['provinces'])}", ""]
        if len(rows) >= 2:
            best, other = rows[0], rows[1]
            gap = best["price_xaf"] - other["price_xaf"]
            pct = gap / other["price_xaf"] * 100.0 if other["price_xaf"] else 0.0
            lines += [
                "| Province | Prix de vente prévu | Revenu brut pour 100 kg |",
                "| :--- | ---: | ---: |",
            ]
            for r in rows:
                lines.append(f"| **{r['province']}** | {_fmt_int(r['price_xaf'])} XAF/kg | {_fmt_int(r['price_xaf'] * 100)} XAF |")
            lines += [
                "",
                f"**Meilleure option : {best['province']}**, soit {_fmt_int(gap)} XAF/kg de plus ({_fmt_pct(pct)}) "
                f"que {other['province']}, c'est-à-dire environ {_fmt_int(gap * 100)} XAF de revenu brut en plus par sac de 100 kg.",
                "",
                "*Revenu brut = prix de vente prévu, avant coût d'achat, transport et manutention.*",
            ]
        elif rows:
            r = rows[0]
            lines.append(
                f"Je ne suis ce produit ({comm}) qu'à **{r['province']}** : prix de vente prévu **{_fmt_int(r['price_xaf'])} XAF/kg** "
                f"(≈ {_fmt_int(r['price_xaf'] * 100)} XAF pour 100 kg)."
            )
        if missing:
            if rows:
                lines.append("")
            lines.append(
                f"Aucune série de prix n'est suivie pour **{comm}** à **{', '.join(missing)}** : "
                f"je ne peux donc pas comparer ces lieux de vente."
            )
            if data.get("available"):
                alt = ", ".join(f"{a['province']} ({_fmt_int(a['price_xaf'])} XAF/kg)" for a in data["available"])
                lines.append("")
                lines.append(f"Provinces où je suis ce produit, par prix de vente prévu décroissant : {alt}. Voulez-vous comparer l'une d'elles ?")
            else:
                lines.append("")
                lines.append("Je ne suis ce produit dans aucune autre province pour le moment. Souhaitez-vous essayer un autre produit ?")
        return "\n".join(lines)

    def tool_calculate_route_revenue(
        self,
        origin_province: str,
        destination_province: str,
        commodities: Optional[list[str]] = None,
        volume_kg: Optional[float] = None,
        volume_label: Optional[str] = None,
    ) -> str:
        data = self.provider.calculate_route_revenue(
            origin_province,
            destination_province,
            commodities=commodities,
            volume_kg=volume_kg,
            volume_label=volume_label,
        )
        return self._format_route_revenue(data)

    @staticmethod
    def _format_route_revenue(data: dict) -> str:
        orig_prov = data["origin_province"]
        dest_prov = data["destination_province"]
        missing_notes = data.get("missing_notes") or []
        routes = data.get("routes") or []

        if not routes:
            if not missing_notes:
                return "Données insuffisantes pour calculer un arbitrage entre ces deux zones."
            return (
                f"Impossible de comparer **{orig_prov}** et **{dest_prov}** pour le produit demandé : "
                + "; ".join(missing_notes)
                + "."
            )

        lines = [
            f"### Arbitrage Commercial — {orig_prov} → {dest_prov}",
            "",
            "*Estimations brutes (avant frais de transport et manutention)*",
        ]
        for r in routes:
            lines.extend(
                [
                    "",
                    f"#### {r['commodity_fr']}",
                    f"- **Prix :** achat **{orig_prov}** à **{_fmt_int(r.get('origin_buy_price_xaf', r['origin_forecast_xaf']))} XAF/kg** "
                    + ("*(dernier prix constaté)*" if r.get("origin_cost_basis", "observed") == "observed" else "*(prévu, prix constaté indisponible)*")
                    + f" → revente **{dest_prov}** à "
                    f"**{_fmt_int(r['destination_forecast_xaf'])} XAF/kg** *(prévu ; dernier constaté : {_fmt_int(r['destination_observed_xaf'])})*",
                    f"- **Écart unitaire brut :** **{_fmt_signed_int(r['unit_spread_xaf'])} XAF/kg** "
                    f"(**{_fmt_pct(r['pct_spread'])}**)",
                    "",
                    "| Volume | Revenu brut | Marge brute |",
                    "| :--- | ---: | ---: |",
                    f"| Sac de 100 kg | {_fmt_int(r['sac_100kg_revenue_xaf'])} XAF | **{_fmt_signed_int(r['sac_100kg_margin_xaf'])} XAF** |",
                    f"| Tonne (1 000 kg) | {_fmt_int(r['tonne_revenue_xaf'])} XAF | **{_fmt_signed_int(r['tonne_margin_xaf'])} XAF** |",
                ]
            )
            if r.get("volume_margin_xaf") is not None:
                lines.append(
                    f"| **{r['volume_label']}** | **{_fmt_int(r['volume_revenue_xaf'])} XAF** | "
                    f"**{_fmt_signed_int(r['volume_margin_xaf'])} XAF** *(coût achat : {_fmt_int(r['volume_cost_xaf'])} XAF)* |"
                )

        if missing_notes:
            lines.append(f"\n*Séries non suivies sur l'un des deux marchés : {'; '.join(missing_notes)}.*")
        return "\n".join(lines)

    @staticmethod
    def _format_business_simulator(
        data: dict,
        mode: str,
        is_default_transport: bool = True,
        is_default_capital: bool = True,
        quantity_label: Optional[str] = None,
    ) -> str:
        """Formate la simulation P&L nette ou le guide débutant en français pédagogique sans jargon technique."""
        if mode == "trade_pnl":
            comm_fr = data.get("commodity_fr") or fr_commodity(str(data.get("commodity", "")))
            orig = data.get("origin_province") or "Origine"
            dest = data.get("dest_province") or "Destination"
            status = data.get("status")

            if status == "missing_origin_data":
                return (
                    f"### 1. Diagnostic de l'opération — {comm_fr} ({orig} → {dest})\n\n"
                    f"Aucun prix vérifié n'est actuellement suivi pour **{comm_fr}** dans la province d'origine **{orig}**.\n\n"
                    f"### 2. Hypothèses & Points de Vigilance\n"
                    f"- Sans prix d'achat mesuré à **{orig}**, il est impossible de chiffrer le coût de revient sans extrapoler.\n"
                    f"- Précisez une autre province d'approvisionnement ou un autre produit suivi (Mil, Sorgho rouge, Riz, Maïs blanc, Niébé)."
                )

            assumptions = data.get("assumptions") or {}
            cap_val = float(assumptions.get("capital_xaf", 500000.0))
            tr_val = float(assumptions.get("transport_cost_per_kg", 25.0))
            loss_val = float(assumptions.get("loss_rate_pct", 5.0))
            if is_default_transport:
                transport_note = (
                    f"*(Hypothèse transport utilisée : {_fmt_num(tr_val)} XAF/kg, pertes techniques estimées : "
                    f"{_fmt_num(loss_val)} % — précisez vos propres frais si besoin)*"
                )
            else:
                transport_note = (
                    f"- Frais de transport saisis : **{_fmt_num(tr_val)} XAF/kg** | "
                    f"Pertes techniques de manutention et d'humidité estimées : **{_fmt_num(loss_val)} %**."
                )

            if status == "missing_dest_data":
                lines = [
                    f"### 1. Diagnostic de l'opération — {comm_fr} ({orig} → {dest})",
                    "",
                    f"Aucun prix de revente n'est suivi pour **{comm_fr}** dans la province cible **{dest}** : "
                    "la simulation ne peut donc pas estimer le chiffre d'affaires ni le bénéfice final sans inventer de prix.",
                    "",
                    "### 2. Repères connus à l'achat",
                    "",
                    "| Indicateur | Valeur estimée |",
                    "| :--- | ---: |",
                    f"| Capital de référence | {_fmt_int(cap_val)} XAF |",
                    f"| Prix d'achat origine ({orig}) | {_fmt_num(data.get('buy_price'))} XAF/kg |",
                    f"| Coût de revient rendu | {_fmt_num(data.get('unit_landed_cost'))} XAF/kg |",
                    f"| Volume achetable | {_fmt_int(data.get('purchasable_kg'))} kg ({data.get('purchasable_bags_100kg', 0):.2f} sacs de 100 kg) |",
                    f"| **Seuil de rentabilité minimum** | **{_fmt_num(data.get('break_even_price_per_kg'))} XAF/kg** |",
                    "",
                    f"**Pour ne pas perdre d'argent, vous devez revendre au minimum à {_fmt_num(data.get('break_even_price_per_kg'))} XAF/kg** à **{dest}**.",
                    "",
                    "### 3. Hypothèses & Points de Vigilance",
                    transport_note,
                    "- Renseignez-vous sur le prix local du sac de 100 kg à destination pour valider si le marché dépasse ce seuil plancher.",
                ]
                return "\n".join(lines)

            is_prof = bool(data.get("is_profitable"))
            net_profit = float(data.get("net_profit_xaf") or 0.0)
            net_margin = float(data.get("net_margin_pct") or 0.0)
            verdict_title = "Opération rentable estimée" if is_prof else "Opération risquée ou déficitaire"
            verdict_detail = (
                f"Sur le corridor **{orig} → {dest}** en **{comm_fr}**, le prix prévu à destination "
                f"(**{_fmt_num(data.get('sell_price'))} XAF/kg**) dépasse le seuil de rentabilité "
                f"(**{_fmt_num(data.get('break_even_price_per_kg'))} XAF/kg**), dégageant un bénéfice net estimé de "
                f"**{_fmt_signed_int(net_profit)} XAF** (**{_fmt_pct(net_margin)}** de marge nette)."
                if is_prof
                else f"Sur le corridor **{orig} → {dest}** en **{comm_fr}**, le prix prévu à destination "
                f"(**{_fmt_num(data.get('sell_price'))} XAF/kg**) ne couvre pas le seuil de rentabilité après transport et pertes "
                f"(**{_fmt_num(data.get('break_even_price_per_kg'))} XAF/kg**), soit un résultat net de "
                f"**{_fmt_signed_int(net_profit)} XAF** (**{_fmt_pct(net_margin)}**)."
            )
            qty_context = f" *(calibré pour {quantity_label})*" if (quantity_label and is_default_capital) else ""
            cap_label_suffix = " *(hypothèse par défaut)*" if (is_default_capital and not qty_context) else ""

            lines = [
                f"### 1. Diagnostic de l'opération — {comm_fr} ({orig} → {dest})",
                "",
                f"**{verdict_title}** : {verdict_detail}",
                "",
                "### 2. Détail du Compte d'Exploitation Estimé",
                "",
                "| Poste financier & volume | Estimation |",
                "| :--- | ---: |",
                f"| Budget disponible{qty_context}{cap_label_suffix} | {_fmt_int(cap_val)} XAF |",
                f"| Capital réellement engagé | {_fmt_int(data.get('actual_invested_xaf'))} XAF |",
                f"| Volume acheté | {_fmt_int(data.get('purchasable_kg'))} kg ({data.get('purchasable_bags_100kg', 0):.2f} sacs de 100 kg) |",
                f"| Volume revendable net (après {_fmt_num(loss_val)} % de pertes) | {_fmt_num(data.get('sellable_kg'))} kg |",
                f"| Prix d'achat ({orig}) → Coût rendu | {_fmt_num(data.get('buy_price'))} → {_fmt_num(data.get('unit_landed_cost'))} XAF/kg |",
                f"| **Seuil de rentabilité minimum** | **{_fmt_num(data.get('break_even_price_per_kg'))} XAF/kg** |",
                f"| Prix de revente estimé ({dest}) | {_fmt_num(data.get('sell_price'))} XAF/kg |",
                f"| Chiffre d'affaires brut | {_fmt_int(data.get('gross_revenue_xaf'))} XAF |",
                f"| Marge brute (hors transport) | {_fmt_signed_int(data.get('gross_margin_xaf'))} XAF |",
                f"| **Résultat d'exploitation estimé** | **{_fmt_signed_int(net_profit)} XAF** |",
                f"| **Rentabilité sur capital engagé (ROIC)** | **{_fmt_pct(net_margin)}** |",
                "",
                "### 3. Hypothèses & Frais exclus du calcul",
                transport_note,
                "- **Frais non inclus** (à déduire selon votre activité) : sacherie, manutention, taxes de marché, stockage, main-d'œuvre, financement et assurance.",
                "- Gardez au moins **12 %** de liquidités d'urgence hors stock pour les imprévus.",
                "- Vous pouvez ajuster votre capital ou vos frais réels de transport (ex. « avec transport 35 XAF/kg ») pour recalculer immédiatement.",
            ]
            return "\n".join(lines)

        # Mode Guide Débutant (`get_beginner_market_guide`)
        cap_val = float(data.get("capital_xaf", 500000.0))
        focus_plan = data.get("focus_plan")
        tremplins = data.get("tremplin_sectors") or []
        pitfalls = data.get("pitfalls") or []
        checklist = data.get("checklist") or []

        lines: list[str] = []
        if isinstance(focus_plan, dict) and focus_plan.get("status") == "missing_data":
            lines.extend([
                f"### 1. Analyse ciblée — {focus_plan.get('commodity_fr', 'Produit')} ({focus_plan.get('requested_province') or 'Tchad'})",
                "",
                f"Aucune série active n'est actuellement disponible pour **{focus_plan.get('commodity_fr')}** "
                + (f"à **{focus_plan.get('requested_province')}**" if focus_plan.get("requested_province") else "")
                + " : je préfère ne pas inventer de prix. Voici les alternatives les mieux couvertes avec votre capital de "
                f"**{_fmt_int(cap_val)} XAF** :",
                "",
            ])
        elif isinstance(focus_plan, dict) and focus_plan.get("unit_price_xaf"):
            f_comm = focus_plan["commodity_fr"]
            f_scope = focus_plan["scope"]
            lines.extend([
                f"### 1. Plan ciblé — {f_comm} ({f_scope}) avec {_fmt_int(cap_val)} XAF",
                "",
                "| Indicateur | Estimation dynamique |",
                "| :--- | ---: |",
                f"| Capital total disponible | **{_fmt_int(cap_val)} XAF** |",
                f"| BFR opérationnel / achat de stock (80 %) | **{_fmt_int(focus_plan['stock_budget_xaf'])} XAF** |",
                f"| Budget CAPEX équipement alloué (8 %) | **{_fmt_int(focus_plan.get('capex_budget_xaf', round(cap_val * 0.08)))} XAF** *(utilisé seulement si requis)* |",
                f"| Réserve de liquidités d'urgence (12 %) | **{_fmt_int(focus_plan['cash_reserve_xaf'])} XAF** |",
                f"| Prix médian observé/prévu ({f_scope}) | **{_fmt_num(focus_plan['unit_price_xaf'])} XAF/kg** ({_fmt_int(focus_plan['bag_100kg_price_xaf'])} XAF / sac 100 kg) |",
                f"| Volume achetable (sur les 80 % BFR) | **{_fmt_int(focus_plan['purchasable_kg'])} kg** ({focus_plan['purchasable_bags_100kg']:.1f} sacs de 100 kg) |",
            ])
            if focus_plan.get("credit_score") is not None:
                lines.append(
                    f"| Solidité Credit Passport | **Score {focus_plan['credit_score']:.1f}/100 ({focus_plan.get('grade', '')})** · volatilité {focus_plan.get('cv_pct', 0):.1f} % |"
                )
            lines.append("")
            if focus_plan.get("best_buy_province") and focus_plan.get("best_sell_province"):
                lines.append(
                    f"- **Repère d'arbitrage ({f_comm}) :** zone la plus abordable à **{focus_plan['best_buy_province']}** "
                    f"({_fmt_num(focus_plan['best_buy_price_xaf'])} XAF/kg) · prix le plus élevé à **{focus_plan['best_sell_province']}** "
                    f"({_fmt_num(focus_plan['best_sell_price_xaf'])} XAF/kg)."
                )
                lines.append("")
        else:
            lines.extend([
                f"### 1. Diagnostic pour débuter avec {_fmt_int(cap_val)} XAF",
                "",
                f"Pour lancer une activité agricole avec un capital de **{_fmt_int(cap_val)} XAF** tout en limitant le risque de perte, "
                f"privilégiez les denrées accessibles (prix unitaire inférieur ou égal à **450 XAF/kg**) affichant une bonne stabilité "
                f"historique et un profil Credit Passport solide, tout en conservant **12 %** de réserve de liquidités d'urgence ({_fmt_int(round(cap_val * 0.12))} XAF) et **8 %** de budget équipement ({_fmt_int(round(cap_val * 0.08))} XAF).",
                "",
            ])

        lines.append("### 2. Top 3 Filières « Tremplin » recommandées")
        if tremplins:
            lines.extend(
                [
                    "",
                    "| Filière | Province | Prix | Pouvoir d'achat | Solidité & Stabilité |",
                    "| :--- | :--- | ---: | ---: | :--- |",
                ]
            )
            for item in tremplins:
                bags_str = f"{item['purchasable_bags_100kg']:.1f} sacs de 100 kg"
                lines.append(
                    f"| **{item['commodity_fr']}** | {item['province']} | "
                    f"{_fmt_num(item['unit_price_xaf'])} XAF/kg | {bags_str} | "
                    f"Score {item['score_global']:.1f}/100 ({item['grade']}) · volatilité {item['cv_pct']:.1f} % |"
                )
        else:
            lines.append("- Aucune filière ne remplit actuellement les critères d'entrée sous 450 XAF/kg dans les données actives.")

        lines.extend(["", "### 3. 3 Pièges à éviter"])
        if pitfalls:
            for idx, p in enumerate(pitfalls, start=1):
                lines.append(
                    f"- **Piège {idx} — {p['commodity_fr']} ({p['province']}) :** {p['risk_reason']}"
                )
        else:
            lines.append("- Surveillez les denrées saisonnières périssables sans débouché pré-identifié.")

        lines.extend(["", "### 4. Checklist opérationnelle en 4 étapes"])
        for step in checklist:
            lines.append(f"{step['step']}. **{step['title']} :** {step['description']}")

        return "\n".join(lines)

    @staticmethod
    def _format_sources_section(chunks: list[dict], heading: str = "Sources documentaires associées") -> str:
        if not chunks:
            return ""
        lines = [f"### {heading}"]
        for c in chunks:
            titre = c.get("titre") or "Document"
            editeur = c.get("editeur") or "Source"
            page = c.get("page")
            page_str = f"p.{page}" if page is not None else "p.?"
            lines.append(f"- **{titre}** ({editeur}, {page_str})")
        return "\n".join(lines)

    def _availability_hint(self, commodities: Optional[list], provinces: list) -> str:
        """Quand une comparaison est impossible, propose des alternatives réellement disponibles."""
        fc = self.provider.forecast_df
        if fc is None or fc.empty:
            return ""
        provinces = [p for p in provinces if p]
        parts = []
        if commodities:
            comm = commodities[0]
            where = sorted(fc.loc[fc["commodity_std"] == comm, "province"].dropna().astype(str).unique())
            if where:
                parts.append(f"**{fr_commodity(comm)}** est suivi dans : {', '.join(where)}.")
        common = None
        for prov in provinces:
            found = set(fc.loc[fc["province"] == prov, "commodity_std"].dropna().astype(str))
            common = found if common is None else common & found
        if common:
            names = ", ".join(sorted({fr_commodity(c) for c in common}))
            parts.append(f"Entre {' et '.join(provinces)}, je peux comparer : {names}.")
        if not parts:
            return ""
        return "\n\n" + " ".join(parts) + "\n\nSouhaitez-vous essayer l'une de ces options ?"

    @staticmethod
    def _ask_capital_response(entities: dict) -> dict:
        return {
            "reply": (
                "**Avec plaisir, construisons votre projet pas à pas.**\n\n"
                "Pour vous proposer des pistes réalistes à partir des prix réels du marché, j'ai besoin de "
                "connaître votre point de départ :\n"
                "1. **Votre capital de départ** : le montant que vous souhaitez investir, à votre convenance\n"
                "2. **Votre zone** : ville ou province (facultatif)\n"
                "3. **Un produit qui vous attire** : mil, riz, oignons… (facultatif)\n\n"
                "Dès que vous m'indiquez votre capital, je vous présente les filières les plus accessibles, "
                "leur stabilité de prix et ce que votre budget permet d'acheter."
            ),
            "intent": "needs_capital",
            "entities": entities,
            "sources": [],
            "chart": None,
        }

    def _build_intro(self, intent: str, entities: Optional[dict]) -> str:
        """Phrase d'introduction (sans chiffre) qui reformule la demande avant les résultats."""
        e = entities or {}
        comm = fr_commodity(e["commodity"]).lower() if e.get("commodity") else None
        prov = e.get("province")
        where = f" à **{prov}**" if prov else ""
        what = f" du **{comm}**" if comm else ""
        if intent == "forecast":
            return f"Voici l'analyse des prix{what}{where} d'après les prévisions de notre modèle."
        if intent == "alerts":
            return f"Voici les signaux de tension sur les prix{' pour le ' + comm if comm else ''}{where}, repérés par notre modèle."
        if intent == "credit_passport":
            base = f"Voici l'évaluation du risque de financement{what}{where}."
            if not e.get("loan_amount_given", True):
                base += " Le montant à financer reste à votre appréciation : indiquez-le-moi pour que je le confronte au plafond recommandé."
            return base
        family = families.by_intent(intent)
        if family is not None:
            return family.intro(e, what, where)
        if intent == "opportunity":
            return f"Voici les écarts de prix entre provinces{what}, utiles pour choisir où acheter ou vendre."
        if intent == "compare_sell":
            return "Voici la comparaison de vos deux lieux de vente, à partir des prix prévus par notre modèle."
        if intent == "route_revenue":
            o, d = e.get("origin_province"), e.get("destination_province")
            return f"Voici l'analyse du trajet {o} → {d}{what}." if o and d else "Voici l'analyse de ce trajet commercial."
        if intent == "business_simulator":
            return "Voici une simulation construite à partir des paramètres que vous m'avez indiqués."
        if intent == "dataset_overview":
            return "Voici ce que couvrent actuellement mes données."
        return ""

    def _format_free_reply(
        self, structured_facts: str, intent: str, chunks: list[dict], entities: Optional[dict] = None
    ) -> str:
        intro = "" if structured_facts.startswith("Pour comparer vos revenus") else self._build_intro(intent, entities)
        reply = f"{intro}\n\n{structured_facts}" if intro else structured_facts
        if intent == "credit_passport" and CREDIT_PASSPORT_DISCLAIMER not in reply:
            reply = f"{reply}\n\n_{CREDIT_PASSPORT_DISCLAIMER}_"
        sources_heading = (
            "Références documentaires associées"
            if intent == "business_simulator"
            else "Sources documentaires associées"
        )
        sources_section = self._format_sources_section(chunks, heading=sources_heading)
        if sources_section:
            reply = f"{reply}\n\n{sources_section}"
        return reply

    @staticmethod
    def _extract_chart_data(intent: str, provider_data: dict) -> Optional[dict[str, float]]:
        """Extrait jusqu'à 5 barres comparatives pour l'affichage visuel `ChartCard`."""
        if not isinstance(provider_data, dict) or provider_data.get("status") != "ok":
            return None
        chart: dict[str, float] = {}
        if intent == "forecast":
            records = provider_data.get("records") or []
            if provider_data.get("province") and 2 <= len(records) <= 6:
                for r in records:
                    fc = r.get("forecast_t1")
                    if fc is not None and r.get("market_name"):
                        chart[str(r["market_name"])] = float(round(fc))
            elif not provider_data.get("province"):
                top3 = (provider_data.get("national_summary") or {}).get("most_expensive_provinces") or []
                for r in top3:
                    fc = r.get("median_forecast_xaf")
                    if fc is not None and r.get("province"):
                        chart[str(r["province"])] = float(round(fc))
        elif intent == "credit_passport" and not provider_data.get("province"):
            for r in (provider_data.get("records") or [])[:5]:
                sc = r.get("credit_score")
                if sc is not None and r.get("province"):
                    chart[str(r["province"])] = round(float(sc), 1)
        elif intent == "alerts":
            for r in (provider_data.get("records") or [])[:5]:
                dev = r.get("deviation_pct")
                if dev is not None and r.get("market_name"):
                    chart[str(r["market_name"])] = round(float(dev), 1)
        elif intent == "opportunity":
            for r in (provider_data.get("cheapest_zones") or [])[:3] + (provider_data.get("highest_zones") or [])[:2]:
                fc = r.get("forecast_median_xaf")
                prov = r.get("province")
                if fc is not None and prov and str(prov) not in chart:
                    chart[str(prov)] = float(round(fc))
        elif intent == "compare_sell":
            for r in (provider_data.get("rows") or [])[:5]:
                px = r.get("price_xaf")
                if px is not None and r.get("province"):
                    chart[str(r["province"])] = float(round(px))
        elif intent == "anomalies":
            for r in (provider_data.get("items") or [])[:5]:
                chg = r.get("change_pct")
                mkt = r.get("market_name")
                if chg is not None and mkt and str(mkt) not in chart:
                    chart[str(mkt)] = round(float(chg), 1)
        elif intent == "timing":
            bd = provider_data.get("buy_discount_pct")
            sp = provider_data.get("sell_premium_pct")
            if bd is not None and sp is not None:
                chart["Creux achat (%)"] = round(float(bd), 1)
                chart["Pic vente (%)"] = round(float(sp), 1)
        return chart if len(chart) >= 2 else None

    @staticmethod
    def _extract_summary_data(intent: str, provider_data: dict) -> Optional[dict]:
        """Extrait un bloc synthèse KPI (`title`, `items`) pour `AnalysisSummary` côté client."""
        if not isinstance(provider_data, dict) or provider_data.get("status") != "ok":
            return None
        items: list[str] = []
        title = "Synthèse de l’analyse"

        if intent == "forecast":
            comm_fr = provider_data.get("commodity_fr") or "Produit"
            prov = provider_data.get("province")
            records = provider_data.get("records") or []
            if prov and records:
                title = f"Repères — {comm_fr} ({prov})"
                top = records[0]
                if top.get("forecast_t1") is not None:
                    items.append(
                        f"{top.get('market_name', prov)} : {_fmt_int(top['forecast_t1'])} XAF/kg "
                        f"({_fmt_int(top.get('sac_100kg_xaf'))} XAF / sac 100 kg)"
                    )
                ps = provider_data.get("province_summary") or {}
                if len(records) >= 2 and ps.get("spread_xaf"):
                    items.append(
                        f"Écart inter-marchés : {_fmt_int(ps['spread_xaf'])} XAF/kg "
                        f"({_fmt_int(ps.get('spread_sac_100kg_xaf'))} XAF / sac)"
                    )
            else:
                ns = provider_data.get("national_summary") or {}
                if ns.get("median_forecast_xaf") is not None:
                    title = f"Synthèse nationale — {comm_fr}"
                    items.append(
                        f"Médiane prévue : {_fmt_int(ns['median_forecast_xaf'])} XAF/kg "
                        f"({_fmt_int(ns['median_forecast_xaf'] * 100)} XAF / sac 100 kg)"
                    )
                    items.append(
                        f"Couverture : {ns.get('provinces_count', 0)} provinces · {ns.get('series_count', 0)} séries"
                    )
        elif intent == "alerts":
            title = "Alertes de tension détectées"
            recs = provider_data.get("records") or []
            items.append(f"{provider_data.get('count', len(recs))} série(s) au-dessus de +{provider_data.get('threshold_pct', 15):.0f} %")
            if recs:
                r0 = recs[0]
                items.append(
                    f"Tension max : {r0.get('market_name', '')} ({r0.get('commodity_fr', '')}) à {r0.get('deviation_pct', 0):+.1f} %"
                )
        elif intent == "anomalies":
            title = "Radar Anomalies & Qualité"
            items.append(
                f"{provider_data.get('n_total', 0)} signal(aux) sur {provider_data.get('months', 3)} mois "
                f"(dont {provider_data.get('n_strong', 0)} fort(s))"
            )
            if provider_data.get("n_quality", 0) > 0:
                items.append(f"Qualité des relevés : {provider_data['n_quality']} série(s) figée(s) ou arrêtée(s)")
        elif intent == "timing":
            comm_fr = provider_data.get("commodity_fr") or "Produit"
            title = f"Calendrier saisonnier — {comm_fr}"
            if provider_data.get("buy_discount_pct") is not None and provider_data.get("sell_premium_pct") is not None:
                items.append(
                    f"Creux achat : {provider_data['buy_discount_pct']:+.0f} % · Pic revente : {provider_data['sell_premium_pct']:+.0f} %"
                )
            if provider_data.get("amplitude_pct") is not None:
                items.append(f"Amplitude saisonnière : {provider_data['amplitude_pct']:.0f} %")
        elif intent == "credit_passport":
            recs = provider_data.get("records") or []
            if recs:
                r0 = recs[0]
                title = f"Credit Passport — {r0.get('commodity_fr', 'Produit')}"
                items.append(
                    f"Meilleur profil : {r0.get('province', '')} ({r0.get('credit_score', 0):.0f}/100 · {r0.get('grade', '')})"
                )
                items.append(f"Plafond LTV indicatif : {_fmt_int(r0.get('recommended_max_loan_xaf'))} XAF ({r0.get('ltv_pct', 0)} %)")
        elif intent == "business_simulator" and provider_data.get("net_profit_xaf") is not None:
            title = f"Compte d’exploitation — {provider_data.get('commodity_fr', '')}"
            items.append(
                f"Marge nette estimée : {_fmt_signed_int(provider_data['net_profit_xaf'])} XAF "
                f"({provider_data.get('net_margin_pct', 0):+.1f} %)"
            )
            items.append(
                f"Seuil de rentabilité : {_fmt_num(provider_data.get('break_even_price_per_kg'))} XAF/kg "
                f"· Volume : {_fmt_int(provider_data.get('purchasable_kg'))} kg"
            )
        elif intent == "business_simulator" and isinstance(provider_data.get("focus_plan"), dict):
            fp = provider_data["focus_plan"]
            if fp.get("unit_price_xaf"):
                title = f"Plan d’investissement — {fp.get('commodity_fr', '')} ({fp.get('scope', '')})"
                items.append(
                    f"BFR achat (80 %) : {_fmt_int(fp.get('stock_budget_xaf'))} XAF · "
                    f"CAPEX (8 %) : {_fmt_int(fp.get('capex_budget_xaf'))} XAF · "
                    f"Réserve (12 %) : {_fmt_int(fp.get('cash_reserve_xaf'))} XAF"
                )
                items.append(
                    f"Volume achetable : {_fmt_int(fp.get('purchasable_kg'))} kg "
                    f"({fp.get('purchasable_bags_100kg', 0):.1f} sacs de 100 kg)"
                )
        elif intent == "opportunity":
            corridors = provider_data.get("corridors") or []
            if corridors:
                c0 = corridors[0]
                title = "Meilleur corridor d’arbitrage"
                items.append(
                    f"{c0.get('commodity_fr', '')} : {c0.get('low_province', '')} → {c0.get('high_province', '')} "
                    f"(+{_fmt_int(c0.get('spread_xaf'))} XAF/kg)"
                )

        return {"title": title, "items": items} if items else None
