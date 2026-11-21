"""Générateur PDF exécutif co-brandé — Bulletin d'Analyse Agronomique & Pédologique en 4 Blocs."""
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


def _bulletin_table(rows: list[list[Any]], col_widths: list[float]) -> Table:
    """Tableau style fiche technique de laboratoire (en-tête #F0F9FF, bordures fines #CBD5E1)."""
    tbl = _styled_table(rows, col_widths=col_widths)
    tbl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F9FF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    return tbl


def render_agro_assessment_pdf(
    assessment: dict[str, Any],
    *,
    agronomist_name: Optional[str] = None,
    agronomist_license: Optional[str] = None,
    agronomist_address: Optional[str] = None,
    agronomist_contact: Optional[str] = None,
    comparison: Optional[dict[str, Any]] = None,
) -> bytes:
    """Construit un Bulletin d'Analyse Agronomique & Pédologique A4 en 4 blocs + pied verrouillé."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.5 * cm,
        title="Bulletin d'Analyse Agronomique & Pédologique — FreeData.td",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AgroTitle",
        parent=styles["Heading1"],
        fontSize=14.5,
        leading=18,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )
    h2_style = ParagraphStyle(
        "AgroH2",
        parent=styles["Heading2"],
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#0284C7"),
        spaceBefore=9,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "AgroBody",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
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
        fontSize=8.2,
        leading=11.5,
        textColor=colors.HexColor("#0F172A"),
        backColor=colors.HexColor("#F8FAFC"),
        borderPadding=5,
    )

    scores = assessment.get("computed_scores") or {}
    gps = scores.get("gps_logistics") or {}
    ws = scores.get("weighted_score") or {}
    econ = scores.get("verified_economics") or {}
    bulletin = scores.get("bulletin") or {}
    code = assessment.get("report_verification_code") or "FDT-VERIFY"
    firm = (agronomist_name or "").strip() or "Agronome / Bureau d'études"
    lic = (agronomist_license or "").strip()
    addr = (agronomist_address or "").strip()
    contact = (agronomist_contact or "").strip()
    date_str = str(assessment.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    has_lab = bool(scores.get("has_lab_measurements"))
    conf_label = scores.get("confidence_level") or (
        "Satellite IDW + Labo Certifié"
        if has_lab
        else "Satellite IDW Uniquement — En attente d'analyse physique"
    )
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
        f"<b>BULLETIN D'ANALYSE AGRONOMIQUE & PÉDOLOGIQUE</b> [{qa_badge}]<br/>"
        f"Réf. : {code} | Date : {date_str}<br/>"
        f"Confiance : {conf_label}"
    )
    header_tbl = Table([[left_cells, Paragraph(right_html, body_style)]], colWidths=[8.8 * cm, 9.2 * cm])
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
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(_clean_pdf_text(resolution_title), title_style))

    if not has_lab:
        warn_tbl = Table(
            [[Paragraph(
                _clean_pdf_text(
                    "<b>AVERTISSEMENT SATELLITAIRE :</b> Mesures de sol laboratoire non fournies — "
                    "la composante sol (plafonnée à 15/30 pts) est estimée par satellite en attente d'analyse physique."
                ),
                body_style,
            )]],
            colWidths=[18.0 * cm],
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
        story.append(Spacer(1, 0.15 * cm))

    # --- 1. FICHE D'IDENTIFICATION PARCELLAIRE & LOCALISATION GPS ---
    story.append(Paragraph("1. Fiche d'Identification Parcellaire & Localisation GPS", h2_style))
    gps_str = (
        f"{gps['gps_lat']:.5f}, {gps['gps_lon']:.5f}"
        if gps.get("gps_provided")
        else (f"{assessment['gps_lat']:.5f}, {assessment['gps_lon']:.5f}" if assessment.get("gps_lat") is not None and assessment.get("gps_lon") is not None else "Non fournies")
    )
    idw_hubs = gps.get("idw_hubs") or []
    idw_str = " | ".join(
        f"{h.get('hub')} ({h.get('road_distance_km', 0)} km · {h.get('weight_pct', 0)}%)"
        for h in idw_hubs
        if (h.get("weight_pct") or 0) > 0
    ) or "—"
    bd = ws.get("breakdown") or {}
    ident_rows = [
        ["Référence Dossier", f"{code} | Date : {date_str} | Cabinet : {firm}"],
        ["Coordonnées GPS & Surface", f"GPS : {gps_str} | Superficie : {assessment.get('area_hectares') or '1.0 (réf.)'} ha"],
        [
            "Rattachement Spatial (IDW)",
            f"Pôle proche : {gps.get('selected_hub') or assessment.get('province_hub')} ({_fmt_num(gps.get('distance_hub_km'), ' km')}) | "
            f"N'Djamena : {_fmt_num(gps.get('distance_ndjamena_km'), ' km')} | Décote : -{gps.get('farmgate_discount_pct', 8)}% | IDW : {idw_str}",
        ],
        [
            "Score Unifié & Confiance",
            f"Score Global : {ws.get('total_score', '—')}/100 ({ws.get('verdict', '—')}) "
            f"[Eau {bd.get('hydric_security', {}).get('score', '—')}/50 + Sol {bd.get('soil_quality', {}).get('score', '—')}/30 + Marché {bd.get('market_logistics', {}).get('score', '—')}/20] · {conf_label}",
        ],
    ]
    story.append(_bulletin_table(ident_rows, col_widths=[5.2 * cm, 12.8 * cm]))

    # --- 2. BULLETIN PÉDOLOGIQUE & AGRO-CLIMATIQUE ---
    story.append(Paragraph("2. Bulletin Pédologique & Agro-Climatique (Paramètres, Valeurs & Seuils)", h2_style))
    lab_params = bulletin.get("lab_parameters") or []
    if lab_params:
        b_rows = [["Paramètre mesuré / modélisé", "Valeur Parcelle", "Norme / Seuil", "Statut", "Source & Maille"]]
        for p in lab_params:
            b_rows.append([
                str(p.get("parameter") or "—"),
                str(p.get("value") or "—"),
                str(p.get("optimal") or "—"),
                str(p.get("status") or "—"),
                str(p.get("source") or "—"),
            ])
        story.append(_bulletin_table(b_rows, col_widths=[4.4 * cm, 4.4 * cm, 3.0 * cm, 2.2 * cm, 4.0 * cm]))

    # --- 3. MATRICE COMPARATIVE D'APTITUDE CULTURALE & RENTABILITÉ VÉRIFIABLE ---
    story.append(Paragraph("3. Matrice Comparative d'Aptitude Culturale & Rentabilité Vérifiable", h2_style))
    crop_rows = [["Culture", "Score /100", "Détail (Eau/50 + Sol/30 + Marché/20)", "Prix Bord-Champ", "CA Brut Estimé", "Verdict"]]
    for c in scores.get("crop_assessments") or []:
        cecon = c.get("verified_economics") or {}
        fg_price = cecon.get("farmgate_price_central_xaf_kg")
        w_sc = c.get("water_score", c.get("satellite_score", "—"))
        s_sc = c.get("soil_score", "—")
        m_sc = c.get("market_score", "—")
        crop_rows.append([
            str(c.get("label_fr") or c.get("crop_id")),
            f"{c.get('suitability_score', 0)}/100",
            f"{w_sc} + {s_sc} + {m_sc}",
            f"{fg_price} F/kg" if fg_price is not None else "N/A",
            f"{_fmt_num(c.get('indicative_gross_revenue_xaf'))} F",
            str(c.get("suitability_label") or "—"),
        ])
    story.append(_bulletin_table(crop_rows, col_widths=[2.6 * cm, 2.0 * cm, 4.8 * cm, 2.6 * cm, 3.2 * cm, 2.8 * cm]))

    if econ and econ.get("formula_text"):
        story.append(Spacer(1, 0.12 * cm))
        story.append(
            Paragraph(
                _clean_pdf_text(
                    "Formule : CA Brut = Superficie (ha) x Rendement réf. (834.6 kg/ha World Bank) x Prix ML t+1 (FCFA/kg) x (1 - Décote logistique %)"
                ),
                body_style,
            )
        )
        unc = econ.get("uncertainty_revenue_range_xaf") or []
        unc_str = f" | Fourchette ±{econ.get('mape_pct', '—')}% : {_fmt_num(unc[0])} à {_fmt_num(unc[1])} FCFA" if len(unc) == 2 else ""
        stress_str = f" | Plancher Stress 2024–2026 : {_fmt_num(econ.get('ca_stress_xaf'))} FCFA" if econ.get("ca_stress_xaf") else ""
        story.append(Paragraph(_clean_pdf_text(f"{econ['formula_text']}{unc_str}{stress_str}"), formula_style))

    # Tableau comparatif multi-terrains optionnel si demandé
    if comparison and comparison.get("comparison_table"):
        story.append(Paragraph("Comparatif Multi-Terrains", h2_style))
        comp_rows = [["Terrain", "Pôle", "Dist. marché", "Hum. rac.", "Prix ML", "CA Central", "Rang"]]
        for row in comparison["comparison_table"]:
            comp_rows.append([
                str(row.get("label") or "—"),
                str(row.get("region") or "—"),
                _fmt_num(row.get("distance_hub_km"), " km"),
                f"{row['rainy_root_wetness']:.2f}" if isinstance(row.get("rainy_root_wetness"), (int, float)) else "—",
                _fmt_num(row.get("predicted_xaf_kg"), " F"),
                _fmt_num(row.get("ca_central_xaf")),
                str(row.get("rank_label") or f"#{row.get('rank', '')}"),
            ])
        story.append(_bulletin_table(comp_rows, col_widths=[2.4 * cm, 2.8 * cm, 2.4 * cm, 2.0 * cm, 2.2 * cm, 3.4 * cm, 2.8 * cm]))

    # --- 4. DIAGNOSTIC DES FACTEURS LIMITANTS & PRESCRIPTIONS TECHNIQUES ---
    story.append(Paragraph("4. Diagnostic des Facteurs Limitants & Prescriptions Techniques", h2_style))
    prescriptions = bulletin.get("prescriptions") or []
    for rx in prescriptions:
        story.append(Paragraph(_clean_pdf_text(f"- {rx}"), body_style))
    notes = (assessment.get("agronomist_field_notes") or "").strip()
    if notes:
        story.append(Spacer(1, 0.1 * cm))
        story.append(Paragraph(_clean_pdf_text(f"<b>Observations terrain & Signature Agronome PRO ({firm}) :</b> {notes}"), body_style))
    else:
        story.append(Spacer(1, 0.1 * cm))
        story.append(Paragraph(_clean_pdf_text(f"<b>Signature Agronome PRO :</b> {firm}"), body_style))

    story.append(Spacer(1, 0.12 * cm))
    story.append(
        Paragraph(
            _clean_pdf_text(
                "Sources & Licences : NASA POWER Agro (Public Domain) | World Bank (CC BY 4.0) | WFP (CC BY-IGO 3.0) | FEWS NET (Attribution Required)."
            ),
            body_style,
        )
    )

    def _draw_footer(canvas, pdf_doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 8.0)
        canvas.setFillColor(colors.HexColor("#475569"))
        footer_text = _clean_pdf_text(
            f"Propulse par FreeData.td  |  Verification : {code}  |  Page {pdf_doc.page}"
        )
        canvas.drawString(1.5 * cm, 1.0 * cm, footer_text)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buf.getvalue()
