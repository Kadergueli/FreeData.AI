-- ============================================================================
-- FreeData.AI | Couche Silver : Vue de standardisation unifiée sur Supabase
-- Branchée directement sur public.table_public (données validées et publiées).
-- ============================================================================

CREATE OR REPLACE VIEW public.v_clean_markets
WITH (security_invoker = on)
AS
WITH base_markets AS (
    SELECT
        id,
        source_api AS source,
        indicateur AS indicator,
        region,
        DATE_TRUNC('month', date_reference)::date AS month_date,
        LOWER(TRIM(unite)) AS raw_unit,
        valeur AS raw_value,
        CASE WHEN COALESCE(notes_publiques, '') LIKE '%OUTLIER%' THEN 1 ELSE 0 END AS is_flagged_outlier,
        score_qualite,
        date_publication
    FROM public.table_public
    WHERE source_api IN ('WFP', 'FEWS NET')
      AND valeur IS NOT NULL
),
standardized AS (
    SELECT
        id,
        source,
        month_date,
        CASE 
            WHEN raw_unit = 'xaf/500_g' THEN raw_value * 2.0
            WHEN raw_unit = 'xaf/400_g' THEN raw_value * 2.5
            ELSE raw_value
        END AS price_value,
        CASE 
            WHEN raw_unit IN ('xaf/500_g', 'xaf/400_g') THEN 'xaf/kg'
            ELSE raw_unit
        END AS unit_clean,
        CASE 
            WHEN source = 'WFP' THEN SUBSTRING(region FROM '\(([^()]+)\)$')
            ELSE region
        END AS province,
        CASE 
            WHEN source = 'WFP' THEN REGEXP_REPLACE(region, '\s*\([^()]+\)$', '')
            ELSE COALESCE(NULLIF(SPLIT_PART(indicator, ' - ', 2), ''), region || ' (Agrégé)')
        END AS market_name,
        CASE 
            WHEN source = 'WFP' THEN 
                CASE 
                    WHEN REGEXP_REPLACE(indicator, '\s+retail price \(WFP\)$', '') = 'Sorghum' THEN 'Sorghum (red)'
                    ELSE REGEXP_REPLACE(indicator, '\s+retail price \(WFP\)$', '')
                END
            ELSE REGEXP_REPLACE(SPLIT_PART(indicator, ' - ', 1), '\s+price\s+\(retail\)$', '')
        END AS raw_commodity,
        is_flagged_outlier,
        score_qualite,
        date_publication
    FROM base_markets
)
SELECT
    id,
    source,
    month_date,
    price_value,
    unit_clean,
    province,
    market_name,
    -- Ne jamais rabattre les indicateurs FEWS NET "Maize (Corn)" et
    -- "Maize Grain (White)" sur une seule catégorie : leur équivalence physique
    -- n'est pas confirmée. Le libellé source est conservé ci-dessous.
    CASE raw_commodity
        WHEN 'Millet (Pearl)' THEN 'Millet'
        WHEN 'Sorghum (Red)' THEN 'Sorghum (red)'
        WHEN 'Rice (5% Broken)' THEN 'Rice (imported)'
        ELSE raw_commodity
    END AS commodity_std,
    is_flagged_outlier,
    score_qualite,
    date_publication,
    raw_commodity AS commodity_source_label
FROM standardized;