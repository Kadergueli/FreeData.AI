-- Intelligence marché : vues publiques en lecture seule sur les données « trade » (licence CC BY 4.0).
-- À appliquer manuellement (Supabase SQL editor). Sans ces vues, l'API dégrade proprement :
-- les modules « contexte mondial » indiquent « données indisponibles » au lieu d'échouer.
-- Les vues n'exposent que des séries publiques agrégées (aucune donnée utilisateur).

CREATE OR REPLACE VIEW public.v_world_prices AS
SELECT
    date_reference AS month_date,
    indicateur     AS indicator,
    valeur         AS value,
    unite          AS unit,
    source_api     AS source,
    licence
FROM public.table_public
WHERE secteur = 'trade'
  AND source_api = 'World Bank Pink Sheet'
  AND valeur IS NOT NULL;

CREATE OR REPLACE VIEW public.v_macro_context AS
SELECT
    date_reference AS year_date,
    indicateur     AS indicator,
    valeur         AS value,
    unite          AS unit,
    source_api     AS source,
    licence
FROM public.table_public
WHERE secteur = 'trade'
  AND source_api = 'World Bank'
  AND valeur IS NOT NULL;

GRANT SELECT ON public.v_world_prices TO anon, authenticated;
GRANT SELECT ON public.v_macro_context TO anon, authenticated;
