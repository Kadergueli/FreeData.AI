"""Générateur PDF exécutif co-brandé — Bulletin d'Analyse Agronomique & Pédologique en 4 sections."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.reports.pdf_generator import _clean_pdf_text, _resolve_logo_path


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
    """Construit un Bulletin d'Analyse Agronomique & Pédologique A4 sans chevauchement de texte."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.4 * cm,
        rightMargin=1.4 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.5 * cm,
        title="Bulletin d'Analyse Agronomique & Pédologique — FreeData.td",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AgroTitle",
        parent=styles["Heading1"],
        fontSize=13.5,
        leading=17,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )
    h2_style = ParagraphStyle(
        "AgroH2",
        parent=styles["Heading2"],
        fontSize=10.2,
        leading=13.5,
        textColor=colors.HexColor("#0284C7"),
        spaceBefore=9,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "AgroBody",
        parent=styles["Normal"],
        fontSize=8.3,
        leading=11.5,
        textColor=colors.HexColor("#334155"),
    )
    bold_style = ParagraphStyle(
        "AgroBold",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0F172A"),
    )
    cell_style = ParagraphStyle(
        "AgroCell",
        parent=styles["Normal"],
        fontSize=8.0,
        leading=10.5,
        textColor=colors.HexColor("#0F172A"),
    )
    cell_bold_style = ParagraphStyle(
        "AgroCellBold",
        parent=cell_style,
        fontName="Helvetica-Bold",
    )
    formula_style = ParagraphStyle(
        "AgroFormula",
        parent=styles["Normal"],
        fontName="Courier-Bold",
        fontSize=7.8,
        leading=10.8,
        textColor=colors.HexColor("#0F172A"),
    )

    def _make_table(rows: list[list[Any]], col_widths: list[float], *, has_header: bool = True) -> Table:
        wrapped: list[list[Paragraph]] = []
        for r_idx, row in enumerate(rows):
            is_hdr = has_header and r_idx == 0
            w_row: list[Paragraph] = []
            for c_idx, cell in enumerate(row):
                st = cell_bold_style if (is_hdr or (not has_header and c_idx == 0)) else cell_style
                w_row.append(Paragraph(_clean_pdf_text(str(cell)), st))
            wrapped.append(w_row)
        tbl = Table(wrapped, colWidths=col_widths, repeatRows=1 if has_header else 0)
        style_cmds: list[Any] = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        if has_header:
            style_cmds.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F9FF")))
            for r_idx in range(1, len(wrapped)):
                bg = colors.HexColor("#FFFFFF") if r_idx % 2 == 1 else colors.HexColor("#F8FAFC")
                style_cmds.append(("BACKGROUND", (0, r_idx), (-1, r_idx), bg))
        else:
            for r_idx in range(len(wrapped)):
                style_cmds.append(("BACKGROUND", (0, r_idx), (0, r_idx), colors.HexColor("#F0F9FF")))
                style_cmds.append(("BACKGROUND", (1, r_idx), (-1, r_idx), colors.HexColor("#FFFFFF")))
        tbl.setStyle(TableStyle(style_cmds))
        return tbl

    scores = assessment.get("computed_scores") or {}
    gps = scores.get("gps_logistics") or {}
    ws = scores.get("weighted_score") or {}
    econ = scores.get("verified_economics") or {}
    bulletin = scores.get("bulletin") or {}
    point_satellite = scores.get("point_satellite_data") or {}
    point_season = point_satellite.get("growing_season") or {}
    code = assessment.get("report_verification_code") or "FDT-VERIFY"
    firm = (agronomist_name or "").strip() or "Agronome / Bureau d'études"
    lic = (agronomist_license or "").strip()
    addr = (agronomist_address or "").strip()
    contact = (agronomist_contact or "").strip()
    date_str = str(assessment.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    has_lab = bool(scores.get("has_lab_measurements"))
    conf_label = scores.get("confidence_level") or (
        "Données de laboratoire fournies — certification non vérifiée"
        if has_lab
        else "Satellite IDW Uniquement — En attente d'analyse physique"
    )
    qa_badge = "DONNÉES LABORATOIRE FOURNIES — VALIDATION REQUISE" if has_lab else "ESTIMATION RÉGIONALE — SANS MESURE LABORATOIRE"
    gps_provided = bool(gps.get("gps_provided") or assessment.get("gps_lat") is not None and assessment.get("gps_lon") is not None)
    resolution_title = (
        "PRÉ-DIAGNOSTIC AGRONOMIQUE — DONNÉES LABORATOIRE FOURNIES"
        if has_lab
        else (
            "PRÉ-DIAGNOSTIC AGRO-CLIMATIQUE & ÉCONOMIQUE (ESTIMATION SATELLITAIRE GÉORÉFÉRENCÉE)"
            if gps_provided
            else "PRÉ-DIAGNOSTIC AGRO-CLIMATIQUE & ÉCONOMIQUE (MAILLE RÉGIONALE — GPS NON FOURNI)"
        )
    )
    soil_basis = scores.get("soil_basis")
    soil_cap = 22 if soil_basis == "soilgrids_zonal" else 15 if soil_basis == "satellite_proxy" else None
    soil_method = (
        "SoilGrids zonal"
        if soil_basis == "soilgrids_zonal"
        else "proxy satellitaire"
        if soil_basis == "satellite_proxy"
        else "estimation pédologique"
    )
    soil_cap_text = f" (plafond modèle : {soil_cap}/30 pts)" if soil_cap is not None else ""

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
        f"<b>BULLETIN D'ANALYSE AGRONOMIQUE & PÉDOLOGIQUE</b><br/>"
        f"Statut : <b>{qa_badge}</b><br/>"
        f"Réf. : {code} | Date : {date_str}<br/>"
        f"Confiance : {conf_label}"
    )
    qr_payload = f"FreeData.td|REF:{code}|SCORE:{ws.get('total_score', '-')}/100|CABINET:{firm[:36]}"
    qr_widget = QrCodeWidget(qr_payload)
    qr_bounds = qr_widget.getBounds()
    qr_size = 1.75 * cm
    qr_w = max(1.0, qr_bounds[2] - qr_bounds[0])
    qr_h = max(1.0, qr_bounds[3] - qr_bounds[1])
    qr_drawing = Drawing(qr_size, qr_size, transform=[qr_size / qr_w, 0, 0, qr_size / qr_h, 0, 0])
    qr_drawing.add(qr_widget)
    header_tbl = Table(
        [[left_cells, Paragraph(right_html, body_style), qr_drawing]],
        colWidths=[8.0 * cm, 8.2 * cm, 2.0 * cm],
    )
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
                    f"<b>AVERTISSEMENT SATELLITAIRE :</b> Mesures de sol laboratoire non fournies — "
                    f"la composante sol repose sur {soil_method}{soil_cap_text} ; cette estimation ne remplace pas une analyse physique."
                ),
                body_style,
            )]],
            colWidths=[18.2 * cm],
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
    usable_w = 18.2 * cm
    gps_str = (
        f"{gps['gps_lat']:.5f}, {gps['gps_lon']:.5f}"
        if gps.get("gps_provided")
        else (
            f"{assessment['gps_lat']:.5f}, {assessment['gps_lon']:.5f}"
            if assessment.get("gps_lat") is not None and assessment.get("gps_lon") is not None
            else "Non fournies — Maille pôle par défaut"
        )
    )
    idw_hubs = gps.get("idw_hubs") or []
    idw_str = (
        " | ".join(
            f"{h.get('hub')} ({h.get('road_distance_km', 0)} km · {h.get('weight_pct', 0)}%)"
            for h in idw_hubs
            if (h.get("weight_pct") or 0) > 0
        )
        if gps.get("gps_provided") and idw_hubs
        else "Maille régionale du pôle (100%) — coordonnées GPS non fournies"
    )
    firm_label = f"{firm} (N° {lic})" if lic else firm
    hub_name = gps.get("selected_hub") or assessment.get("province_hub") or "—"
    prov_name = assessment.get("province") or gps.get("province") or hub_name
    area_raw = assessment.get("area_hectares")
    area_val = (
        f"{float(area_raw):g} (superficie déclarée ; {float(area_raw) * 10000:,.0f} m²)".replace(",", " ")
        if isinstance(area_raw, (int, float)) and float(area_raw) > 0
        else "Non renseignée — aucune projection surfacique fiable"
    )
    bd = ws.get("breakdown") or {}
    ident_rows = [
        [
            "Dossier & Cabinet",
            f"Référence Dossier : {code} | Cabinet : {firm_label}",
        ],
        [
            "GPS & Superficie",
            f"Coordonnées GPS : {gps_str} | Superficie : {area_val} ha",
        ],
        [
            "Rattachement Spatial",
            f"Pôle {hub_name} ({prov_name}) | Distance N'Djamena : {_fmt_num(gps.get('distance_ndjamena_km'), ' km')} | Décote bord-champ : -{gps.get('farmgate_discount_pct', 8)}%",
        ],
        [
            "Pondération IDW",
            idw_str,
        ],
        [
            "Score Unifié & Confiance",
            f"Score Global : {ws.get('total_score', '—')}/100 ({ws.get('verdict', '—')}) "
            f"[Eau {bd.get('hydric_security', {}).get('score', '—')}/{bd.get('hydric_security', {}).get('max', '—')} + Sol {bd.get('soil_quality', {}).get('score', '—')}/{bd.get('soil_quality', {}).get('max', '—')} + Marché {bd.get('market_logistics', {}).get('score', '—')}/{bd.get('market_logistics', {}).get('max', '—')}] · {conf_label}",
        ],
    ]
    story.append(_make_table(ident_rows, col_widths=[4.6 * cm, usable_w - 4.6 * cm], has_header=False))

    # --- 1 BIS. LOCALISATION, SUPERFICIE ET PROVENANCE DES DONNÉES ---
    site_ctx = scores.get("site_context") or {}
    coords = site_ctx.get("coordinates") or {}
    climate_hubs = site_ctx.get("climate_hubs") or []
    hub_weights = ", ".join(
        f"{h.get('hub')} : {h.get('road_distance_km', h.get('distance_km'))} km / {h.get('weight_pct')} %"
        for h in climate_hubs if (h.get("weight_pct") or 0) > 0
    ) or "Aucun pôle IDW disponible"
    soil_values = site_ctx.get("soil_values") or {}
    soil_values_text = "; ".join(f"{key} : {value}" for key, value in soil_values.items() if value is not None) or "Aucune valeur régionale disponible"
    lab_values = site_ctx.get("laboratory_values") or {}
    lab_values_text = "; ".join(f"{key} : {value}" for key, value in lab_values.items() if value is not None) or "Aucune mesure déclarée"
    location_rows = [
        ["Élément", "Valeur / provenance"],
        ["Coordonnées du site", f"Latitude {coords.get('latitude')} ; longitude {coords.get('longitude')}" if coords.get("provided") else "Non fournies — rattachement régional"],
        ["Superficie déclarée", area_val + (" ha" if area_raw is not None else "")],
        ["Méthode climatique", str(site_ctx.get("climate_method") or "Données régionales du pôle")],
        ["Pôles IDW contributeurs", hub_weights],
        ["Méthode pédologique", str(site_ctx.get("soil_method") or "Non documentée")],
        ["Mesures déclarées (non vérifiées)", lab_values_text],
        ["Valeurs pédologiques régionales", soil_values_text],
    ]
    story.append(Paragraph("1 bis. Localisation, superficie et provenance des données", h2_style))
    story.append(_make_table(location_rows, col_widths=[4.6 * cm, usable_w - 4.6 * cm]))
    story.append(Spacer(1, 0.12 * cm))
    story.append(Paragraph(
        _clean_pdf_text(str(site_ctx.get("area_usage") or
            "La superficie est une donnée déclarée. Sans contour géographique, les valeurs satellitaires et pédologiques ne constituent pas des moyennes de toute la parcelle.")),
        body_style,
    ))

    # --- 2. BULLETIN PÉDOLOGIQUE & AGRO-CLIMATIQUE ---
    story.append(Paragraph("2. Bulletin Pédologique & Agro-Climatique (Paramètres, Valeurs & Seuils)", h2_style))
    lab_params = bulletin.get("lab_parameters") or []
    if lab_params:
        b_rows = [["Paramètre mesuré / modélisé", "Valeur Parcelle", "Norme / Seuil", "Statut", "Source & Maille"]]
        for p in lab_params:
            b_rows.append([
                str(p.get("parameter") or "—"),
                (str(p.get("value") or "—") + (f" {p.get('unit')}" if p.get("unit") else "")),
                str(p.get("optimal") or "—"),
                str(p.get("status") or "—"),
                str(p.get("source") or "—"),
            ])
        b_widths = [0.32 * usable_w, 0.26 * usable_w, 0.16 * usable_w, 0.11 * usable_w, 0.15 * usable_w]
        story.append(_make_table(b_rows, col_widths=b_widths))

    if point_satellite:
        story.append(Spacer(1, 0.12 * cm))
        point_coords = point_satellite.get("coordinates") or {
            "latitude": point_satellite.get("latitude"),
            "longitude": point_satellite.get("longitude"),
        }
        point_prov = point_satellite.get("provenance") or {}
        point_parameter_meta = point_satellite.get("parameter_metadata") or {}
        precipitation_unit = (point_parameter_meta.get("IMERG_PRECTOT") or {}).get("unit") or "unité non précisée"
        point_rows = [
            ["Donnée satellitaire au point GPS", "Valeur / Métadonnée"],
            ["Coordonnées interrogées", f"{point_coords.get('latitude', '—')}, {point_coords.get('longitude', '—')}"],
            ["Humidité racinaire moyenne (juin–sept.)", _fmt_num(point_season.get("root_zone_wetness_mean")) + " (fraction 0–1)"],
            ["Humidité de surface moyenne (juin–sept.)", _fmt_num(point_season.get("surface_wetness_mean")) + " (fraction 0–1)"],
            ["Précipitations moyennes (juin–sept.)", f"{_fmt_num(point_season.get('precipitation_mean'))} {precipitation_unit}"],
            ["Température moyenne (juin–sept.)", _fmt_num(point_season.get("temperature_mean_c"), " °C")],
            ["Période / climatologie", str(point_prov.get("reference_period") or point_satellite.get("reference_period") or "Non précisée par le fournisseur")],
            ["Date de récupération UTC", str(point_prov.get("retrieved_at_utc") or point_satellite.get("retrieved_at_utc") or "—")],
            ["Maille", str(point_prov.get("resolution") or point_satellite.get("spatial_resolution") or "Résolution native variable selon le paramètre")],
            ["Portée spatiale", "Échantillon satellitaire au point GPS fourni; ce n'est pas une moyenne de toute la superficie. Une géométrie de parcelle (polygone) est nécessaire pour une agrégation surfacique."],
        ]
        story.append(_make_table(point_rows, col_widths=[7.0 * cm, usable_w - 7.0 * cm], has_header=True))
    elif gps_provided:
        story.append(Paragraph(
            _clean_pdf_text("NASA POWER au point GPS indisponible au moment du calcul : les indicateurs climatiques affichés proviennent du repli IDW/régional indiqué dans la colonne Source & Maille. Aucune valeur ponctuelle n'a été inventée."),
            body_style,
        ))

    # --- 3. MATRICE COMPARATIVE D'APTITUDE CULTURALE & RENTABILITÉ VÉRIFIABLE ---
    story.append(Paragraph("3. Matrice Comparative d'Aptitude Culturale & Rentabilité Vérifiable", h2_style))
    crop_rows = [["Culture", "Score /100", "Détail (Eau + Sol + Marché)", "Prix Bord-Champ", "CA Brut Estimé", "Verdict"]]
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
            f"{fg_price} FCFA/kg" if fg_price is not None else "N/A",
            f"{_fmt_num(c.get('indicative_gross_revenue_xaf'))} FCFA",
            str(c.get("suitability_label") or "—"),
        ])
    c_widths = [0.20 * usable_w, 0.12 * usable_w, 0.22 * usable_w, 0.16 * usable_w, 0.16 * usable_w, 0.14 * usable_w]
    story.append(_make_table(crop_rows, col_widths=c_widths))

    if econ and econ.get("formula_text"):
        story.append(Spacer(1, 0.18 * cm))
        unc = econ.get("uncertainty_revenue_range_xaf") or []
        area_f = econ.get("area_hectares", 1.0)
        y_f = econ.get("yield_kg_ha", 834.6)
        p_ml = econ.get("predicted_market_xaf_kg")
        disc_f = econ.get("farmgate_discount_pct", 8)
        ca_c = _fmt_num(econ.get("ca_central_xaf"))
        if isinstance(p_ml, (int, float)):
            line1 = f"Formule appliquée : {area_f:g} ha x {y_f:.1f} kg/ha (source rendement : {econ.get('yield_source') or 'non précisée'}) x {p_ml:.1f} FCFA/kg (prix marché prédit) x (1 - {disc_f:g}% de décote bord-champ) = {ca_c} FCFA"
        else:
            line1 = f"Calcul de production : {area_f:g} ha x {y_f:.1f} kg/ha = {y_f * area_f:,.1f} kg ; chiffre d'affaires non calculable (prix marché indisponible)"
        if len(unc) == 2:
            line2 = f"Intervalle de confiance modèle (± {econ.get('mape_pct', '—')}% MAPE hors-temps) : {_fmt_num(unc[0])} FCFA à {_fmt_num(unc[1])} FCFA"
        else:
            line2 = "Intervalle de confiance modèle : non disponible"
        stress_scen = next((s for s in (econ.get("scenarios") or []) if s.get("id") == "stress_floor"), {})
        p_min = stress_scen.get("market_price_xaf_kg", "—")
        ca_s = _fmt_num(econ.get("ca_stress_xaf"))
        stress_farmgate = stress_scen.get("farmgate_price_xaf_kg", "—")
        line3 = f"Scénario Plancher Stress (prix marché min. historique : {p_min} FCFA/kg ; après décote bord-champ : {stress_farmgate} FCFA/kg) : CA brut estimé {ca_s} FCFA"

        formula_box = Table(
            [
                [Paragraph(_clean_pdf_text(line1), formula_style)],
                [Paragraph(_clean_pdf_text(line2), formula_style)],
                [Paragraph(_clean_pdf_text(line3), formula_style)],
            ],
            colWidths=[usable_w],
        )
        formula_box.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ])
        )
        story.append(formula_box)

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
        story.append(_make_table(comp_rows, col_widths=[2.6 * cm, 2.8 * cm, 2.4 * cm, 2.0 * cm, 2.2 * cm, 3.4 * cm, 2.8 * cm]))

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
    # --- 5. PROVENANCE, LICENCES & LIMITES DES DONNÉES ---
    story.append(Paragraph("5. Provenance, Licences & Limites des Données", h2_style))
    prov_blocks = [
        ("Indicateurs régionaux", scores.get("provenance") or {}),
        ("Indicateurs nationaux", scores.get("national_provenance") or {}),
    ]
    site = scores.get("site_profile") or {}
    site_sources: set[str] = set()
    if (site.get("soil") or {}).get("provenance"):
        sp = (site.get("soil") or {})["provenance"]
        if sp.get("source"):
            site_sources.add(str(sp["source"]).casefold())
        story.append(Paragraph(
            _clean_pdf_text(
                f"Sol — {sp.get('source', 'Source non précisée')} | Licence : {sp.get('license', 'non précisée')} | "
                f"Résolution : {sp.get('spatial_resolution', 'non précisée')} | {sp.get('note', '')}"
            ), body_style
        ))
        if sp.get("attribution"):
            story.append(Paragraph(_clean_pdf_text(f"Attribution sol : {sp['attribution']}"), body_style))
    if (site.get("climate") or {}).get("provenance"):
        cp = (site.get("climate") or {})["provenance"]
        if cp.get("source"):
            site_sources.add(str(cp["source"]).casefold())
        story.append(Paragraph(
            _clean_pdf_text(
                f"Climat — {cp.get('source', 'Source non précisée')} | Licence : {cp.get('license', 'non précisée')} | "
                f"Résolution : {cp.get('spatial_resolution', 'non précisée')} | {cp.get('note', '')}"
            ), body_style
        ))
        if cp.get("attribution"):
            story.append(Paragraph(_clean_pdf_text(f"Attribution climat : {cp['attribution']}"), body_style))

    for label, prov in prov_blocks:
        sources = prov.get("sources") or []
        licenses = prov.get("licenses") or []
        period = prov.get("reference_period") or {}
        resolutions = prov.get("spatial_resolution") or []
        confidence = prov.get("confidence_level") or []
        if not (sources or licenses or period or resolutions or confidence):
            continue
        period_text = (
            f"{period.get('first', '—')} à {period.get('last', '—')}"
            if isinstance(period, dict) else str(period)
        )
        story.append(Paragraph(
            _clean_pdf_text(
                f"{label} — Sources : {', '.join(map(str, sources)) or 'non renseignées'} | "
                f"Licences déclarées : {', '.join(map(str, licenses)) or 'non renseignées'} | "
                f"Période : {period_text} | Maille : {', '.join(map(str, resolutions)) or 'non renseignée'} | "
                f"Confiance : {', '.join(map(str, confidence)) or 'non précisée'}"
            ), body_style
        ))
    # Références bibliographiques : n'afficher que les fournisseurs réellement présents dans ce dossier.
    source_names = {
        str(name).casefold()
        for _label, prov in prov_blocks
        for name in (prov.get("sources") or [])
    } | site_sources
    reference_rows: list[tuple[str, str]] = []
    if any("soilgrids" in name for name in source_names):
        reference_rows.append((
            "SoilGrids 2.0 — Poggio, L., de Sousa, L. M., Batjes, N. H., Heuvelink, G. B. M., "
            "Kempen, B., Ribeiro, E. and Rossiter, D. (2021). SoilGrids 2.0: producing soil information "
            "for the globe with quantified spatial uncertainty. SOIL, 7, 217–240. "
            "https://doi.org/10.5194/soil-7-217-2021. Données CC BY 4.0 ; attribution ISRIC.",
            "Documentation et politique de partage : https://docs.isric.org/globaldata/soilgrids/"
        ))
    if any("nasa power" in name for name in source_names):
        reference_rows.append((
            "NASA POWER — NASA Langley Research Center, Prediction of Worldwide Energy Resources. "
            "Référence officielle du projet ; la version du service et la date d'accès ne sont pas "
            "conservées dans les métadonnées de ce dossier.",
            "Guide de citation : https://power.larc.nasa.gov/docs/referencing/ | "
            "Services et résolution : https://power.larc.nasa.gov/docs/services/"
        ))
    if any("world bank" in name for name in source_names):
        reference_rows.append((
            "World Bank — indicateurs de la Banque mondiale. La licence CC BY 4.0 est déclarée "
            "pour les lignes utilisées ; vérifier les conditions propres à chaque jeu de données.",
            "Conditions et licences des jeux de données : https://datacatalog.worldbank.org/public-licenses"
        ))
    if reference_rows:
        story.append(Paragraph("6. Références bibliographiques & documentation des fournisseurs", h2_style))
        for citation, reference_url in reference_rows:
            story.append(Paragraph(_clean_pdf_text(citation), body_style))
            story.append(Paragraph(_clean_pdf_text(reference_url), body_style))
    story.append(Spacer(1, 0.08 * cm))
    story.append(
        Paragraph(
            _clean_pdf_text(
                "Limites : les valeurs régionales, zonales ou satellitaires sont des estimations et ne constituent pas des mesures de la parcelle. "
                "Les rendements de référence, prix prédits, décotes logistiques et chiffres d'affaires sont des hypothèses de modèle, non des garanties de production ou de vente. "
                "Vérifier les licences, dates et conditions de réutilisation auprès de chaque fournisseur avant toute redistribution."
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
        canvas.drawString(1.4 * cm, 1.0 * cm, footer_text)
        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buf.getvalue()
