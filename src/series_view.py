import pandas as pd


def months_behind(month: str, latest: str) -> int:
    """Nombre de mois d'écart entre `month` et `latest` (formats 'YYYY-MM')."""
    return (pd.Period(latest, freq="M") - pd.Period(month, freq="M")).n


def _close(row, ref, rel_tol: float) -> bool:
    return (
        abs(row["value"] - ref["value"]) <= rel_tol * abs(ref["value"])
        and abs(row["forecast_t1"] - ref["forecast_t1"]) <= rel_tol * abs(ref["forecast_t1"])
    )


def collapse_near_identical(df: pd.DataFrame, rel_tol: float = 0.001) -> list[list]:
    """Regroupe les séries quasi identiques, SANS en supprimer aucune.

    Deux séries vont dans le même groupe si elles ont la même source et le même dernier mois
    observé, et si leur dernier prix ET leur prévision t+1 diffèrent de moins de `rel_tol`
    (0,1 % par défaut). Retourne une liste de groupes ; chaque groupe est une liste de lignes.
    Seul l'affichage change : toutes les données restent dans les tables.
    """
    groups: list[list] = []
    for _, part in df.groupby(["source", "last_observed_month"], sort=False):
        current: list = []
        for _, row in part.sort_values("value").iterrows():
            if current and _close(row, current[0], rel_tol):
                current.append(row)
            else:
                if current:
                    groups.append(current)
                current = [row]
        if current:
            groups.append(current)
    return groups
