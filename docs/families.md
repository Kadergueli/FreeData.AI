# Architecture : les familles d'analyses

```
src/
  ai_agent.py          cœur du chat : fournisseur de données, routage, agent
  chat/
    lexicon.py         alias produits, villes/provinces, normalisation, formatage de nombres
    patterns.py        regex de détection (salutations, crédit, alertes, volumes...)
    formatters.py      mise en forme Markdown des réponses (FormattersMixin)
  families/
    base.py            contrat FamilySpec
    registry.py        register / by_intent / detect
    seasonality.py     famille A : calendrier saisonnier (chat)
  seasonality.py, season_study.py, backtest.py   calculs hors ligne de la famille A
scripts/               jobs hors ligne (update_predictions, update_seasonality, ...)
sql/                   tables Gold numérotées
```

## Ajouter une famille (ex. B : anomalies)

1. **Calcul hors ligne** : un module `src/<nom>.py` (fonctions pures sur DataFrame, testables).
2. **Stockage** : un fichier `sql/NN_gold_<nom>.sql` (lecture publique ou non, voir la politique d'accès) et un script `scripts/update_<nom>.py`.
3. **Chat** : `src/families/<nom>.py` expose un `FamilySpec` :
   - `pattern` (texte normalisé) et `intent` ;
   - `run(agent, entities) -> (faits Markdown, données brutes)` ;
   - `intro(entities, what, where)` ;
   - `clarify(agent, entities, has_history)` (optionnel) pour demander un produit manquant ;
   - `gold_tables` et `offline_script` (documentation).
4. **Enregistrement** : une ligne `register(...)` dans `src/families/__init__.py`.
5. **Tests** : calcul pur, formatage, et un test de routage dans le chat (voir `tests/test_families.py`).

Le routeur LLM, l'introduction des réponses, la détection d'intention et les demandes de précision lisent le
registre : aucune modification du cœur n'est nécessaire.

## Règles à respecter
- Une famille n'invente jamais de chiffres : tout nombre vient des données ou d'un calcul traçable.
- Si l'historique est insuffisant, elle le dit plutôt que de répondre.
- Les réponses par défaut (question vague) se calculent sur les données suivies, jamais sur un produit imposé.
