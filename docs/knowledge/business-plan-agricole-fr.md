# Méthodologie FreeData.td — business plan agricole et financement

**Éditeur :** FreeData.td / FreeData.AI  
**Nature :** cadre méthodologique de préfaisabilité ; ne constitue ni une offre de crédit ni une garantie de financement.

## 1. Objectif d'un business plan

Un business plan agricole ou de négoce doit relier le marché, l'opération, les besoins de financement, les flux de trésorerie et les risques. Il doit permettre au lecteur de distinguer les données vérifiées, les hypothèses du porteur de projet et les résultats calculés.

**Limite de périmètre :** le moteur déterministe `build_professional_business_plan` décrit ici couvre principalement le négoce (achat, transport et revente de produits agricoles). Il ne constitue pas, à lui seul, un modèle complet de production à la ferme : budget cultural, itinéraire technique, rendement parcellaire, main-d'œuvre, intrants et calendrier de récolte nécessitent des données et un moteur de production dédiés. Si la demande concerne la production agricole, l'assistant ne doit pas présenter le simulateur de négoce comme un business plan de ferme.

Un document utile comprend généralement :
- résumé du projet et objectif commercial ;
- produit, qualité, zone d'approvisionnement et débouchés ;
- analyse du marché et sources de prix ;
- organisation opérationnelle, stockage et transport ;
- investissements (CAPEX) et besoins de fonds de roulement (BFR) ;
- hypothèses de coûts, pertes, prix et volumes ;
- compte d'exploitation prévisionnel et trésorerie ;
- seuil de rentabilité et scénarios de stress ;
- risques, mesures d'atténuation et plan de validation terrain.

## 2. Allocation de capital utilisée par le modèle FreeData.AI

Le modèle de négoce documenté applique par défaut :
- **80 %** au BFR opérationnel ;
- **8 %** aux équipements (CAPEX) ;
- **12 %** à une réserve de trésorerie de sécurité.

Lorsque le porteur de projet demande explicitement de fonctionner sans équipement (CAPEX = 0), la part équipement est transférée au BFR : **88 % BFR / 0 % CAPEX / 12 % réserve**.

Cette allocation est une convention de scénario du modèle, pas une norme bancaire universelle. Elle doit être adaptée au projet et aux besoins réels. Le BFR sert notamment à financer le stock et les dépenses opérationnelles du cycle ; la réserve ne doit pas être comptée une seconde fois comme budget d'achat.

## 3. Projection et réinvestissement

Le modèle professionnel peut projeter six mois et appliquer par défaut un réinvestissement de **75 % du résultat net positif** dans le BFR. Si l'utilisateur demande « sans réinvestissement » ou « BFR constant », cette règle doit être désactivée et le fonds de roulement doit rester constant selon le scénario.

La projection est conditionnelle aux hypothèses saisies. Elle ne représente pas une garantie de ventes, de recouvrement ou de trésorerie réelle. Un business plan doit expliciter les délais de paiement, la rotation des stocks, la saisonnalité et les éventuels besoins supplémentaires de liquidité lorsqu'ils sont connus.

## 4. Prix, rentabilité et point mort

Le prix de vente doit provenir d'un relevé observé, d'une prévision identifiée ou d'une hypothèse explicitement étiquetée. Une prévision t+1 ne doit pas être présentée comme une transaction garantie.

Le point mort est calculé à partir du périmètre de coûts et du volume commercialisable du scénario. Si le prix de marché disponible est inférieur au prix de seuil, le projet doit être déclaré non rentable aux hypothèses retenues. Ne jamais augmenter artificiellement le prix de vente pour faire apparaître un bénéfice.

Le modèle peut inclure un plafond de prix d'achat compatible avec une marge cible, des scénarios de stress, un ROI et un besoin de capital. Ces indicateurs doivent être présentés avec leur formule ou leur définition et leurs limites.

## 5. Risques à documenter

Selon le projet, examiner :
- risque de prix et volatilité ;
- risque de disponibilité et de qualité du stock ;
- pertes post-récolte et déclassement ;
- transport, état des axes, péages et frais locaux ;
- stockage, sécurité et durée d'immobilisation ;
- concentration des acheteurs et délais de paiement ;
- risque climatique et saisonnier ;
- risque de financement et de remboursement.

Une donnée indisponible doit rester « non renseignée ». Ne pas inventer une étude de clientèle, une part de marché, des devis, des contrats, des taux d'intérêt ou des probabilités de défaut.

## 6. Plan de validation terrain

Avant de solliciter un financement ou d'engager du capital, vérifier :
1. un prix d'achat ferme auprès de fournisseurs identifiés ;
2. un prix de vente et une demande confirmés auprès d'acheteurs réels ;
3. un devis de transport incluant carburant, péages et manutention ;
4. les frais de marché, taxes et tickets applicables ;
5. le coût de magasinage, la sécurité, les pertes et la vitesse d'écoulement.

Les éléments non confirmés doivent apparaître dans le plan comme conditions préalables, et non comme faits acquis.

## 7. Limites et responsabilité

Un business plan généré est une étude de préfaisabilité basée sur les données disponibles et les hypothèses déclarées. Il ne remplace pas une comptabilité, une étude de terrain, un audit, une validation juridique ou une décision d'un établissement financier. Un score ou ratio calculé par FreeData.AI ne constitue pas une décision de crédit.
