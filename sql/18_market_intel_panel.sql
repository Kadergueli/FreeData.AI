-- Intelligence marché : panneau de prix PRÉ-AGRÉGÉ (une ligne par produit x marché, séries mensuelles en tableaux).
-- Remplace la lecture des ~50 000 relevés bruts par l'API : ~700 lignes, une seule requête, quelques Ko de mémoire.
-- À appliquer manuellement (SQL Editor Supabase), puis à rafraîchir après chaque mise à jour mensuelle des données :
--     REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_market_panel;
-- Données publiques agrégées (prix de détail WFP / FEWS NET), aucune donnée utilisateur.

DROP MATERIALIZED VIEW IF EXISTS public.mv_market_panel;

CREATE MATERIALIZED VIEW public.mv_market_panel AS
WITH monthly AS (
    SELECT lower(commodity_std)           AS commodity,
           COALESCE(province, '')         AS province,
           COALESCE(market_name, '')      AS market_name,
           month_date,
           avg(price_value)               AS price   -- WFP et FEWS NET se recoupent : moyenne par mois
    FROM public.v_clean_markets
    WHERE unit_clean = 'xaf/kg'
      AND is_flagged_outlier = 0
      AND price_value > 0
      AND lower(commodity_std) IN (
          'millet', 'sorghum (red)', 'maize (white)', 'groundnuts (shelled)', 'rice (local)',
          'rice (imported)', 'sesame', 'beans (niebe)', 'onions (red)', 'sugar', 'wheat flour')
    GROUP BY 1, 2, 3, 4
)
SELECT commodity,
       province,
       market_name,
       array_agg(month_date ORDER BY month_date)                  AS months,
       array_agg(round(price::numeric, 2)::float8 ORDER BY month_date) AS prices
FROM monthly
GROUP BY commodity, province, market_name;

CREATE UNIQUE INDEX mv_market_panel_key ON public.mv_market_panel (commodity, province, market_name);

GRANT SELECT ON public.mv_market_panel TO anon, authenticated;
