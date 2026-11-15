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

Dans l'éditeur SQL, dans l'ordre :

| Situation | Fichiers |
|---|---|
| Installation neuve | `01_silver_v_clean_markets.sql`, `02_gold_ml_tables.sql`, `04_rls_policies.sql` |
| Base Gold déjà créée | `03_gold_alert_columns.sql` puis `04_rls_policies.sql` |

Ensuite, relancer `python scripts/update_predictions.py` pour remplir `predicted_price` et `deviation_pct` (sources des alertes). Tant que ce n'est pas fait, `/api/v1/health` indique `"alerts_source": "approximated"`.

## 2. Variables d'environnement

Voir `.env.example`. Points importants :

- `SUPABASE_KEY` : clé **publique** (anon) pour l'API. `SUPABASE_SERVICE_ROLE_KEY` : seulement pour le script mensuel.
- `ADMIN_TOKEN` : active `POST /api/v1/refresh` (en-tête `X-Admin-Token`). Sans valeur, l'endpoint est désactivé.
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

- Le score **Credit Passport** est un indicateur de volatilité des prix : ses poids et seuils ne sont pas calibrés sur des défauts de paiement. Il ne constitue pas une décision de crédit.
- Les observations marquées `is_flagged_outlier` ne sont pas exclues de l'entraînement ni du score.
- `hist_mae` et les intervalles à 80 % sont calculés sur les données d'entraînement (pas de validation hors échantillon).

## Études saisonnières avancées (offre premium)

- `GET /api/v1/studies/seasonality?commodity=Millet&province=Lac&storage_cost_pct_month=1.5&format=markdown`
  (en-tête `X-Premium-Key`) : calendrier achat/vente, indice mensuel, comparaison de provinces et stratégie
  « acheter au creux, vendre au pic » rejouée sur le passé (mois choisis sans regarder l'année évaluée).
- `PREMIUM_API_KEYS` (virgules, 16 caractères min.) : une fois défini, le tier `premium` du chat (LLM) exige aussi la clé.
- Production : `sql/05_gold_seasonality_studies.sql` puis `python -m scripts.update_seasonality --apply` (mensuel).
  Sans `--apply`, le script écrit un JSON local et n'envoie rien.
- **Tout contrôler en une commande (lecture seule) :** `python -m scripts.check_family_a` (ou `--csv ton_fichier.csv`) → dossier `reports/`.
- Évaluer seulement le modèle : `python -m scripts.run_backtest --csv données.csv`.
