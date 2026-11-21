"""Générateur PDF co-brandé pour les diagnostics de terrain Agronome PRO."""
from __future__ import annotations

from io import BytesIO
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from src.reports.pdf_generator import _clean_pdf_text, _resolve_logo_path, _styled_table


def render_agro_assessment_pdf(
    assessment: dict[str, Any],
    *,
    agronomist_name: Optional[str] = None,
) -> bytes:
    """Construit un rapport PDF A4 co-brandé (en-tête agronome + badge verrouillé FreeData.td)."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title="Diagnostic Agronomique de Terrain — FreeData.td",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AgroTitle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        "AgroH2",
        parent=styles["Heading2"],
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor("#1D4ED8"),
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "AgroBody",
        parent=styles["Normal"],
        fontSize=9.2,
        leading=13,
        textColor=colors.HexColor("#334155"),
    )
    badge_style = ParagraphStyle(
        "AgroBadge",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#15803D"),
    )

    scores = assessment.get("computed_scores") or {}
    lab = assessment.get("lab_soil_inputs") or {}
    code = assessment.get("report_verification_code") or "FDT-VERIFY"
    firm = (agronomist_name or "").strip() or "Agronome / Bureau d'études"

    story: list[Any] = []
    logo = _resolve_logo_path()
    if logo is not None:
        try:
            story.append(Image(str(logo), width=1.4 * cm, height=1.4 * cm))
            story.append(Spacer(1, 0.2 * cm))
        except Exception:
            pass

    story.append(Paragraph(_clean_pdf_text(f"{firm}  |  Code : {code}"), badge_style))
    story.append(Paragraph(_clean_pdf_text("Propulsé par FreeData.td — Badge vérifié"), badge_style))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(_clean_pdf_text("Diagnostic agronomique de terrain (pré-achat)"), title_style))
    story.append(
        Paragraph(
            _clean_pdf_text(
                f"Zone : {assessment.get('province_hub')} ({scores.get('province') or ''})  |  "
                f"Superficie : {assessment.get('area_hectares') or 'N/A'} ha  |  "
                f"Confiance : {scores.get('confidence_level') or 'Terrain + Régional'}"
            ),
            body_style,
        )
    )
    if assessment.get("gps_lat") is not None and assessment.get("gps_lon") is not None:
        story.append(
            Paragraph(
                _clean_pdf_text(f"Coordonnées GPS : {assessment['gps_lat']:.5f}, {assessment['gps_lon']:.5f}"),
                body_style,
            )
        )

    story.append(Paragraph("1. Mesures de sol saisies (laboratoire / terrain)", h2_style))
    lab_rows = [["Paramètre", "Valeur saisie"]]
    for k, label in (
        ("ph", "pH du sol"),
        ("texture", "Texture"),
        ("organic_matter", "Matière organique (%)"),
        ("nitrogen", "Azote (N)"),
        ("phosphorus", "Phosphore (P)"),
        ("potassium", "Potassium (K)"),
    ):
        v = lab.get(k)
        if v is not None and str(v).strip() != "":
            lab_rows.append([label, str(v)])
    story.append(_styled_table(lab_rows, col_widths=[7.5 * cm, 9.5 * cm]))

    notes = (assessment.get("agronomist_field_notes") or "").strip()
    if notes:
        story.append(Paragraph("2. Notes d'inspection de l'agronome", h2_style))
        story.append(Paragraph(_clean_pdf_text(notes), body_style))

    story.append(Paragraph("3. Aptitude des cultures & couplage prix de marché", h2_style))
    crop_rows = [["Culture", "Score", "Aptitude", "Prix prévu (XAF/kg)", "Facteurs limitants"]]
    for c in scores.get("crop_assessments") or []:
        mkt = c.get("market_forecast") or {}
        price_str = f"{mkt['predicted_xaf_kg']}" if mkt.get("predicted_xaf_kg") is not None else "N/A"
        lim = "; ".join(c.get("limiting_factors") or []) or "Aucun facteur limitant majeur"
        crop_rows.append([
            str(c.get("label_fr") or c.get("crop_id")),
            f"{c.get('suitability_score', 0)}/100",
            str(c.get("suitability_label") or ""),
            price_str,
            lim,
        ])
    story.append(_styled_table(crop_rows, col_widths=[3.0 * cm, 1.8 * cm, 2.5 * cm, 3.2 * cm, 6.5 * cm]))

    prov = scores.get("provenance") or {}
    story.append(Paragraph("4. Provenance, licences & limites d'utilisation", h2_style))
    story.append(
        Paragraph(
            _clean_pdf_text(
                f"Sources régionales : {', '.join(prov.get('sources') or [])} "
                f"({', '.join(prov.get('licenses') or [])}). "
                f"Période : {(prov.get('reference_period') or {}).get('first', '—')} -> "
                f"{(prov.get('reference_period') or {}).get('last', '—')}."
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
        canvas.drawString(1.8 * cm, 1.0 * cm, footer_text)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buf.getvalue()

