import dataclasses

import numpy as np
import pandas as pd

from src import ai_agent
from src.ai_agent import (
    FreeDataAIAgent,
    MarketDataProvider,
    extract_business_params,
)


def _sample_business_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fc_df = pd.DataFrame(
        [
            # Mil : pas cher à Tandjile (250), cher à Ouaddai (400), modéré à N'Djamena (360)
            {
                "province": "Tandjile",
                "market_name": "Kelo",
                "commodity_std": "Millet",
                "predicted_price": 250.0,
                "last_price": 240.0,
                "forecast_t1": 250.0,
                "last_observed_price": 240.0,
            },
            {
                "province": "Ouaddai",
                "market_name": "Abeche",
                "commodity_std": "Millet",
                "predicted_price": 400.0,
                "last_price": 390.0,
                "forecast_t1": 400.0,
                "last_observed_price": 390.0,
            },
            {
                "province": "N'Djamena",
                "market_name": "Dembé",
                "commodity_std": "Millet",
                "predicted_price": 360.0,
                "last_price": 350.0,
                "forecast_t1": 360.0,
                "last_observed_price": 350.0,
            },
            # Sorgho rouge : accessible (<= 450)
            {
                "province": "Logone Occidental",
                "market_name": "Moundou",
                "commodity_std": "Sorghum (red)",
                "predicted_price": 220.0,
                "last_price": 215.0,
                "forecast_t1": 220.0,
                "last_observed_price": 215.0,
            },
            # Maïs blanc : accessible (<= 450)
            {
                "province": "Mayo-Kebbi Ouest",
                "market_name": "Pala",
                "commodity_std": "Maize (white)",
                "predicted_price": 300.0,
                "last_price": 295.0,
                "forecast_t1": 300.0,
                "last_observed_price": 295.0,
            },
            # Riz local : accessible (<= 450) mais predicted_price manquant -> repli sur last_price
            {
                "province": "Tandjile",
                "market_name": "Lai",
                "commodity_std": "Rice (local)",
                "predicted_price": np.nan,
                "last_price": 340.0,
                "forecast_t1": np.nan,
                "last_observed_price": 340.0,
            },
            # Sésame : score élevé mais prix > 450 XAF/kg -> exclu du Top 3 Tremplin débutant
            {
                "province": "Salamat",
                "market_name": "Am Timan",
                "commodity_std": "Sesame",
                "predicted_price": 680.0,
                "last_price": 660.0,
                "forecast_t1": 680.0,
                "last_observed_price": 660.0,
            },
            # Oignon rouge : prix bas mais très volatil
            {
                "province": "Borkou",
                "market_name": "Faya-Largeau",
                "commodity_std": "Onions (red)",
                "predicted_price": 430.0,
                "last_price": 410.0,
                "forecast_t1": 430.0,
                "last_observed_price": 410.0,
            },
            # Niébé : prix pour test destination manquante (présent Tandjile, absent Borkou)
            {
                "province": "Tandjile",
                "market_name": "Kelo",
                "commodity_std": "Beans (niebe)",
                "predicted_price": 250.0,
                "last_price": 245.0,
                "forecast_t1": 250.0,
                "last_observed_price": 245.0,
            },
        ]
    )

    cp_df = pd.DataFrame(
        [
            {
                "province": "Logone Occidental",
                "commodity_std": "Sorghum (red)",
                "score_global": 88.0,
                "credit_score": 88.0,
                "grade": "A",
                "cv_pct": 11.5,
                "max_drawdown_pct": 12.0,
                "ltv_ratio": 0.70,
            },
            {
                "province": "Tandjile",
                "commodity_std": "Millet",
                "score_global": 85.0,
                "credit_score": 85.0,
                "grade": "A",
                "cv_pct": 14.0,
                "max_drawdown_pct": 15.0,
                "ltv_ratio": 0.70,
            },
            {
                "province": "Mayo-Kebbi Ouest",
                "commodity_std": "Maize (white)",
                "score_global": 82.0,
                "credit_score": 82.0,
                "grade": "B",
                "cv_pct": 16.0,
                "max_drawdown_pct": 18.0,
                "ltv_ratio": 0.65,
            },
            {
                "province": "Tandjile",
                "commodity_std": "Rice (local)",
                "score_global": 76.0,
                "credit_score": 76.0,
                "grade": "B",
                "cv_pct": 19.0,
                "max_drawdown_pct": 21.0,
                "ltv_ratio": 0.60,
            },
            {
                "province": "Salamat",
                "commodity_std": "Sesame",
                "score_global": 94.0,
                "credit_score": 94.0,
                "grade": "A",
                "cv_pct": 9.0,
                "max_drawdown_pct": 10.0,
                "ltv_ratio": 0.75,
            },
            # 3 pièges à forte volatilité / drawdown
            {
                "province": "Borkou",
                "commodity_std": "Onions (red)",
                "score_global": 42.0,
                "credit_score": 42.0,
                "grade": "D",
                "cv_pct": 58.0,
                "max_drawdown_pct": 62.0,
                "ltv_ratio": 0.35,
            },
            {
                "province": "Ouaddai",
                "commodity_std": "Millet",
                "score_global": 51.0,
                "credit_score": 51.0,
                "grade": "C",
                "cv_pct": 44.0,
                "max_drawdown_pct": 49.0,
                "ltv_ratio": 0.45,
            },
            {
                "province": "Tandjile",
                "commodity_std": "Beans (niebe)",
                "score_global": 48.0,
                "credit_score": 48.0,
                "grade": "C",
                "cv_pct": 41.0,
                "max_drawdown_pct": 47.0,
                "ltv_ratio": 0.45,
            },
        ]
    )
    hist_df = pd.DataFrame()
    return hist_df, fc_df, cp_df


def test_resolve_route_chadian_cities():
    _, fc_df, cp_df = _sample_business_tables()
    provider = MarketDataProvider(fc_df, cp_df)

    # Formulations directionnelles explicites et villes secondaires du Tchad
    assert provider.resolve_route("Je vends de Kélo à Abéché") == ("Tandjile", "Ouaddai")
    assert provider.resolve_route("depuis Moundou vers N'Djamena") == ("Logone Occidental", "N'Djamena")
    assert provider.resolve_route("à Abéché depuis Béré") == ("Tandjile", "Ouaddai")
    assert provider.resolve_route("de Léré pour Fianga") == ("Mayo-Kebbi Ouest", "Mayo-Kebbi Est")
    assert provider.resolve_route("Goré vers Kyabé") == ("Logone Oriental", "Moyen-Chari")

    # Villes individuelles ajoutées en Spec 1.1
    expected_towns = {
        "béré": "Tandjile",
        "goré": "Logone Oriental",
        "bebedjia": "Logone Oriental",
        "kyabé": "Moyen-Chari",
        "bitkine": "Guera",
        "melfi": "Guera",
        "haraze": "Salamat",
        "fianga": "Mayo-Kebbi Est",
        "léré": "Mayo-Kebbi Ouest",
        "bagasola": "Lac",
        "nokou": "Kanem",
        "oumm hadjer": "Batha",
        "guereda": "Wadi Fira",
        "am-djarass": "Ennedi Est",
        "bokoro": "Hadjer-Lamis",
        "bousso": "Chari-Baguirmi",
        "zouar": "Tibesti",
    }
    for town, expected_prov in expected_towns.items():
        assert provider.resolve_location(f"Prix à {town}") == expected_prov
        assert provider.resolve_route(f"marché de {town}") == (expected_prov, None)

    assert provider.resolve_route("Bonjour") == (None, None)


def test_extract_business_params():
    defaults = extract_business_params("Je veux débuter dans le mil")
    assert defaults == {
        "capital_xaf": 500000.0,
        "transport_cost_per_kg": 25.0,
        "quantity_kg": None,
    }

    p1 = extract_business_params("Avec 500 000 FCFA et transport 30 pour 2.5 tonnes")
    assert p1["capital_xaf"] == 500000.0
    assert p1["transport_cost_per_kg"] == 30.0
    assert p1["quantity_kg"] == 2500.0

    p2 = extract_business_params("Budget de 1.5 million avec fret 40 xaf/kg pour 10 sacs")
    assert p2["capital_xaf"] == 1500000.0
    assert p2["transport_cost_per_kg"] == 40.0
    assert p2["quantity_kg"] == 1000.0

    p3 = extract_business_params("Investir 2 millions pour 350 kg de niébé")
    assert p3["capital_xaf"] == 2000000.0
    assert p3["transport_cost_per_kg"] == 25.0
    assert p3["quantity_kg"] == 350.0


def test_simulate_trade_pnl_profitable_case():
    _, fc_df, cp_df = _sample_business_tables()
    provider = MarketDataProvider(fc_df, cp_df)

    pnl = provider.simulate_trade_pnl(
        commodity="Millet",
        origin_province="Tandjile",
        dest_province="Ouaddai",
        capital_xaf=500000.0,
        transport_cost_per_kg=25.0,
        loss_rate_pct=5.0,
    )
    assert pnl["status"] == "ok"
    assert pnl["buy_price"] == 250.0
    assert pnl["sell_price"] == 400.0
    assert pnl["unit_landed_cost"] == 275.0
    assert pnl["purchasable_kg"] == 1818
    assert pnl["purchasable_bags_100kg"] == 18.18
    assert pnl["actual_invested_xaf"] == 499950.0
    assert pnl["sellable_kg"] == 1727.1
    assert pnl["break_even_price_per_kg"] == 289.5
    assert pnl["gross_revenue_xaf"] == 690840.0
    assert pnl["net_profit_xaf"] == 190890.0
    assert pnl["net_margin_pct"] == 38.2
    assert pnl["is_profitable"] is True

    # Repli sur last_price lorsque predicted_price est NaN (Riz local à Tandjile = 340.0)
    # Destination N'Djamena pour Mil (360) vs seuil 289.5 ou scénario déficitaire avec fret élevé
    unprofitable = provider.simulate_trade_pnl(
        commodity="Millet",
        origin_province="Tandjile",
        dest_province="N'Djamena",
        capital_xaf=500000.0,
        transport_cost_per_kg=100.0,
        loss_rate_pct=5.0,
    )
    assert unprofitable["status"] == "ok"
    assert unprofitable["unit_landed_cost"] == 350.0
    assert unprofitable["break_even_price_per_kg"] == 368.4
    assert unprofitable["is_profitable"] is False
    assert unprofitable["net_profit_xaf"] < 0


def test_simulate_trade_pnl_missing_destination():
    _, fc_df, cp_df = _sample_business_tables()
    provider = MarketDataProvider(fc_df, cp_df)

    res = provider.simulate_trade_pnl(
        commodity="Beans (niebe)",
        origin_province="Tandjile",
        dest_province="Borkou",
        capital_xaf=500000.0,
        transport_cost_per_kg=25.0,
        loss_rate_pct=5.0,
    )
    assert res["status"] == "missing_dest_data"
    assert res["commodity"] == "Beans (niebe)"
    assert res["origin_province"] == "Tandjile"
    assert res["dest_province"] == "Borkou"
    assert res["buy_price"] == 250.0
    assert res["sell_price"] is None
    assert res["unit_landed_cost"] == 275.0
    assert res["purchasable_kg"] == 1818
    assert res["break_even_price_per_kg"] == 289.5

    # Vérifie aussi le repli last_price quand predicted_price est NaN à l'origine
    missing_rice_dest = provider.simulate_trade_pnl(
        commodity="Rice (local)",
        origin_province="Tandjile",
        dest_province="Ouaddai",
        capital_xaf=500000.0,
    )
    assert missing_rice_dest["status"] == "missing_dest_data"
    assert missing_rice_dest["buy_price"] == 340.0

    # Origine sans donnée
    missing_orig = provider.simulate_trade_pnl(
        commodity="Millet",
        origin_province="Borkou",
        dest_province="Ouaddai",
    )
    assert missing_orig["status"] == "missing_origin_data"
    assert missing_orig["buy_price"] is None
    assert missing_orig["sell_price"] == 400.0


def test_get_beginner_market_guide():
    _, fc_df, cp_df = _sample_business_tables()
    provider = MarketDataProvider(fc_df, cp_df)

    guide = provider.get_beginner_market_guide(capital_xaf=500000.0)
    assert guide["status"] == "ok"
    assert guide["capital_xaf"] == 500000.0

    # Top 3 Tremplin : <= 450 XAF/kg, trié par score_global desc puis cv_pct asc
    # Sesame (680 XAF/kg) doit être filtré même avec score 94.0
    tremplins = guide["tremplin_sectors"]
    assert len(tremplins) == 3
    assert [t["commodity_std"] for t in tremplins] == [
        "Sorghum (red)",
        "Millet",
        "Maize (white)",
    ]
    assert all(t["unit_price_xaf"] <= 450.0 for t in tremplins)
    assert tremplins[0]["full_bags_100kg"] == 22  # 500 000 // (220 * 100) = 22 sacs
    assert tremplins[1]["full_bags_100kg"] == 20  # 500 000 // (250 * 100) = 20 sacs

    # 3 pièges à éviter (volatilité / drawdown max)
    pitfalls = guide["pitfalls"]
    assert len(pitfalls) == 3
    assert pitfalls[0]["commodity_std"] == "Onions (red)"
    assert all(p["risk_reason"] for p in pitfalls)

    # Checklist 4 étapes
    checklist = guide["checklist"]
    assert len(checklist) == 4
    assert [c["step"] for c in checklist] == [1, 2, 3, 4]


def test_agent_business_intent_end_to_end(monkeypatch):
    hist_df, fc_df, cp_df = _sample_business_tables()
    agent = FreeDataAIAgent(hist_df, fc_df, cp_df)

    monkeypatch.setattr(
        agent.provider,
        "retrieve_rag_chunks",
        lambda q, match_count=3: [
            {
                "titre": "Guide FEWS NET Commercialisation Céréales Tchad",
                "editeur": "FEWS NET",
                "page": 14,
                "url_source": "https://example.org/fews.pdf",
                "content": "Le stockage sur palettes réduit les pertes de grains sous 5 %.",
                "similarity": 0.89,
            }
        ],
    )

    # 1. Simulation de route P&L avec hypothèses par défaut
    res_route = agent.answer(
        "Quel profit net si j'achète du mil de Kélo à Abéché avec 500 000 FCFA ?",
        tier="free",
    )
    assert res_route["intent"] == "business_simulator"
    assert res_route["entities"]["origin_province"] == "Tandjile"
    assert res_route["entities"]["destination_province"] == "Ouaddai"
    reply_route = res_route["reply"]
    assert "Diagnostic de l'opération" in reply_route
    assert "Compte d'Exploitation Estimé" in reply_route
    assert "+190 890 XAF" in reply_route
    assert "289.5 XAF/kg" in reply_route
    assert "Hypothèse transport utilisée : 25 XAF/kg, pertes techniques estimées : 5 %" in reply_route
    assert "Références documentaires associées" in reply_route
    assert "FEWS NET" in reply_route
    for raw_col in ("predicted_price", "last_price", "commodity_std", "cv_pct", "score_global", "break_even_price_per_kg"):
        assert raw_col not in reply_route

    # 2. Destination manquante -> seuil plancher affiché honnêtement sans inventer de prix
    res_missing = agent.answer(
        "Combien je gagne si j'achète du niébé de Kélo vers Faya avec 500 000 FCFA ?",
        tier="free",
    )
    assert res_missing["intent"] == "business_simulator"
    assert "Pour ne pas perdre d'argent, vous devez revendre au minimum à 289.5 XAF/kg" in res_missing["reply"]

    # 3. Guide débutant avec capital
    res_guide = agent.answer(
        "Je veux débuter un business agricole avec un capital de 500 000 FCFA",
        tier="free",
    )
    assert res_guide["intent"] == "business_simulator"
    reply_guide = res_guide["reply"]
    assert "Diagnostic pour débuter" in reply_guide
    assert "Top 3 Filières « Tremplin »" in reply_guide
    assert "3 Pièges à éviter" in reply_guide
    assert "Checklist opérationnelle en 4 étapes" in reply_guide
    assert "Sorgho rouge" in reply_guide
    assert "Sésame" not in reply_guide  # filtré car 680 > 450 XAF/kg
    assert "Références documentaires associées" in reply_guide

    # 4. Vérifie que le point d'extension tier="premium" reste fonctionnel sans bloquer free
    monkeypatch.setattr(ai_agent, "settings", dataclasses.replace(ai_agent.settings, llm_api_key=""))
    res_prem_fallback = agent.answer(
        "Quel bénéfice pour le mil de Kélo à Abéché ?",
        tier="premium",
    )
    assert res_prem_fallback["intent"] == "business_simulator"
    assert "+190 890 XAF" in res_prem_fallback["reply"]

