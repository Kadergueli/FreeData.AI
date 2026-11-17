"""Générateur d'études de marché et rapports PDF PRO basés exclusivement sur les données FreeData.AI."""
from src.reports.pdf_generator import render_market_study_pdf
from src.reports.study_builder import build_market_study_dossier

__all__ = ["build_market_study_dossier", "render_market_study_pdf"]

