import numpy as np
import pandas as pd


def filter_fresh(df: pd.DataFrame, month_col: str, max_months: int) -> tuple[pd.DataFrame, int]:
    """Écarte les lignes dont le mois est trop en retard sur le mois le plus récent de `df`.

    - `month_col` contient des mois au format 'YYYY-MM' (str) ou des pandas.Period.
    - Retourne (dataframe filtré, nombre de lignes écartées).
    - `max_months <= 0` désactive le filtre.

    N'altère aucune valeur : seules des lignes sont retirées.
    """
    if df.empty or max_months is None or max_months <= 0:
        return df, 0
    months = pd.PeriodIndex(df[month_col].astype(str), freq="M")
    keep = np.asarray(months >= (months.max() - max_months))
    return df[keep].copy(), int((~keep).sum())
