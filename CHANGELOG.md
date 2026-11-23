# Changelog

## [Unreleased] — Audit écrans : sécurité et UI (2026-11-23)
- Partage de projet : l'API renvoie `name` (le titre était vide) ; ouvert dans un navigateur, le lien affiche une page de lecture seule statique, entièrement échappée (CSP `default-src 'none'`, `noindex`, `no-store`) au lieu de JSON brut.
- Chat : les images distantes du Markdown ne sont plus chargées (pistage / exfiltration par URL).
- Clé PRO : retirée de la barre d'adresse (`?key=`, `?premium_key=`) dès sa lecture.
- Agronome PRO : pH (3–10) et matière organique (0–40 %) validés dans l'interface avant l'envoi.

## [Unreleased] — Réparation de main (2026-11-22)
- Fix critique : `api/server.py` ne se chargeait plus (SyntaxError, bloc « share-link » inséré 35 fois dont au milieu de fonctions). Fichier reconstruit avec une seule copie des 3 ajouts (credit-passport depuis un audit agro, rapport de benchmark, liens de partage de projet).
- Sécurité : le secret des liens de partage n'a plus de valeur de repli publique ; sans `AUTH_SECRET` (16 car. min.), le partage répond 503.
- Moteur agro : les mesures labo aberrantes ou illisibles (pH 99, « abc », texture inconnue) sont écartées et ne débloquent plus le titre « PRÉ-ACHAT CERTIFIÉ ».
- Tests : liens de partage (aller-retour, falsification, expiration, secret absent), routes uniques.

## [Unreleased] — Correctifs audit frontend/backend (2026-11-22)
- Fix : `trigger_sqlite_backup` (NameError `Path`, route admin de sauvegarde en 500).
- Nettoyage : suppression du système de clés PRO mort (`create/list/revoke/redeem_pro_key`, double `_hash_activation_key`, double table `pro_activation_keys`) ; seul `*_activation_key` reste.
- Perf/confidentialité : cache 24 h des climatologies NASA POWER par cellule GPS arrondie (0,01°).
- Dépôt : `model_registry.db` et `experiments.db` retirés du suivi git (ignorés).

## [Unreleased] - Sol réel dans le moteur Agronome PRO
- `agro_site` : profil de sol (SoilGrids, CC BY 4.0) et de climat (NASA POWER) des 12 pôles, texture USDA calculée, matière organique estimée.
- Moteur d'analyse : sans mesures labo, le score pédologique utilise le sol réel de la zone (plafonné à 22/30, jamais assimilé à une mesure) ; avec mesures labo, elles prévalent et sont recoupées avec l'estimation zonale (`soil_cross_check`). Le titre « Diagnostic de terrain (pré-achat) » reste réservé aux mesures labo.
- Moteur d'aptitude FAO (trapèzes, calendrier de semis) prêt mais inactif : besoins EcoCrop non livrés (conditions FAO d'usage commercial à confirmer).

## [1.2.0] - 2026-11-18
### Added
- Persistent `StudyContext` (`src/study_context.py`) preserving instructions beyond 8 chat turns with contradiction detection.
- Modular Report Engine (`src/reports/orchestrator.py`, `engines.py`, `sections.py`, `qa_validator.py`, `jobs.py`) with vector cash-flow charts, FreeData.AI logo, dynamic traceability, and 6-dimension QA gate.
- Persistent Projects & Study Versions (`src/projects/store.py`, `sql/10_projects_and_study_versions.sql`, `ProjectsScreen`).
- Data Governance, Licensing Registry, Lineage & Privacy (`src/governance.py`, `src/ai_eval.py`).
- Advanced Analytics, ML Engine, Hybrid RAG & Orchestration (`src/analytics/`, `src/ml_engine.py`, `src/rag_engine.py`, `src/orchestrator_ml_rag.py`, `AnalyticsScreen`).
- Data Products Catalog & Python SDK (`src/data_products.py`, `src/api_keys.py`, `sdk/python/freedata_client.py`).
- Multi-Domain Platform & Monetization (`src/domains.py`, `src/entitlements.py`, `src/monetization.py`, `sql/11`, `SubscriptionScreen`, `SettingsScreen`).
- AI Infrastructure Router, TTL Caches & Provider Gateway (`src/ai_infra.py`).
- Security Hardening (`src/security.py`), Admin RBAC Console (`src/admin.py`, `sql/12`, `AdminScreen`), Online SQLite Backup (`src/backup.py`), and `render.yaml`.

