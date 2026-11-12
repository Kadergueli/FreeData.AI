# FreeData.AI — Agent IA, Prévisions Agricoles & Credit Passport (Tchad)

Application décisionnelle découplée de **FreeData.td**, connectée à **Supabase (PostgreSQL)** via **FastAPI** et servie en Web/Mobile par **Flutter (Firebase Hosting)**.

## 1. Démarrage Backend Python (FastAPI)
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn api.server:app --reload --port 8000
```
Documentation interactive Swagger disponible sur `http://127.0.0.1:8000/docs`.

## 2. Démarrage & Déploiement Frontend Flutter (Firebase Hosting)
```bash
cd frontend_flutter
flutter pub get
flutter run -d chrome
# Build & déploiement Firebase Hosting :
flutter build web --dart-define=API_BASE_URL=https://votre-api.onrender.com
firebase deploy --only hosting
```
