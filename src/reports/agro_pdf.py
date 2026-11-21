"""Générateur PDF exécutif co-brandé pour les audits parcellaires & comparatifs Agronome PRO."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.reports.pdf_generator import _clean_pdf_text, _resolve_logo_path, _styled_table


def _fmt_num(val: Any, suffix: str = "") -> str:
    if val is None or val == "":
        return "—"
    if isinstance(val, (int, float)):
        txt = f"{val:,.0f}".replace(",", " ") if abs(val) >= 100 else f"{val:.1f}"
        return f"{txt}{suffix}"
    return f"{val}{suffix}"


def render_agro_assessment_pdf(
    assessment: dict[str, Any],
    *,
    agronomist_name: Optional[str] = None,
    agronomist_license: Optional[str] = None,
    agronomist_address: Optional[str] = None,
    agronomist_contact: Optional[str] = None,
    comparison: Optional[dict[str, Any]] = None,
) -> bytes:
    """Construit un rapport PDF A4 institutionnel (5 blocs obligatoires, formules transparentes, pied verrouillé)."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.6 * cm,
        title="Dossier d'Audit Agronomique & Marché — FreeData.td",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AgroTitle",
        parent=styles["Heading1"],
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )
    h2_style = ParagraphStyle(
        "AgroH2",
        parent=styles["Heading2"],
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0284C7"),
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "AgroBody",
        parent=styles["Normal"],
        fontSize=8.8,
        leading=12.2,
        textColor=colors.HexColor("#334155"),
    )
    bold_style = ParagraphStyle(
        "AgroBold",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0F172A"),
    )
    formula_style = ParagraphStyle(
        "AgroFormula",
        parent=body_style,
        fontName="Courier-Bold",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#0F172A"),
        backColor=colors.HexColor("#F8FAFC"),
        borderPadding=6,
    )

    scores = assessment.get("computed_scores") or {}
    lab = assessment.get("lab_soil_inputs") or {}
    gps = scores.get("gps_logistics") or {}
    ws = scores.get("weighted_score") or {}
    econ = scores.get("verified_economics") or {}
    risks = scores.get("hydric_risk_signals") or {}
    latest = scores.get("zone_latest") or {}
    code = assessment.get("report_verification_code") or "FDT-VERIFY"
    firm = (agronomist_name or "").strip() or "Agronome / Bureau d'études"
    lic = (agronomist_license or "").strip()
    addr = (agronomist_address or "").strip()
    contact = (agronomist_contact or "").strip()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conf_label = scores.get("confidence_level") or "Modèle Satellitaire IDW"
    has_lab = bool(scores.get("has_lab_measurements"))
    qa_badge = "QA TERRAIN VALIDÉ" if has_lab else "ESTIMATION SATELLITAIRE GPS"
    resolution_title = (
        "DIAGNOSTIC D'AUDIT PARCELLAIRE & MARCHÉ (PRÉ-ACHAT CERTIFIÉ)"
        if has_lab
        else "PRÉ-DIAGNOSTIC AGRO-CLIMATIQUE & ÉCONOMIQUE (MAILLE SATELLITAIRE GPS)"
    )

    story: list[Any] = []

    # --- EN-TÊTE CO-BRANDÉ ---
    left_cells: list[Any] = []
    logo = _resolve_logo_path()
    if logo is not None:
        try:
            left_cells.append(Image(str(logo), width=1.1 * cm, height=1.1 * cm))
        except Exception:
            pass
    left_cells.append(Paragraph(_clean_pdf_text(firm), bold_style))
    if lic:
        left_cells.append(Paragraph(_clean_pdf_text(f"N° d'agrément / RCCM : {lic}"), body_style))
    if addr:
        left_cells.append(Paragraph(_clean_pdf_text(f"Adresse : {addr}"), body_style))
    if contact:
        left_cells.append(Paragraph(_clean_pdf_text(f"Contact : {contact}"), body_style))

    right_html = _clean_pdf_text(
        f"<b>DOSSIER D'AUDIT AGRONOMIQUE & MARCHÉ</b> [{qa_badge}]<br/>"
        f"Date : {date_str} | Code : {code}<br/>"
        f"Confiance : {conf_label}"
    )
    header_tbl = Table([[left_cells, Paragraph(right_html, body_style)]], colWidths=[8.8 * cm, 9.0 * cm])
    header_tbl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(header_tbl)
    story.append(Spacer(1, 0.25 * cm))
    story.append(Paragraph(_clean_pdf_text(resolution_title), title_style))
    if not has_lab:
        warn_tbl = Table(
            [[Paragraph(
                _clean_pdf_text(
                    "<b>AVERTISSEMENT SATELLITAIRE :</b> Mesures de sol laboratoire non fournies — "
                    "la composante sol (plafonnée à 20/40 pts) est estimée par satellite en attente d'analyse de laboratoire."
                ),
                body_style,
            )]],
            colWidths=[17.8 * cm],
        )
        warn_tbl.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#F59E0B")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(warn_tbl)
        story.append(Spacer(1, 0.2 * cm))

    # --- BLOC 1 : SYNTHÈSE EXÉCUTIVE & VERDICT DÉCISIONNEL ---
    story.append(Paragraph("1. Synthèse Exécutive & Verdict Décisionnel", h2_style))
    gps_str = (
        f"{gps['gps_lat']:.5f}, {gps['gps_lon']:.5f}"
        if gps.get("gps_provided")
        else (f"{assessment['gps_lat']:.5f}, {assessment['gps_lon']:.5f}" if assessment.get("gps_lat") is not None and assessment.get("gps_lon") is not None else "Non fournies")
    )
    bd = ws.get("breakdown") or {}
    exec_rows = [
        ["Indicateur clé", "Valeur auditée", "Détail / Pondération"],
        [
            "Score Global / 100",
            f"{ws.get('total_score', '—')}/100 ({ws.get('verdict', '—')})",
            f"Hydrique {bd.get('hydric_security', {}).get('score', '—')}/40 · Sol {bd.get('soil_quality', {}).get('score', '—')}/30 · Marché {bd.get('market_logistics', {}).get('score', '—')}/30",
        ],
        [
            "Localisation & Pôle",
            f"{assessment.get('province_hub') or scores.get('region')} ({scores.get('province') or '—'})",
            f"GPS : {gps_str} · Superficie : {assessment.get('area_hectares') or '1.0 (réf.)'} ha",
        ],
        [
            "Logistique & Décote Bord-Champ",
            f"Pôle : {_fmt_num(gps.get('distance_hub_km'), ' km')} | N'Djamena : {_fmt_num(gps.get('distance_ndjamena_km'), ' km')}",
            f"Décote appliquée : {gps.get('farmgate_discount_pct', 0)}% ({gps.get('enclavement_label', '—')})",
        ],
    ]
    idw_hubs = gps.get("idw_hubs") or []
    if idw_hubs:
        idw_str = " | ".join(
            f"{h.get('hub')} ({h.get('road_distance_km', 0)} km, {h.get('weight_pct', 0)}%)"
            for h in idw_hubs
            if (h.get("weight_pct") or 0) > 0
        )
        exec_rows.append(["Interpolation Spatiale IDW (k=3)", gps.get("idw_mode", "idw_k3"), idw_str or "—"])
    story.append(_styled_table(exec_rows, col_widths=[4.6 * cm, 5.4 * cm, 7.8 * cm]))
    strengths = ws.get("strengths") or []
    vigilances = ws.get("vigilances") or []
    if strengths or vigilances:
        story.append(Spacer(1, 0.15 * cm))
        if strengths:
            story.append(Paragraph(_clean_pdf_text("<b>Points forts :</b> " + " | ".join(strengths[:3])), body_style))
        if vigilances:
            story.append(Paragraph(_clean_pdf_text("<b>Points de vigilance :</b> " + " | ".join(vigilances[:2])), body_style))

    # --- BLOC 2 : TABLEAU COMPARATIF MULTI-TERRAINS (si demandé) ---
    if comparison and comparison.get("comparison_table"):
        story.append(Paragraph("2. Tableau Comparatif Multi-Terrains", h2_style))
        comp_rows = [["Terrain", "Pôle / Province", "Dist. marché", "Hum. rac.", "Prix ML", "CA Central", "CA Stress", "Rang"]]
        for row in comparison["comparison_table"]:
            comp_rows.append([
                str(row.get("label") or "—"),
                f"{row.get('region') or '—'}",
                _fmt_num(row.get("distance_hub_km"), " km"),
                f"{row['rainy_root_wetness']:.2f}" if isinstance(row.get("rainy_root_wetness"), (int, float)) else "—",
                _fmt_num(row.get("predicted_xaf_kg"), " F"),
                _fmt_num(row.get("ca_central_xaf")),
                _fmt_num(row.get("ca_stress_xaf")),
                str(row.get("rank_label") or f"#{row.get('rank', '')}"),
            ])
        story.append(_styled_table(comp_rows, col_widths=[2.0 * cm, 3.0 * cm, 2.0 * cm, 1.8 * cm, 1.8 * cm, 2.5 * cm, 2.5 * cm, 2.2 * cm]))

    # --- BLOC 3 : PREUVES CLIMATIQUES & PÉDOLOGIQUES (TRAÇABILITÉ) ---
    story.append(Paragraph("3. Preuves Climatiques & Pédologiques (Traçabilité)", h2_style))
    rz = latest.get("root_zone_wetness") or {}
    sf = latest.get("surface_wetness") or {}
    proof_rows = [
        ["Paramètre", "Valeur observée", "Source / Référence"],
        ["Humidité zone racinaire (dernière)", _fmt_num(rz.get("value")), f"NASA POWER Agro ({rz.get('reference_date', '—')})"],
        ["Humidité racinaire moyenne (juin–sept.)", _fmt_num(ws.get("rainy_season_root_wetness_mean")), "NASA POWER Agro 2020–2026 vs 2020–2023"],
        ["Humidité de surface (dernière)", _fmt_num(sf.get("value")), f"NASA POWER Agro ({sf.get('reference_date', '—')})"],
        ["Années critiques (< 0.45 juil.–août)", str(risks.get("critical_july_aug_years", "—")), f"Sur {risks.get('observed_july_aug_years', '—')} années observées"],
    ]
    for k, label in (
        ("ph", "pH du sol (labo)"),
        ("texture", "Texture du sol (labo)"),
        ("organic_matter", "Matière organique (%)"),
        ("nitrogen", "Azote (N)"),
        ("phosphorus", "Phosphore (P)"),
        ("potassium", "Potassium (K)"),
    ):
        v = lab.get(k)
        if v is not None and str(v).strip() != "":
            proof_rows.append([label, str(v), "Mesure terrain / laboratoire agronome"])
    story.append(_styled_table(proof_rows, col_widths=[5.6 * cm, 4.4 * cm, 7.8 * cm]))

    notes = (assessment.get("agronomist_field_notes") or "").strip()
    if notes:
        story.append(Spacer(1, 0.12 * cm))
        story.append(Paragraph(_clean_pdf_text(f"<b>Notes d'inspection terrain :</b> {notes}"), body_style))

    # --- BLOC 4 : MODÉLISATION ÉCONOMIQUE & FORMULES MATHÉMATIQUES VÉRIFIABLES ---
    story.append(Paragraph("4. Modélisation Économique & Formules Mathématiques Vérifiables", h2_style))
    if econ and econ.get("formula_text"):
        story.append(
            Paragraph(
                _clean_pdf_text(
                    "Formule : Superficie (ha) x Rendement (kg/ha) x Prix ML t+1 (FCFA/kg) x (1 - Decote logistique %) = CA Brut Estime"
                ),
                body_style,
            )
        )
        story.append(Paragraph(_clean_pdf_text(econ["formula_text"]), formula_style))
        story.append(Spacer(1, 0.12 * cm))
        if econ.get("scenarios"):
            scen_rows = [["Scénario économique", "Prix marché (FCFA/kg)", "Prix bord-champ (FCFA/kg)", "CA Brut Estimé (FCFA)"]]
            for sc in econ["scenarios"]:
                scen_rows.append([
                    str(sc.get("label") or "—"),
                    _fmt_num(sc.get("market_price_xaf_kg")),
                    _fmt_num(sc.get("farmgate_price_xaf_kg")),
                    _fmt_num(sc.get("gross_revenue_xaf")),
                ])
            story.append(_styled_table(scen_rows, col_widths=[6.2 * cm, 3.8 * cm, 3.9 * cm, 3.9 * cm]))
            story.append(Spacer(1, 0.12 * cm))

    crop_rows = [["Culture", "Score (Eau+Sol)", "Rdt WB", "Prix IDW", "Décote", "CA Brut (FCFA)"]]
    for c in scores.get("crop_assessments") or []:
        mkt = c.get("market_forecast") or {}
        cecon = c.get("verified_economics") or {}
        price_str = f"{mkt['predicted_xaf_kg']} F" if mkt.get("predicted_xaf_kg") is not None else "N/A"
        s_sat = c.get("satellite_score", "—")
        s_soil = c.get("soil_score", "—")
        yld = cecon.get("yield_kg_ha", 834.6)
        disc = cecon.get("farmgate_discount_pct", 0)
        crop_rows.append([
            str(c.get("label_fr") or c.get("crop_id")),
            f"{c.get('suitability_score', 0)}/100 ({s_sat}+{s_soil})",
            f"{yld} kg/ha",
            price_str,
            f"-{disc}%",
            _fmt_num(c.get("indicative_gross_revenue_xaf")),
        ])
    story.append(_styled_table(crop_rows, col_widths=[2.8 * cm, 3.8 * cm, 2.5 * cm, 2.5 * cm, 2.0 * cm, 4.2 * cm]))

    # --- BLOC 5 : SOURCES, LICENCES & MENTIONS LÉGALES ---
    prov = scores.get("provenance") or {}
    story.append(Paragraph("5. Sources, Licences & Mentions Légales", h2_style))
    story.append(
        Paragraph(
            _clean_pdf_text(
                f"Sources : NASA POWER Agro (Public Domain) | World Bank (CC BY 4.0) | WFP (CC BY-IGO 3.0) | FEWS NET (Attribution Required). "
                f"Période climatique : {(prov.get('reference_period') or {}).get('first', '2020-01')} -> "
                f"{(prov.get('reference_period') or {}).get('last', '2026-09')}."
            ),
            body_style,
        )
    )
    for lim in scores.get("limitations") or []:
        story.append(Paragraph(_clean_pdf_text(f"- {lim}"), body_style))

    def _draw_footer(canvas, pdf_doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 8.0)
        canvas.setFillColor(colors.HexColor("#475569"))
        footer_text = _clean_pdf_text(
            f"Propulse par FreeData.td  |  Verification : {code}  |  Page {pdf_doc.page}"
        )
        canvas.drawString(1.6 * cm, 1.0 * cm, footer_text)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buf.getvalue()
