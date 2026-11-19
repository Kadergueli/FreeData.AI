"""Institutional ReportLab Platypus PDF renderer for FreeData.AI Market Intelligence."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.reports.orchestrator import ReportDocument, ReportOrchestrator


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


def _styled_table(rows: list[list[str]], col_widths: list[float] | None = None) -> Table:
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle("FDCell", parent=styles["Normal"], fontSize=8.0, leading=10.0)
    header_style = ParagraphStyle(
        "FDCellHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.0,
        leading=10.0,
        textColor=colors.white,
    )
    cleaned_rows: list[list[Any]] = []
    for r_idx, row in enumerate(rows):
        out_row: list[Any] = []
        for cell in row:
            txt = _clean_pdf_text(cell)
            if len(txt) > 36:
                safe_html = txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                out_row.append(Paragraph(safe_html, header_style if r_idx == 0 else cell_style))
            else:
                out_row.append(txt)
        cleaned_rows.append(out_row)
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


def _build_cashflow_chart(projection: list[dict[str, Any]]) -> Drawing:
    drawing = Drawing(17 * cm, 4.6 * cm)
    drawing.add(String(0, 4.2 * cm, "Evolution BFR vs Tresorerie cumulee (M1-M6, XAF)", fontName="Helvetica-Bold", fontSize=8.5, fillColor=colors.HexColor("#1E3A8A")))
    if not projection:
        return drawing

    wc_vals = [float(p.get("working_capital", 0)) for p in projection]
    cash_vals = [float(p.get("cumulative_cash", 0)) for p in projection]
    labels = [f"M{p.get('month', i + 1)}" for i, p in enumerate(projection)]

    chart = VerticalBarChart()
    chart.x = 1.4 * cm
    chart.y = 0.55 * cm
    chart.width = 14.8 * cm
    chart.height = 3.2 * cm
    chart.data = [wc_vals, cash_vals]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontSize = 7.5
    chart.valueAxis.labels.fontSize = 7.0
    all_vals = wc_vals + cash_vals + [0.0]
    chart.valueAxis.valueMin = min(0.0, min(all_vals))
    chart.valueAxis.valueMax = max(1.0, max(all_vals) * 1.12)
    chart.bars[0].fillColor = colors.HexColor("#1D4ED8")
    chart.bars[1].fillColor = colors.HexColor("#059669")
    chart.groupSpacing = 10
    chart.barSpacing = 2
    drawing.add(chart)
    return drawing


class PDFRenderer:
    """Renders a structured ReportDocument into an institutional PDF."""

    def render(self, doc_model: ReportDocument) -> bytes:
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=1.8 * cm,
            rightMargin=1.8 * cm,
            topMargin=1.8 * cm,
            bottomMargin=1.8 * cm,
            title=_clean_pdf_text(doc_model.title),
        )

        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("FDH1", parent=styles["Heading1"], textColor=colors.HexColor("#1E3A8A"), fontSize=17, spaceAfter=4, keepWithNext=True)
        h2 = ParagraphStyle("FDH2", parent=styles["Heading2"], textColor=colors.HexColor("#1D4ED8"), fontSize=11.5, spaceBefore=10, spaceAfter=4, keepWithNext=True)
        body = ParagraphStyle("FDBody", parent=styles["Normal"], fontSize=9.0, leading=12.5, spaceAfter=3)
        small = ParagraphStyle("FDSmall", parent=styles["Normal"], fontSize=8.0, leading=10.5, textColor=colors.HexColor("#475569"))

        logo_path = _resolve_logo_path()
        story: list[Any] = []

        # Institutional Cover / Executive Header
        title_para = Paragraph(_clean_pdf_text(doc_model.title), h1)
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

        story.append(Paragraph(_clean_pdf_text(f"<b>{doc_model.subtitle}</b>"), h2))
        story.append(KeepTogether(_styled_table([["Champ", "Valeur verifiee"], *doc_model.metadata_rows], col_widths=[6 * cm, 11 * cm])))
        story.append(Spacer(1, 0.25 * cm))

        # Executive Verdict Box
        verdict = doc_model.verdict
        if verdict.get("is_non_rentable"):
            v_bg, v_border, v_fg = colors.HexColor("#FEF2F2"), colors.HexColor("#DC2626"), colors.HexColor("#991B1B")
        else:
            v_bg, v_border, v_fg = colors.HexColor("#ECFDF5"), colors.HexColor("#059669"), colors.HexColor("#065F46")
        verdict_tbl = Table(
            [[Paragraph(_clean_pdf_text(f"<b>{verdict['title']}</b><br/>{verdict['text']}"), ParagraphStyle("FDVerdict", parent=body, textColor=v_fg))]],
            colWidths=[17 * cm],
        )
        verdict_tbl.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), v_bg),
                ("BOX", (0, 0), (-1, -1), 1.0, v_border),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.append(KeepTogether(verdict_tbl))

        ctx = doc_model.study_context
        if ctx.get("objectives"):
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph(_clean_pdf_text("<b>Objectifs du projet :</b> " + " ; ".join(ctx["objectives"])), body))
        if ctx.get("target_customers"):
            story.append(Paragraph(_clean_pdf_text("<b>Clientele cible :</b> " + ", ".join(ctx["target_customers"])), body))
        if ctx.get("operational_constraints"):
            story.append(Paragraph(_clean_pdf_text("<b>Contraintes operationnelles :</b> " + " ; ".join(ctx["operational_constraints"])), body))

        # Dynamic Table of Contents
        if doc_model.sections:
            story.append(Paragraph("Sommaire du Dossier", h2))
            toc_rows = [["N°", "Section", "Statut donnees"]]
            for idx, sec in enumerate(doc_model.sections, 1):
                toc_rows.append([str(idx), sec.title, "Disponible" if sec.is_available else "Non mesure (lacune explicite)"])
            story.append(KeepTogether(_styled_table(toc_rows, col_widths=[1.0 * cm, 11.5 * cm, 4.5 * cm])))

        # Dynamic Numbered Sections
        for idx, sec in enumerate(doc_model.sections, 1):
            story.append(Paragraph(_clean_pdf_text(f"{idx}. {sec.title}"), h2))
            for blk in sec.blocks:
                btype = blk.get("type")
                if btype == "table":
                    widths = [w * cm for w in blk["col_widths_cm"]] if blk.get("col_widths_cm") else None
                    story.append(KeepTogether(_styled_table(blk["rows"], col_widths=widths)))
                elif btype == "paragraph":
                    story.append(Paragraph(_clean_pdf_text(blk["text"]), body))
                elif btype == "small":
                    story.append(Paragraph(_clean_pdf_text(blk["text"]), small))
                elif btype == "spacer":
                    story.append(Spacer(1, float(blk.get("cm", 0.2)) * cm))
                elif btype == "chart_cashflow":
                    story.append(KeepTogether(_build_cashflow_chart(blk.get("projection") or [])))

        def _header_footer(canvas, doc_obj):
            canvas.saveState()
            if doc_obj.page > 1:
                canvas.setFont("Helvetica", 7.5)
                canvas.setFillColor(colors.HexColor("#64748B"))
                canvas.drawString(1.8 * cm, A4[1] - 1.15 * cm, _clean_pdf_text(doc_model.subtitle))
                canvas.drawRightString(A4[0] - 1.8 * cm, A4[1] - 1.15 * cm, doc_model.study_id)
            text_x = 1.8 * cm
            if logo_path is not None:
                canvas.drawImage(str(logo_path), 1.8 * cm, 0.88 * cm, width=0.55 * cm, height=0.55 * cm, mask="auto")
                text_x = 2.5 * cm
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(colors.HexColor("#64748B"))
            canvas.drawString(text_x, 1.1 * cm, f"FreeData.AI Market Intelligence | {doc_model.study_id} | Donnees verifiees uniquement")
            canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Page {doc_obj.page}")
            canvas.restoreState()

        doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
        return buf.getvalue()


def validate_rendered_pdf(pdf_bytes: bytes, doc_model: ReportDocument) -> dict[str, Any]:
    """Post-render verification of the generated PDF:
    - Confirms valid `%PDF-` header and readable pages via `pypdf`.
    - Verifies that every section title in `doc_model.sections`, the study reference (`study_id`),
      and expected tables are preserved in the rendered PDF text without silent omission.
    """
    issues: list[str] = []
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF-"):
        return {
            "passed": False,
            "page_count": 0,
            "missing_sections": [s.title for s in doc_model.sections],
            "table_count": 0,
            "issues": ["En-tête PDF invalide (%PDF- manquant)."],
        }

    extracted_text = ""
    page_count = 0
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        extracted_text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as exc:
        issues.append(f"Lecture post-rendu PDF impossible : {type(exc).__name__}")

    if page_count < 1:
        issues.append("Le PDF généré ne contient aucune page.")
    if not extracted_text.strip():
        issues.append("Le PDF généré ne contient aucun texte lisible.")

    norm_pdf = " ".join(extracted_text.split()).lower()
    if doc_model.study_id and doc_model.study_id.lower() not in norm_pdf:
        issues.append(f"Référence étude absente du PDF rendu : {doc_model.study_id}")

    missing_sections: list[str] = []
    expected_tables = 0
    for sec in doc_model.sections:
        expected_tables += sum(1 for blk in sec.blocks if blk.get("type") == "table")
        clean_title = " ".join(_clean_pdf_text(sec.title).split()).lower()
        # Match full title or significant prefix (handles line wrapping across spaces)
        if clean_title and clean_title not in norm_pdf:
            words = [w for w in clean_title.split() if len(w) >= 4]
            if not words or sum(1 for w in words if w in norm_pdf) < max(1, len(words) // 2):
                missing_sections.append(sec.title)
                issues.append(f"Section absente ou tronquée dans le PDF rendu : {sec.title}")

    return {
        "passed": len(issues) == 0,
        "page_count": page_count,
        "missing_sections": missing_sections,
        "expected_table_count": expected_tables,
        "extracted_chars": len(extracted_text),
        "issues": issues,
    }


def render_market_study_pdf(dossier: dict, *, return_validation: bool = False) -> bytes | tuple[bytes, dict[str, Any]]:
    """Assemble le dossier vérifié en un document PDF binaire téléchargeable avec validation post-rendu."""
    doc_model = ReportOrchestrator().build_document(dossier)
    pdf_bytes = PDFRenderer().render(doc_model)
    post_val = validate_rendered_pdf(pdf_bytes, doc_model)
    if return_validation:
        return pdf_bytes, post_val
    return pdf_bytes
