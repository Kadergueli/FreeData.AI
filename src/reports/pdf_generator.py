"""Générateur PDF institutionnel ReportLab Platypus pour les études de marché PRO FreeData.AI."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _xaf(val: object) -> str:
    if val is None:
        return "—"
    try:
        return f"{round(float(val)):,} XAF".replace(",", " ")
    except (TypeError, ValueError):
        return str(val)


def _num(val: object, suffix: str = "") -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        txt = f"{f:.1f}" if not f.is_integer() else f"{int(f)}"
        return f"{txt}{suffix}"
    except (TypeError, ValueError):
        return str(val)


def _styled_table(rows: list[list[str]], col_widths: list[float] | None = None) -> Table:
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1D4ED8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    return tbl


def render_market_study_pdf(dossier: dict) -> bytes:
    """Assemble le dossier vérifié en un document PDF binaire téléchargeable."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=f"FreeData.AI — Étude de Marché {dossier.get('commodity_fr', '')}",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("FDH1", parent=styles["Heading1"], textColor=colors.HexColor("#1E3A8A"), fontSize=18, spaceAfter=8)
    h2 = ParagraphStyle("FDH2", parent=styles["Heading2"], textColor=colors.HexColor("#1D4ED8"), fontSize=12.5, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("FDBody", parent=styles["Normal"], fontSize=9.5, leading=13, spaceAfter=4)
    small = ParagraphStyle("FDSmall", parent=styles["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#475569"))

    bp = dossier["business_plan"]
    ca = bp["capital_allocation"]
    ue = bp["unit_economics"]
    route = (
        f"{dossier['origin_province']} → {dossier['dest_province']}"
        if dossier.get("dest_province")
        else f"{dossier['origin_province']} (marché local)"
    )

    story = []
    # Page de garde / Fiche d'identité
    story.append(Paragraph("FreeData.AI Market Intelligence — Dossier PRO", h1))
    story.append(Paragraph(f"<b>Étude de marché & Business Plan : {dossier['commodity_fr']} ({route})</b>", styles["Heading2"]))
    story.append(Spacer(1, 0.3 * cm))
    meta_rows = [
        ["Référence étude", dossier["study_id"]],
        ["Date de génération (UTC)", dossier["generated_at_utc"]],
        ["Promoteur", dossier.get("promoter_name", "Non précisé")],
        ["Produit / Corridor", f"{dossier['commodity_fr']} — {route}"],
        ["Capital engagé", _xaf(ca["total_capital_xaf"])],
        ["Point mort (seuil minimal)", f"{_num(ue['break_even_price_per_kg'], ' XAF/kg')} ({_xaf(ue['break_even_bag_100kg_xaf'])} / sac 100 kg)"],
        ["Résultat net Cycle 1 (Central)", f"{_xaf(ue['net_profit_cycle1_xaf'])} (ROI {_num(ue['roi_cycle1_pct'], ' %')})"],
    ]
    story.append(_styled_table([["Champ", "Valeur vérifiée"], *meta_rows], col_widths=[6 * cm, 11 * cm]))
    story.append(Spacer(1, 0.4 * cm))

    if dossier.get("user_instructions"):
        story.append(Paragraph("<b>Consignes client mémorisées :</b> " + " ; ".join(dossier["user_instructions"]), body))

    # Section 1 : Prix & Prévisions
    story.append(Paragraph("1. Analyse des prix observés et prévisions t+1", h2))
    fc_rows = [["Marché", "Province", "Observé (XAF/kg)", "Prévu t+1 (XAF/kg)", "Intervalle 80 %"]]
    for rec in (dossier["market_data"].get("origin_forecasts") or []) + (dossier["market_data"].get("destination_forecasts") or []):
        fc_rows.append([
            str(rec.get("market_name", "—")),
            str(rec.get("province", "—")),
            _num(rec.get("last_observed_price")),
            _num(rec.get("forecast_t1")),
            f"{_num(rec.get('ci_low_80'))} – {_num(rec.get('ci_high_80'))}",
        ])
    if len(fc_rows) > 1:
        story.append(_styled_table(fc_rows, col_widths=[4.2 * cm, 3.5 * cm, 3 * cm, 3 * cm, 3.3 * cm]))
    else:
        story.append(Paragraph("Aucune série détaillée disponible pour ce filtre.", body))

    # Section 2 : Indice de stabilité marché
    story.append(Paragraph("2. Indice de Stabilité Marché (Agricultural Market Risk & Stability Index)", h2))
    stab = dossier["market_data"].get("market_stability") or {}
    if stab:
        story.append(
            Paragraph(
                f"Score stabilité : <b>{_num(stab.get('credit_score'), '/100')}</b> ({stab.get('grade', '—')}) | "
                f"Volatilité CV : {_num(stab.get('cv_pct'), ' %')} | LTV indicatif : {_num(float(stab.get('ltv_ratio', 0)) * 100, ' %')}",
                body,
            )
        )
    else:
        story.append(Paragraph("Indice de stabilité non disponible pour ce couple province/produit.", body))
    story.append(Paragraph(f"<i>{dossier['market_data']['market_stability_disclaimer']}</i>", small))

    # Section 3 : Allocation 80/8/12 & Scénarios
    story.append(PageBreak())
    story.append(Paragraph("3. Allocation du capital (80 / 8 / 12) & Scénarios financiers", h2))
    alloc_rows = [
        ["Poste", "Montant", "Part", "Usage"],
        ["BFR opérationnel", _xaf(ca["working_capital_xaf"]), "80 %", "Achat stock + transport + sacherie"],
        ["CAPEX équipement", _xaf(ca["capex_equipment_xaf"]), "8 %", "Balance, bâches, palettes (optionnel si non requis)"],
        ["Réserve d'urgence", _xaf(ca["safety_cash_reserve_xaf"]), "12 %", "Liquidités de sécurité (jamais engagées en stock)"],
    ]
    story.append(_styled_table(alloc_rows, col_widths=[3.8 * cm, 3.4 * cm, 1.8 * cm, 8 * cm]))
    story.append(Spacer(1, 0.3 * cm))

    scen_rows = [["Scénario", "Achat (XAF/kg)", "Vente (XAF/kg)", "Fret (XAF/kg)", "Pertes", "Résultat Cycle 1", "ROI"]]
    for sc in dossier["scenarios"]:
        scen_rows.append([
            sc["name"],
            _num(sc["buy_price_per_kg"]),
            _num(sc["sell_price_per_kg"]),
            _num(sc["transport_cost_per_kg"]),
            _num(sc["loss_rate_pct"], " %"),
            _xaf(sc["net_profit_cycle1_xaf"]),
            _num(sc["roi_cycle1_pct"], " %"),
        ])
    story.append(_styled_table(scen_rows, col_widths=[2.3 * cm, 2.3 * cm, 2.3 * cm, 2.3 * cm, 1.6 * cm, 3.8 * cm, 2.4 * cm]))

    # Section 4 : Projection 6 mois & Stress-tests
    story.append(Paragraph("4. Compte d'exploitation prévisionnel sur 6 mois", h2))
    proj_rows = [["Mois", "BFR", "Chiffre d'affaires", "Coûts totaux", "Résultat net", "Trésorerie cumulée"]]
    for p in bp["projection_6_months"]:
        proj_rows.append([
            f"M{p['month']}",
            _xaf(p["working_capital"]),
            _xaf(p["revenue"]),
            _xaf(p["total_costs"]),
            _xaf(p["net_profit"]),
            _xaf(p["cumulative_cash"]),
        ])
    story.append(_styled_table(proj_rows, col_widths=[1.4 * cm, 3.1 * cm, 3.3 * cm, 3.1 * cm, 3.0 * cm, 3.1 * cm]))

    # Section 5 : Limites, données manquantes et sources
    story.append(Paragraph("5. Limites, données manquantes & Sources vérifiées", h2))
    for gap in dossier.get("data_gaps") or []:
        story.append(Paragraph(f"• {gap}", body))
    if dossier.get("sources"):
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph("<b>Sources documentaires RAG associées :</b>", body))
        for src in dossier["sources"]:
            story.append(Paragraph(f"• {src.get('editeur', 'Source')} — {src.get('titre', 'Document')} (p.{src.get('page', '?')})", small))

    def _footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(
            1.8 * cm,
            1.1 * cm,
            f"FreeData.AI Market Intelligence · {dossier['study_id']} · Données vérifiées uniquement (zéro chiffre inventé)",
        )
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()

