# Méthodologie FreeData.td — marchés, prix et prévisions

**Éditeur :** FreeData.td / FreeData.AI  
**Nature :** documentation méthodologique de première partie  
**Périmètre :** interprétation des prix agricoles et des prévisions de marché au Tchad.

## 1. Distinguer observation, estimation et prévision

- Un **prix observé** est une valeur rapportée par une source pour un marché, un produit, une unité et une période donnés.
- Une **prévision t+1** est une estimation pour la période suivante. Ce n'est pas un prix déjà constaté et elle ne garantit pas le prix auquel une transaction sera conclue.
- Une **valeur calculée** (écart, moyenne, conversion en sac ou en tonne) est dérivée d'entrées identifiées. Elle ne doit pas être présentée comme une observation indépendante.
- Une **hypothèse utilisateur** (transport, pertes, frais, prix cible) doit rester distinguée des données observées et des valeurs calculées.

Toute réponse doit préciser le produit, le marché ou la province, l'unité et la période. Une comparaison n'est valable que si les unités et les définitions sont compatibles.

## 2. Lire une prévision sans la surinterpréter

La prévision t+1 doit être lue avec son historique de validation et son niveau d'incertitude, lorsqu'ils sont disponibles.

- **MAE** : erreur absolue moyenne, exprimée dans l'unité du prix. Elle donne un ordre de grandeur de l'erreur typique en valeur absolue.
- **MAPE** : erreur absolue moyenne en pourcentage. Elle facilite la comparaison relative, mais devient instable lorsque les valeurs réelles sont nulles ou proches de zéro.
- **Intervalle de confiance ou de prévision à 80 %** : plage d'incertitude produite par le modèle selon sa méthode de calibration. Il ne signifie pas que le prix restera nécessairement dans cette plage.
- **CV (coefficient de variation)** : écart-type rapporté à la moyenne, exprimé en pourcentage. Il décrit la dispersion relative d'une série et ne prédit pas à lui seul la direction du prix.

Un modèle avec peu d'historique, une erreur élevée ou un intervalle large doit être présenté avec prudence. Si l'indicateur de validation est absent, il faut dire qu'il n'est pas disponible plutôt que de l'estimer.

## 3. Comparer deux marchés

Pour comparer deux lieux, vérifier :
1. même produit standardisé et qualité comparable ;
2. même unité (XAF/kg, sac de 100 kg ou tonne) ;
3. dates compatibles ;
4. statut de chaque valeur (observée ou prévue) ;
5. frais et contraintes logistiques non inclus dans le prix.

L'écart de prix brut est : **prix de vente de référence − prix d'achat de référence**. Cet écart n'est pas une marge nette : il ne tient pas compte du transport, des pertes, de la manutention, du stockage, des taxes ni des autres charges.

## 4. Fraîcheur et limites

La date du dernier relevé doit accompagner toute analyse de marché. Une série ancienne ne doit pas être décrite comme « actuelle ». Si les données sont vieillissantes ou périmées, l'assistant doit le signaler et éviter une recommandation d'achat ou de vente catégorique.

La couverture dépend des marchés, produits, sources et périodes effectivement suivis. Les données de marchés suivis ne constituent pas automatiquement un recensement exhaustif du marché national.

## 5. Règles de réponse de FreeData.AI

- Citer les sources documentaires récupérées et leurs pages lorsqu'elles sont disponibles.
- Séparer explicitement les observations, prévisions, calculs et hypothèses.
- Ne jamais fabriquer un prix, une date, une province, une précision statistique ou une source.
- Ne pas transformer une corrélation ou une anomalie en causalité.
- Si le corpus documentaire ne répond pas à la question, le dire. Les moteurs de données et de calcul peuvent néanmoins répondre à une demande quantitative lorsque leurs entrées sont disponibles.
