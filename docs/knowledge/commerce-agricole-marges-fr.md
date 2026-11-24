# Guide FreeData.td — calcul des marges du commerce agricole

**Éditeur :** FreeData.td / FreeData.AI  
**Nature :** guide méthodologique original ; ne constitue pas une cotation de marché ni un conseil financier personnalisé.

## 1. Les quatre niveaux à ne pas confondre

1. **Écart brut de prix** : prix de vente de référence moins prix d'achat de référence. Il ne déduit aucun coût opérationnel.
2. **Coût rendu unitaire** : prix d'achat augmenté des coûts unitaires explicitement pris en compte (transport, emballage, manutention ou autres frais configurés).
3. **Marge brute** : chiffre d'affaires diminué du coût des marchandises vendues ou du coût variable défini par le simulateur. La définition exacte utilisée doit être affichée.
4. **Résultat net estimé de l'opération** : recettes diminuées de l'ensemble des coûts inclus dans le scénario, y compris les charges opérationnelles et fixes déclarées. Il ne s'agit pas nécessairement du bénéfice comptable ou fiscal.

## 2. Formules de base

Pour un scénario de négoce :

- **Coût rendu par kg** = prix d'achat par kg + transport par kg + emballage et autres coûts unitaires retenus.
- **Volume commercialisable** = volume acheté × (1 − taux de pertes / 100).
- **Chiffre d'affaires estimé** = volume commercialisable × prix de vente retenu.
- **Marge unitaire indicative** = prix de vente × (1 − taux de pertes / 100) − coût rendu par kg.
- **Résultat opérationnel estimé** = chiffre d'affaires − coût d'achat − transport − emballage − autres charges incluses.
- **ROI** = résultat estimé / capital effectivement engagé × 100, lorsque le dénominateur est positif.
- **Seuil de rentabilité en prix** = coûts retenus / volume commercialisable. Le périmètre de coûts utilisé doit être précisé.

Ces formules sont des repères. Le résultat exact affiché par FreeData.AI dépend du moteur et des paramètres du scénario. Ne pas mélanger une formule simplifiée avec un résultat produit par un autre simulateur.

## 3. Données nécessaires pour une estimation crédible

À collecter ou à demander :
- produit, qualité et unité ;
- marché d'achat et marché de vente ;
- prix d'achat et prix de vente, en précisant s'ils sont observés, prévus ou saisis ;
- quantité ou tonnage ;
- transport total ou par kg ;
- emballage, manutention, chargement et déchargement ;
- pertes, avaries et déclassement ;
- frais de stockage et durée d'immobilisation ;
- taxes, droits, tickets de marché et autres frais locaux ;
- charges fixes et fréquence des cycles ;
- capital mobilisé et délai de paiement des acheteurs.

Une donnée non fournie ne doit pas être présentée comme un coût observé. Si le moteur utilise une valeur par défaut, l'assistant doit l'identifier comme hypothèse et proposer de la remplacer par un devis réel.

## 4. Interpréter un résultat négatif

Si les coûts dépassent les recettes, le scénario est déficitaire aux hypothèses retenues. L'assistant ne doit pas relever artificiellement le prix de vente pour rendre le scénario rentable. Il doit exposer :
- les postes qui pèsent sur le résultat ;
- le prix ou le volume de seuil calculé ;
- les paramètres qui changeraient le résultat ;
- les coûts qui restent inconnus ;
- la nécessité de vérifier les prix et le fret avant engagement.

Une marge positive ne garantit pas la liquidité : le stock peut rester invendu, le client peut payer tardivement et les frais imprévus peuvent absorber le bénéfice.

## 5. Sensibilité et risques

Comparer au minimum un scénario central et des scénarios défavorables lorsque le moteur les fournit. Faire varier uniquement des paramètres explicites : prix de vente, coût du transport, pertes, délai de stockage ou charges. Ne pas présenter un scénario de stress comme une prévision probabiliste si aucune probabilité n'a été calculée.

Avant expédition, confirmer le prix d'achat ferme, la disponibilité du produit, le devis de transport, les frais de marché, la capacité de stockage et la vitesse réelle d'écoulement.

## 6. Règles de réponse de l'assistant

- Le calcul chiffré vient du moteur déterministe, jamais d'une improvisation du modèle de langage.
- Le RAG explique les notions, les postes de coût, les hypothèses et les limites ; il ne remplace pas le calcul.
- Chaque chiffre doit être traçable à une donnée, une hypothèse utilisateur ou un calcul identifié.
- Si le marché de destination ou le prix de vente manque, demander la précision nécessaire ou étiqueter clairement tout scénario simulé.
- Distinguer marge brute, marge nette, résultat opérationnel, trésorerie et ROI.
