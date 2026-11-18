"""Générateur PDF institutionnel ReportLab Platypus pour les études de marché PRO FreeData.AI."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape   # le texte saisi par l'utilisateur ne doit jamais être interprété comme balisage ReportLab
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _resolve_logo_path() -> Path | None:
    local_logo = Path(__file__).with_name("freedata_logo.png")
    if local_logo.is_file():
        return local_logo
    web_logo = Path(__file__).resolve().parents[2] / "frontend_flutter" / "web" / "icons" / "Icon-192.png"
    if web_logo.is_file():
        return web_logo
    return None


def _clean_pdf_text(val: object) -> str:
    txt = str(val if val is not None else "")
    txt = txt.replace("\u03a7", "X").replace("\u03c7", "x")
    for bad in ("FreeData. Al", "FreeData.Al", "FreeData. al", "FreeData.al", "FreeData. AI"):
        txt = txt.replace(bad, "FreeData.AI")
    return txt


def _xaf(val: object) -> str:
    if val is None:
        return "—"
    try:
        return _clean_pdf_text(f"{round(float(val)):,} XAF".replace(",", " "))
    except (TypeError, ValueError):
        return _clean_pdf_text(val)


def _num(val: object, suffix: str = "") -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        txt = f"{f:.1f}" if not f.is_integer() else f"{int(f)}"
        return _clean_pdf_text(f"{txt}{suffix}")
    except (TypeError, ValueError):
        return _clean_pdf_text(val)


def _styled_table(rows: list[list[str]], col_widths: list[float] | None = None) -> Table:
    cleaned_rows = [[_clean_pdf_text(cell) for cell in row] for row in rows]
    tbl = Table(cleaned_rows, colWidths=col_widths, repeatRows=1)
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
    h1 = ParagraphStyle("FDH1", parent=styles["Heading1"], textColor=colors.HexColor("#1E3A8A"), fontSize=17, spaceAfter=6, keepWithNext=True)
    h2 = ParagraphStyle("FDH2", parent=styles["Heading2"], textColor=colors.HexColor("#1D4ED8"), fontSize=11.5, spaceBefore=10, spaceAfter=4, keepWithNext=True)
    body = ParagraphStyle("FDBody", parent=styles["Normal"], fontSize=9.0, leading=12.5, spaceAfter=3)
    small = ParagraphStyle("FDSmall", parent=styles["Normal"], fontSize=8.0, leading=10.5, textColor=colors.HexColor("#475569"))

    bp = dossier["business_plan"]
    ca = bp["capital_allocation"]
    ue = bp["unit_economics"]
    cs = bp.get("commercial_strategy") or {}
    route = (
        f"{dossier['origin_province']} -> {dossier['dest_province']}"
        if dossier.get("dest_province")
        else f"{dossier['origin_province']} (marche local)"
    )

    story = []
    logo_path = _resolve_logo_path()
    # 1. En-tête & Encadré Verdict Exécutif
    title_para = Paragraph("FreeData.AI Market Intelligence - Dossier PRO", h1)
    if logo_path is not None:
        logo_img = Image(str(logo_path), width=1.35 * cm, height=1.35 * cm)
        header_tbl = Table([[logo_img, title_para]], colWidths=[1.6 * cm, 15.4 * cm])
        header_tbl.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ])
        )
        story.append(KeepTogether(header_tbl))
    else:
        story.append(title_para)
    story.append(Paragraph(f"<b>1. Etude de prefaisabilite : {dossier['commodity_fr']} ({route})</b>", h2))
    meta_rows = [
        ["Reference etude", dossier["study_id"]],
        ["Date de generation (UTC)", dossier["generated_at_utc"]],
        ["Promoteur", dossier.get("promoter_name", "Non precise")],
        ["Produit / Corridor", f"{dossier['commodity_fr']} - {route}"],
        ["Capital engage", _xaf(ca["total_capital_xaf"])],
        ["Point mort (seuil minimal)", f"{_num(ue['break_even_price_per_kg'], ' XAF/kg')} ({_xaf(ue['break_even_bag_100kg_xaf'])} / sac 100 kg)"],
        ["Resultat net Cycle 1 (Central)", f"{_xaf(ue['net_profit_cycle1_xaf'])} (ROI {_num(ue['roi_cycle1_pct'], ' %')})"],
    ]
    story.append(KeepTogether(_styled_table([["Champ", "Valeur verifiee"], *meta_rows], col_widths=[6 * cm, 11 * cm])))
    story.append(Spacer(1, 0.25 * cm))

    is_non_rentable = ue.get("profitability_status") == "NON RENTABLE À CETTE ÉCHELLE"
    if is_non_rentable:
        min_cap = ue.get("min_theoretical_capital_xaf")
        cap_msg = (
            f"Capital minimum theorique requis pour absorber les couts fixes : {_xaf(min_cap)}."
            if min_cap is not None and min_cap > 0
            else "Marge unitaire <= 0 a ces prix : corridor structurellement non rentable sans baisse du prix d'achat ou hausse du prix de vente."
        )
        verdict_title = "STATUT : NON RENTABLE A CETTE ECHELLE"
        verdict_text = f"Perte nette reelle Cycle 1 : {_xaf(ue['net_profit_cycle1_xaf'])} (ROI {_num(ue['roi_cycle1_pct'], ' %')}). {cap_msg}"
        verdict_bg = colors.HexColor("#FEF2F2")
        verdict_border = colors.HexColor("#DC2626")
        verdict_fg = colors.HexColor("#991B1B")
    else:
        verdict_title = "STATUT : VIABLE / RENTABLE A CETTE ECHELLE"
        verdict_text = (
            f"Resultat net Cycle 1 : {_xaf(ue['net_profit_cycle1_xaf'])} (ROI {_num(ue['roi_cycle1_pct'], ' %')}). "
            f"Point mort : {_num(ue['break_even_price_per_kg'], ' XAF/kg')}."
        )
        verdict_bg = colors.HexColor("#ECFDF5")
        verdict_border = colors.HexColor("#059669")
        verdict_fg = colors.HexColor("#065F46")

    verdict_tbl = Table(
        [[Paragraph(f"<b>{verdict_title}</b><br/>{verdict_text}", ParagraphStyle("FDVerdict", parent=body, textColor=verdict_fg))]],
        colWidths=[17 * cm],
    )
    verdict_tbl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), verdict_bg),
            ("BOX", (0, 0), (-1, -1), 1.0, verdict_border),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(KeepTogether(verdict_tbl))

    if dossier.get("user_instructions"):
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph("<b>Consignes client memorisees :</b> " + " ; ".join(escape(str(i)) for i in dossier["user_instructions"]), body))

    # 2. Analyse des prix observés et prévisions t+1
    story.append(Paragraph("2. Analyse des prix observes et previsions t+1", h2))
    fc_rows = [["Marche", "Province", "Observe (XAF/kg)", "Prevu t+1 (XAF/kg)", "Intervalle 80 %"]]
    for rec in (dossier["market_data"].get("origin_forecasts") or []) + (dossier["market_data"].get("destination_forecasts") or []):
        fc_rows.append([
            str(rec.get("market_name", "-")),
            str(rec.get("province", "-")),
            _num(rec.get("last_observed_price")),
            _num(rec.get("forecast_t1")),
            f"{_num(rec.get('ci_low_80'))} - {_num(rec.get('ci_high_80'))}",
        ])
    if len(fc_rows) > 1:
        story.append(KeepTogether(_styled_table(fc_rows, col_widths=[4.2 * cm, 3.5 * cm, 3 * cm, 3 * cm, 3.3 * cm])))
    else:
        story.append(Paragraph("Aucune serie detaillee disponible pour ce filtre.", body))

    # 3. Indice de Stabilité Marché
    story.append(Paragraph("3. Indice de Stabilite Marche (Agricultural Market Risk & Stability Index)", h2))
    stab = dossier["market_data"].get("market_stability") or {}
    if stab:
        story.append(
            Paragraph(
                f"Score stabilite : <b>{_num(stab.get('credit_score'), '/100')}</b> (Classe {stab.get('grade', '-')}) | "
                f"Volatilite CV : {_num(stab.get('cv_pct'), ' %')} | LTV indicatif : {_num(float(stab.get('ltv_ratio', 0)) * 100, ' %')}",
                body,
            )
        )
    else:
        story.append(Paragraph("Indice de stabilite non disponible pour ce couple province/produit.", body))
    story.append(Paragraph(f"<i>{dossier['market_data']['market_stability_disclaimer']}</i>", small))

    # 4. Allocation du capital (80/8/12 ou 88/0/12) & Scénarios financiers (flux continu, sans saut de page)
    wc_pct_txt = f"{ca.get('working_capital_share_pct', 80.0):.0f} %"
    capex_pct_txt = f"{ca.get('capex_share_pct', 8.0):.0f} %"
    res_pct_txt = f"{ca.get('safety_share_pct', 12.0):.0f} %"
    story.append(Paragraph(f"4. Allocation du capital ({wc_pct_txt}/{capex_pct_txt}/{res_pct_txt}) & Scenarios financiers", h2))
    alloc_rows = [
        ["Poste", "Montant", "Part", "Usage"],
        ["BFR operationnel", _xaf(ca["working_capital_xaf"]), wc_pct_txt, "Achat stock + transport + sacherie"],
        ["CAPEX equipement", _xaf(ca["capex_equipment_xaf"]), capex_pct_txt, "Balance, baches, palettes (0 % si sans equipement)"],
        ["Reserve d'urgence", _xaf(ca["safety_cash_reserve_xaf"]), res_pct_txt, "Liquidites de securite (jamais engagees en stock)"],
    ]
    story.append(KeepTogether(_styled_table(alloc_rows, col_widths=[3.8 * cm, 3.4 * cm, 1.8 * cm, 8 * cm])))
    story.append(Spacer(1, 0.25 * cm))

    scen_rows = [["Scenario", "Achat (XAF/kg)", "Vente (XAF/kg)", "Fret (XAF/kg)", "Pertes (%)", "Resultat Cycle 1 & ROI"]]
    for sc in dossier["scenarios"]:
        scen_rows.append([
            sc["name"],
            _num(sc["buy_price_per_kg"]),
            _num(sc["sell_price_per_kg"]),
            _num(sc["transport_cost_per_kg"]),
            _num(sc["loss_rate_pct"], " %"),
            f"{_xaf(sc['net_profit_cycle1_xaf'])} ({_num(sc['roi_cycle1_pct'], ' %')})",
        ])
    story.append(KeepTogether(_styled_table(scen_rows, col_widths=[2.3 * cm, 2.5 * cm, 2.5 * cm, 2.4 * cm, 2.0 * cm, 5.3 * cm])))

    # 5. Compte d'exploitation prévisionnel sur 6 mois
    reinv_mode = (
        f"Reinvestissement {ue.get('reinvest_rate_pct', 75.0):.0f} % du resultat net dans le BFR"
        if ue.get("reinvest_enabled", True)
        else "BFR constant M1-M6 (sans reinvestissement)"
    )
    story.append(Paragraph(f"5. Compte d'exploitation previsionnel sur 6 mois ({reinv_mode})", h2))
    proj_rows = [["Mois", "BFR", "Chiffre d'affaires", "Couts totaux", "Resultat net", "Tresorerie cumulee"]]
    for p in bp["projection_6_months"]:
        proj_rows.append([
            f"M{p['month']}",
            _xaf(p["working_capital"]),
            _xaf(p["revenue"]),
            _xaf(p["total_costs"]),
            _xaf(p["net_profit"]),
            _xaf(p["cumulative_cash"]),
        ])
    story.append(KeepTogether(_styled_table(proj_rows, col_widths=[1.4 * cm, 3.1 * cm, 3.3 * cm, 3.1 * cm, 3.0 * cm, 3.1 * cm])))

    # 6. Stratégie Commerciale, Plan de Validation Terrain & Limites
    story.append(Paragraph("6. Strategie Commerciale, Plan de Validation Terrain & Limites", h2))
    if cs.get("flow_strategy"):
        story.append(Paragraph(f"<b>Ecoulement recommande (tendance t+1) :</b> {cs['flow_strategy']}", body))
    if cs.get("distribution_channel"):
        story.append(Paragraph(f"<b>Canal de distribution adapte au capital :</b> {cs['distribution_channel']}", body))
    if cs.get("long_distance_freight_warning"):
        story.append(Paragraph("<b>Alerte fret longue distance :</b> Le tarif par defaut de 25 XAF/kg doit etre reevalue selon un devis transporteur reel.", body))

    story.append(Spacer(1, 0.2 * cm))
    checklist_rows = [["Parametre terrain (24h-48h)", "Objectif de verification", "Valeur verifiee (a remplir)"]]
    checklist_items = [
        ("1. Fret reel", "Devis transporteur bord-champ -> destination (XAF/kg)", "________\u00a0XAF/kg"),
        ("2. Taxes communales", "Ticket de place / droits de marche hebdomadaires", "________\u00a0XAF"),
        ("3. Vitesse d'ecoulement", "Capacite d'absorption en sacs/semaine (5 acheteurs)", "________\u00a0sacs/sem"),
        ("4. Gardiennage / magasinage", "Loyer depot ou gardiennage nocturne", "________\u00a0XAF/mois"),
        ("5. Prix d'achat ferme", "Prix negocie bord-champ ou demi-gros", "________\u00a0XAF/kg"),
    ]
    for param, obj, blank in checklist_items:
        checklist_rows.append([param, obj, blank])
    story.append(KeepTogether(_styled_table(checklist_rows, col_widths=[4.4 * cm, 7.8 * cm, 4.8 * cm])))

    story.append(Spacer(1, 0.2 * cm))
    trace = dossier.get("data_traceability") or {}
    if trace:
        story.append(Paragraph("<b>Sources des donnees reellement utilisees (Tracabilite dynamique) :</b>", body))
        story.append(
            Paragraph(
                _clean_pdf_text(
                    f"- <b>Prix observes :</b> {trace.get('observed_sources', 'Source primaire non renseignee dans le jeu de donnees')} "
                    f"- Dernier releve verifie : {trace.get('latest_observed_date', 'Non renseignee')} "
                    f"(Profondeur : {trace.get('observation_count', 0)} observations)."
                ),
                small,
            )
        )
        story.append(
            Paragraph(
                _clean_pdf_text(
                    f"- <b>Previsions t+1 & Indice de risque :</b> Calcules par le moteur statistique FreeData.AI "
                    f"a partir de la serie historique ci-dessus (ID serie : {trace.get('dataset_id', '-')})."
                ),
                small,
            )
        )
        story.append(
            Paragraph(
                _clean_pdf_text(f"- <b>Parametres logistiques :</b> {trace.get('logistics_source', '-')}"),
                small,
            )
        )
        story.append(Spacer(1, 0.15 * cm))

    story.append(Paragraph("<b>Limites methodologiques verifiees :</b>", body))
    for gap in dossier.get("data_gaps") or []:
        story.append(Paragraph(_clean_pdf_text(f"- {gap}"), small))
    if dossier.get("sources"):
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph("<b>Sources documentaires RAG associees :</b>", body))
        for src in dossier["sources"]:
            story.append(Paragraph(_clean_pdf_text(f"- {src.get('editeur', 'Source')} - {src.get('titre', 'Document')} (p.{src.get('page', '?')})"), small))

    def _footer(canvas, doc_obj):
        canvas.saveState()
        text_x = 1.8 * cm
        if logo_path is not None:
            canvas.drawImage(
                str(logo_path),
                1.8 * cm,
                0.88 * cm,
                width=0.55 * cm,
                height=0.55 * cm,
                mask="auto",
            )
            text_x = 2.5 * cm
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(
            text_x,
            1.1 * cm,
            f"FreeData.AI Market Intelligence | {dossier['study_id']} | Donnees verifiees uniquement (zero chiffre invente)",
        )
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()

