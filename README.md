# FreeData.AI — Agent IA, Prévisions Agricoles & Credit Passport (Tchad)

Application décisionnelle découplée de **FreeData.td**, connectée à **Supabase (PostgreSQL)** via **FastAPI** et servie en Web/Mobile par **Flutter (Firebase Hosting)**.

## Architecture

```
FreeData.td (collecte) -> public.table_public
        -> sql/01  vue Silver  v_clean_markets (unités homogènes XAF/kg)
        -> scripts/update_predictions.py (mensuel) : exécute le modèle
        -> sql/02-04  tables Gold  table_ml_forecasts / table_ml_credit_passport
        -> API FastAPI (lecture seule des tables Gold) -> Flutter
```

- **Modèle** : `src/forecasting.py` (prévision t+1) et `src/credit_passport.py` (score 0-100). Ils sont exécutés par `scripts/update_predictions.py`, qui publie leurs sorties dans les tables Gold.
- **En production (`SUPABASE_URL` + `SUPABASE_KEY`)** l'API ne recalcule rien : elle sert les sorties déjà publiées. Le recalcul complet n'existe qu'en mode local (CSV / PostgreSQL).
- **Agent** (`src/ai_agent.py`) : extraction d'entités par règles, puis outils déterministes qui lisent les tables. Un LLM local (Ollama) peut reformuler, mais sa réponse est rejetée si elle cite un nombre absent des faits du moteur.

## 1. Installation base de données (Supabase)

Dans l'éditeur SQL, exécuter les scripts dans l'ordre exact pour une installation neuve :

1. `sql/01_silver_v_clean_markets.sql` (vue Silver `v_clean_markets`)
2. `sql/02_gold_ml_tables.sql` (`table_ml_forecasts`, `table_ml_credit_passport`)
3. `sql/03_gold_alert_columns.sql` (`predicted_price`, `deviation_pct`)
4. `sql/04_rls_policies.sql` (RLS lecture publique sur prévisions & indice de stabilité)
5. `sql/05_gold_seasonality_studies.sql` (`table_ml_seasonality_studies`)
6. `sql/06_gold_forecast_quality.sql` (`forecast_quality`)
7. `sql/07_gold_anomalies.sql` (`table_ml_anomalies`)
8. `sql/08_harden_grants.sql` *(optionnel — vérifier d'abord qu'aucune app tierce n'écrit en `anon`/`authenticated`)*
9. `sql/09_lock_premium_tables_rls.sql` *(retire la lecture directe `anon`/`authenticated` sur les tables PRO ; requiert `SUPABASE_SERVICE_ROLE_KEY` sur l'API)*
10. `sql/10_projects_and_study_versions.sql` *(projets persistants, StudyContext, conversations, versions d'études & RLS)*

## Documentation & Base de Connaissances

- [ARCHITECTURE.md](ARCHITECTURE.md) — Architecture système, diagrammes et flux de données
- [DATA_CATALOG.md](DATA_CATALOG.md) — Catalogue des jeux de données sources, Silver et Gold
- [METHODOLOGY.md](METHODOLOGY.md) — Méthodologie statistique, formules financières et scoring QA
- [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md) — Gouvernance des données, qualité et usage responsable
- [USER_GUIDE.md](USER_GUIDE.md) — Guide utilisateur pas-à-pas
- [API.md](API.md) — Référence complète des endpoints REST
- [SECURITY.md](SECURITY.md) — Authentification, isolation par utilisateur et RLS
- [DEPLOYMENT.md](DEPLOYMENT.md) — Déploiement Render, Firebase Hosting, sauvegardes et rollback

Ensuite, lancer le pipeline de publication : `python -m scripts.publish_pipeline` (ou `python scripts/update_predictions.py`). Tant que `predicted_price` / `deviation_pct` ne sont pas remplis, `/api/v1/health` indique `"alerts_source": "approximated"`.

## 2. Variables d'environnement

Voir `.env.example`. Points importants :

- `SUPABASE_KEY` : clé **publique** (anon) pour l'API. `SUPABASE_SERVICE_ROLE_KEY` : seulement pour le script mensuel.
- `ADMIN_TOKENS` : jetons admin par personne `acteur:rôle:jeton` séparés par `;` (rôles `read_only_analyst`, `support_admin`, `platform_admin`, `super_admin`). Le rôle et l'acteur journalisé sont déduits du jeton ; `X-Admin-Role`/`X-Admin-Actor` sont ignorés.
- `ADMIN_TOKEN` (hérité, équivaut à `root_admin` / `super_admin`) : active `POST /api/v1/refresh` (en-tête `X-Admin-Token`). Sans valeur, l'endpoint est désactivé.
- `MAX_STALENESS_MONTHS` : fraîcheur maximale des séries servies (défaut 3).

## 3. Démarrage Backend Python (FastAPI)
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows ; Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.server:app --reload --port 8000
```
Documentation interactive Swagger : `http://127.0.0.1:8000/docs`.

Tests :
```bash
pip install -r requirements-dev.txt
pytest
```

## 4. Démarrage & Déploiement Frontend Flutter (Firebase Hosting)
```bash
cd frontend_flutter
flutter pub get
flutter run -d chrome
# Build & déploiement Firebase Hosting :
flutter build web --dart-define=API_BASE_URL=https://votre-api.onrender.com
firebase deploy --only hosting
```

## Limites connues

- L'indice **Agricultural Market Risk & Stability Index** (champ `credit_score` / `market_stability_index`) mesure uniquement la stabilité des prix de marché : ses poids et seuils ne sont **pas** calibrés sur des défauts de remboursement d'emprunteurs et ne constituent pas une décision de crédit bancaire.
- Les intervalles à 80 % (`ci_low_80`, `ci_high_80`) utilisent une calibration conforme hors-échantillon (split chronologique 70/30) avec statut explicite (`interval_status` : `calibrated_80`, `wide_reduced` ou `insufficient_history`), mesurée à **78,9 %** globalement sur `freedatatd-markets-full.csv` (13 360 comparaisons *rolling-origin*), avec une sous-couverture résiduelle sur les séries très instables (`Fish (dry)` : 49,4 %).
- La Bibliothèque Flutter stocke les conversations **localement** (`SharedPreferences`) : aucune synchronisation cloud multi-appareils ni mode hors-ligne complet pour les données API n'est actif.

## Études saisonnières avancées (offre premium)

- `GET /api/v1/studies/seasonality?commodity=Millet&province=Lac&storage_cost_pct_month=1.5&format=markdown`
  (en-tête `X-Premium-Key`) : calendrier achat/vente, indice mensuel, comparaison de provinces et stratégie
  « acheter au creux, vendre au pic » rejouée sur le passé (mois choisis sans regarder l'année évaluée).
- `PREMIUM_API_KEYS` (virgules, 16 caractères min.) : une fois défini, le tier `premium` du chat (LLM) exige aussi la clé.
- Production : `sql/05_gold_seasonality_studies.sql` puis `python -m scripts.update_seasonality --apply` (mensuel).
  Sans `--apply`, le script écrit un JSON local et n'envoie rien.
- **Tout contrôler en une commande (lecture seule) :** `python -m scripts.check_family_a` (ou `--csv ton_fichier.csv`) → dossier `reports/`.
- Évaluer seulement le modèle : `python -m scripts.run_backtest --csv données.csv`.

- Le même traitement mensuel publie aussi un **bilan de fiabilité par produit** (`kind='track_record'`) : le chat indique si, sur
  12 mois, les prévisions du produit ont été plus justes, équivalentes ou moins justes que « le prix reste celui du mois dernier ».
- Les noms de produit qui ne diffèrent que par la casse (« Wheat Flour » / « Wheat flour ») sont fusionnés au chargement.

## Anomalies de prix (famille B)

Détection de sauts de prix, de marchés qui divergent de leurs pairs et de séries figées ou arrêtées (`src/anomalies.py`).
Ce sont des **signaux à vérifier**, jamais un verdict : l'historique réel est court.

```bash
python -m scripts.check_family_b --csv freedatatd-markets-full.csv   # contrôle en lecture seule (chocs injectés)
# appliquer sql/07_gold_anomalies.sql dans Supabase, puis :
python -m scripts.update_anomalies --apply                           # publie les 6 derniers mois
```

Lecture (offre PRO, en-tête `X-Premium-Key` requis) : `GET /api/v1/anomalies?province=&commodity=&kind=&severity=` et dans le chat (« anomalies de prix du mil »).
Architecture des familles : `docs/families.md`.

## Sécurité de l'API

- **Limites de requêtes** par IP et par catégorie (chat 20/min, données 120/min, administration 10/min) et un plafond **global** non falsifiable (`GLOBAL_RATE_LIMIT_PER_MIN`). Sans `TRUSTED_PROXY_HOPS` (ou si le `peer` est hors `TRUSTED_PROXY_CIDRS`), l'API se replie sur l'IP directe (`peer`) et ignore `X-Forwarded-For`. En multi-instances, configurer `UPSTASH_REDIS_REST_URL` et `UPSTASH_REDIS_REST_TOKEN` (repli automatique sur la mémoire locale si indisponible).
- **Premium** : uniquement les clés de `PREMIUM_API_KEYS`. Sans clé valide, `/api/v1/anomalies` et `/api/v1/studies/seasonality` renvoient `403` (ou `503` si non configuré), et le chat reste au niveau gratuit. Le jeton `ADMIN_TOKEN` ne sert qu'à `/api/v1/refresh` et `/api/v1/diag/client-ip`.
- **Chat** : au plus `CHAT_MAX_CONCURRENCY` appels simultanés, sinon 503 (`Retry-After`).
- **Intégration continue & Publication** : `.github/workflows/ci.yml` exécute `python` (`pytest` + `pip-audit`), `flutter` (`format`, `analyze`, `test`, `build web`) et `integration` (`tests/test_api_contracts.py`). `.github/workflows/publish_pipeline.yml` orchestre `scripts/publish_pipeline.py` (12 étapes).
- Durcissement des droits Supabase : `sql/08_harden_grants.sql` et `sql/09_lock_premium_tables_rls.sql` (à lire avant d'appliquer).
