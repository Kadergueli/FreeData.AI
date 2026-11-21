"""Rendu PDF de l'évaluation de terrain (co-branding, provenance, QA). Le titre vient du QA gate, jamais du client."""
from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape


def _p(text: Any, style) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")), style)


def render_assessment_pdf(a: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=a["title"], author="FreeData.AI")
    base = getSampleStyleSheet()
    brand = colors.HexColor(a["branding"]["primary_color"])
    h1 = ParagraphStyle("h1", parent=base["Title"], textColor=brand, fontSize=18, alignment=0)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], textColor=brand)
    body = ParagraphStyle("b", parent=base["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#555555"))

    flow: list = []
    org = a["branding"].get("organization_name") or "FreeData.AI"
    flow += [_p(org, small), _p(a["title"], h1),
             _p(f"Hub : {a['hub']} ({a['region']}) · Généré le {a['generated_at'][:10]}"
                + (f" · Culture : {a['crop']}" if a.get("crop") else ""), body)]
    if a.get("downgraded"):
        flow += [Spacer(1, 6), _p("Mesures de sol absentes ou incomplètes : ce document est un pré-diagnostic de zone uniquement.", body)]
    flow += [Spacer(1, 8), _p("Indicateurs de zone (NASA POWER)", h2)]
    rows = [["Indicateur", "Valeur", "Mois de référence", "Résolution", "Confiance", "Licence"]]
    for i in a["zone_indicators"]:
        p = i["provenance"]
        rows.append([_p(i["label"], small), f"{i['value']} {i['unit']}", p["reference_date"][:7],
                     _p(p["spatial_resolution"], small), _p(p["confidence_level"], small), _p(p["license"], small)])
    t = Table(rows, repeatRows=1, colWidths=[4.2 * cm, 2.6 * cm, 2.2 * cm, 2.6 * cm, 2.6 * cm, 3 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), brand), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flow += [t, Spacer(1, 4), _p(f"Source : {a['zone_indicators'][0]['provenance']['source']}.", small)]

    if a["soil"]:
        flow += [Spacer(1, 8), _p("Mesures de sol (fournies par l'agronome)", h2)]
        labels = {"ph": "pH", "organic_matter_pct": "Matière organique (%)", "texture": "Texture",
                  "sampling_date": "Date de prélèvement", "lab_name": "Laboratoire"}
        flow.append(Table([[labels[k], str(v)] for k, v in a["soil"].items() if k in labels],
                          colWidths=[6 * cm, 6 * cm], style=TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey)])))
    if a["findings"]:
        flow += [Spacer(1, 8), _p("Constats", h2)] + [_p("• " + f, body) for f in a["findings"]]
    flow += [Spacer(1, 8), _p("Contrôle qualité", h2)]
    flow += [_p(("✓ " if c["ok"] else "✗ ") + c["detail"], body) for c in a["qa"]["checks"]]
    flow += [Spacer(1, 10), _p(a["resolution_notice"], small), _p(a["disclaimer"], small)]
    if a["branding"].get("agronomist_name"):
        flow += [Spacer(1, 6), _p(f"Agronome : {a['branding']['agronomist_name']}", body)]
    doc.build(flow)
    return buf.getvalue()
