"""Lexique du chat : alias produits, villes/provinces, normalisation et formatage de nombres."""
from __future__ import annotations

from typing import Literal, Optional
import math
import pandas as pd
import unicodedata

COMMODITY_ALIASES = {
    "mil": "Millet",
    "millet": "Millet",
    "sorgho": "Sorghum (red)",
    "sorghos": "Sorghum (red)",
    "sorgho rouge": "Sorghum (red)",
    "sorghum": "Sorghum (red)",
    "sorghum (red)": "Sorghum (red)",
    "mais": "Maize (white)",
    "mais blanc": "Maize (white)",
    "maize": "Maize (white)",
    "maize (white)": "Maize (white)",
    "riz": "Rice (imported)",
    "rice": "Rice (imported)",
    "rice (imported)": "Rice (imported)",
    "riz importe": "Rice (imported)",
    "riz local": "Rice (local)",
    "rice (local)": "Rice (local)",
    "niebe": "Beans (niebe)",
    "haricot": "Beans (niebe)",
    "haricots": "Beans (niebe)",
    "beans (niebe)": "Beans (niebe)",
    "arachide": "Groundnuts (shelled)",
    "arachides": "Groundnuts (shelled)",
    "arachide decortiquee": "Groundnuts (shelled)",
    "arachides decortiquees": "Groundnuts (shelled)",
    "groundnuts (shelled)": "Groundnuts (shelled)",
    "sesame": "Sesame",
    "sucre": "Sugar",
    "sugar": "Sugar",
    "oignon": "Onions (red)",
    "oignons": "Onions (red)",
    "oignon rouge": "Onions (red)",
    "oignons rouges": "Onions (red)",
    "onions (red)": "Onions (red)",
    "pates": "Pasta",
    "pate": "Pasta",
    "pasta": "Pasta",
    "patate": "Sweet potatoes",
    "patates": "Sweet potatoes",
    "patate douce": "Sweet potatoes",
    "patates douces": "Sweet potatoes",
    "sweet potatoes": "Sweet potatoes",
    "poisson": "Fish (dry)",
    "poisson seche": "Fish (dry)",
    "fish (dry)": "Fish (dry)",
    # Produits suivis dans les données mais absents jusqu'ici : « prix du sel » renvoyait le mil par défaut.
    "sel": "Salt",
    "salt": "Salt",
    "ail": "Garlic",
    "garlic": "Garlic",
    "datte": "Dates",
    "dattes": "Dates",
    "dates": "Dates",
    "tomate sechee": "Tomatoes (dried)",
    "tomates sechees": "Tomatoes (dried)",
    "gombo": "Okra (dry)",
    "gombos": "Okra (dry)",
    "gombo sec": "Okra (dry)",
    "okra": "Okra (dry)",
    "farine": "Wheat flour",
    "farine de ble": "Wheat flour",
    "wheat flour": "Wheat flour",
    "huile": "Groundnut Oil (Refined)",
    "huile d'arachide": "Groundnut Oil (Refined)",
    "huile d\u2019arachide": "Groundnut Oil (Refined)",
    "huile d arachide": "Groundnut Oil (Refined)",
    "manioc": "Cassava (cossette)",
    "cossette": "Cassava (cossette)",
    "cossettes": "Cassava (cossette)",
    "cassava": "Cassava (cossette)",
    "niebe rouge": "Beans (niebe, red)",
    "haricot rouge": "Beans (niebe, red)",
    "sesame blanc": "Sesame (White)",
    "sucre raffine": "Refined sugar",
    "riz decortique": "Rice (Milled)",
    "riz usine": "Rice (Milled)",
    "macaroni": "Macaroni",
    "spaghetti": "Spaghetti",
    "spaghettis": "Spaghetti",
    "sorgho berbere": "Sorghum (Berbere)",
    "berbere": "Sorghum (Berbere)",
    "sorgho blanc": "Sorghum (White)",
    "cowpeas": "Cowpeas (Mixed)",
    "cowpea": "Cowpeas (Mixed)",
    "peanut": "Peanut",
    "niebe blanc": "Cowpeas (White)",
    "cowpeas (white)": "Cowpeas (White)",
    "cowpeas (red)": "Cowpeas (Red)",
    "cassava chips": "Cassava Chips",
    "manioc (cossettes)": "Cassava Chips",
    "pasta (mixed)": "Pasta (Mixed)",
    "pates alimentaires (melange)": "Pasta (Mixed)",
    "onions": "Onions",
}

COMMODITY_FR = {
    "Millet": "Mil",
    "Sorghum (red)": "Sorgho rouge",
    "Maize (white)": "Maïs blanc",
    "Rice (local)": "Riz local",
    "Rice (imported)": "Riz importé",
    "Groundnuts (shelled)": "Arachide décortiquée",
    "Beans (niebe)": "Niébé (haricot)",
    "Onions (red)": "Oignon rouge",
    "Sesame": "Sésame",
    "Sugar": "Sucre",
    "Pasta": "Pâtes alimentaires",
    "Sweet potatoes": "Patate douce",
    "Fish (dry)": "Poisson séché",
    "Salt": "Sel",
    "Garlic": "Ail",
    "Dates": "Dattes",
    "Tomatoes (dried)": "Tomates séchées",
    "Okra (dry)": "Gombo sec",
    "Wheat flour": "Farine de blé",
    "Groundnut Oil (Refined)": "Huile d'arachide raffinée",
    "Cassava (cossette)": "Manioc (cossettes)",
    "Beans (niebe, red)": "Niébé rouge",
    "Sesame (White)": "Sésame blanc",
    "Refined sugar": "Sucre raffiné",
    "Rice (Milled)": "Riz décortiqué",
    "Sorghum (Berbere)": "Sorgho berbéré",
    "Sorghum (White)": "Sorgho blanc",
    "Cowpeas (Mixed)": "Niébé (mélange)",
    "Cassava Chips": "Manioc (cossettes)",
    "Cowpeas (Red)": "Niébé rouge",
    "Cowpeas (White)": "Niébé blanc",
    "Onions": "Oignon",
    "Pasta (Mixed)": "Pâtes alimentaires (mélange)",
    "Macaroni": "Macaroni",
    "Peanut": "Arachide",
    "Spaghetti": "Spaghetti",
    "Wheat": "Blé",
}

CITY_TO_PROVINCE = {
    "kelo": "Tandjile",
    "kélo": "Tandjile",
    "lai": "Tandjile",
    "laï": "Tandjile",
    "bere": "Tandjile",
    "béré": "Tandjile",
    "abeche": "Ouaddai",
    "abéché": "Ouaddai",
    "abe": "Ouaddai",
    "moundou": "Logone Occidental",
    "doba": "Logone Oriental",
    "gore": "Logone Oriental",
    "goré": "Logone Oriental",
    "bebedjia": "Logone Oriental",
    "sarh": "Moyen-Chari",
    "kyabe": "Moyen-Chari",
    "kyabé": "Moyen-Chari",
    "mongo": "Guera",
    "bitkine": "Guera",
    "melfi": "Guera",
    "am timan": "Salamat",
    "amtiman": "Salamat",
    "haraze": "Salamat",
    "bongor": "Mayo-Kebbi Est",
    "fianga": "Mayo-Kebbi Est",
    "pala": "Mayo-Kebbi Ouest",
    "lere": "Mayo-Kebbi Ouest",
    "léré": "Mayo-Kebbi Ouest",
    "bol": "Lac",
    "bagasola": "Lac",
    "mao": "Kanem",
    "nokou": "Kanem",
    "ati": "Batha",
    "oumm hadjer": "Batha",
    "biltine": "Wadi Fira",
    "guereda": "Wadi Fira",
    "faya": "Borkou",
    "faya-largeau": "Borkou",
    "faya largeau": "Borkou",
    "fada": "Ennedi Ouest",
    "amdjarass": "Ennedi Est",
    "am-djarass": "Ennedi Est",
    "am djarass": "Ennedi Est",
    "massakory": "Hadjer-Lamis",
    "bokoro": "Hadjer-Lamis",
    "moussoro": "Barh El Gazel",
    "massenya": "Chari-Baguirmi",
    "bousso": "Chari-Baguirmi",
    "bardai": "Tibesti",
    "bardaï": "Tibesti",
    "zouar": "Tibesti",
    "ndjamena": "N'Djamena",
    "n'djamena": "N'Djamena",
    "n djamena": "N'Djamena",
    "ndj": "N'Djamena",
}


def fr_commodity(commodity_std: str) -> str:
    """Nom français d'un produit (le nom d'origine si inconnu)."""
    return COMMODITY_FR.get(commodity_std, commodity_std)


def _normalize_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _clean_float(val: object) -> Optional[float]:
    if val is None or pd.isna(val):
        return None
    f = float(val)
    return f if math.isfinite(f) else None


def _clean_int(val: object) -> Optional[int]:
    f = _clean_float(val)
    return int(round(f)) if f is not None else None


def _fmt_int(val: Optional[float]) -> str:
    """Formate un entier avec séparateur de milliers français (espace)."""
    if val is None or not math.isfinite(float(val)):
        return "n/d"
    return f"{int(round(float(val))):,}".replace(",", " ")


def _fmt_signed_int(val: Optional[float]) -> str:
    """Formate un entier signé avec séparateur de milliers français."""
    if val is None or not math.isfinite(float(val)):
        return "n/d"
    num = int(round(float(val)))
    if num > 0:
        return f"+{num:,}".replace(",", " ")
    if num < 0:
        return f"-{abs(num):,}".replace(",", " ")
    return "0"


def _fmt_pct(val: Optional[float], signed: bool = True) -> str:
    """Formate un pourcentage lisible à 1 décimale."""
    if val is None or not math.isfinite(float(val)):
        return "n/d"
    num = float(val)
    if signed:
        sign = "+" if num > 0 else ("-" if num < 0 else "")
        return f"{sign}{abs(num):.1f}%"
    return f"{num:.1f}%"


def _fmt_num(val: Optional[float]) -> str:
    """Formate un montant/prix (entier si exact, sinon 1 décimale) avec séparateur d'espace."""
    if val is None or not math.isfinite(float(val)):
        return "n/d"
    num = round(float(val), 1)
    if abs(num - round(num)) < 0.05:
        return _fmt_int(round(num))
    whole = int(num) if num >= 0 else -int(abs(num))
    frac = int(round(abs(num - whole) * 10))
    return f"{_fmt_int(whole)}.{frac}"


_CITY_CANONICAL_HINTS = {
    "abe": "abeche",
    "ndj": "djamena",
    "ndjamena": "djamena",
    "n'djamena": "djamena",
    "n djamena": "djamena",
    "faya-largeau": "faya",
}
