"""Motifs (regex) de détection d'intention et d'entités du chat."""
from __future__ import annotations

import re
from src.chat.lexicon import COMMODITY_ALIASES


# Mots ENTIERS uniquement (évite "cher" dans "recherche", "lac" dans "placer"...).
_GREETING_RE = re.compile(
    r"\b(salut|slt|bonjour|bjr|bonsoir|bsr|hello|hey|hi|coucou|cc|salam|salamou|assalam|ahlan|marhaba|"
    r"good\s+(?:morning|afternoon|evening)|bonne\s+(?:journee|soiree)|merci|aide|help)\b"
)
_SMALLTALK_HOW_RE = re.compile(
    r"\b(?:comment\s+(?:vas?[\s-]*tu|tu\s+vas|allez[\s-]*vous|vous\s+allez)|"
    r"ca\s+va|tu\s+vas\s+bien|vous\s+allez\s+bien|quoi\s+de\s+neuf)\b"
)
_SMALLTALK_IDENTITY_RE = re.compile(
    r"\b(?:qui\s+es[\s-]+tu|tu\s+es\s+qui|que\s+(?:fais|peux|sais)[\s-]+tu|"
    r"c\s*est\s+quoi\s+freedata|presente[\s-]+toi|tu\s+peux\s+m[\s']aider)\b"
)
_SMALLTALK_THANKS_RE = re.compile(
    r"\b(?:merci(?:\s+beaucoup)?|d[\s']accord|parfait|super|genial|top|au\s+revoir|a\s+bientot|bye|ok)\b"
)
_SMALLTALK_RE = re.compile(
    rf"(?:{_GREETING_RE.pattern}|{_SMALLTALK_HOW_RE.pattern}|{_SMALLTALK_IDENTITY_RE.pattern}|{_SMALLTALK_THANKS_RE.pattern})"
)
_OVERVIEW_RE = re.compile(
    r"\b(dataset|donnees|combien|marches|provinces|produits|sources|couverture)\b"
)
# "risque" seul est ambigu (risque de stocker, risque météo...) : il ne déclenche plus
# le Credit Passport sans un mot de financement.
_CREDIT_RE = re.compile(
    r"\b(credit|credits|pret|prets|preter|financer|financement|financements|"
    r"banque|banques|score|scores|passport|imf|microfinance|emprunt|emprunter)\b"
)
# "cher" seul est une question de prix, pas une alerte de tension.
_ALERT_RE = re.compile(
    r"\b(alerte|alertes|tension|tensions|surchauffe|anomalie|anomalies|flambee|hausse|hausses)\b"
)
# Recherche du meilleur endroit où acheter/vendre : comparaison de provinces.
_CHEAPEST_RE = re.compile(
    r"\b(?:moins\s+cher(?:e|s|es)?|meilleurs?\s+prix|bon\s+marche|pas\s+cher|"
    r"ou\s+(?:acheter|vendre)|plus\s+avantageu(?:x|se|ses))\b"
)
# "Quand acheter / vendre / stocker ?" : question de calendrier saisonnier (pas de prévision chiffrée du mois prochain).
_OPPORTUNITY_RE = re.compile(
    r"\b(business|investir|investissement|investissements|opportunite|opportunites|"
    r"rentable|rentables|rentabilite|marge|marges|commerce|commercant|commercants|"
    r"approvisionner|approvisionnement|revendre|revente|"
    r"meilleur marche|meilleurs marches|approprie|lancer|conseil|conseils)\b"
)
# "Entre vendre à A et à B, où aurais-je le plus de revenus ?" : comparer deux lieux de VENTE (pas un trajet A -> B).
_FOLLOW_UP_RE = re.compile(r"^\s*(?:et|et\s+si|pour|aussi|meme\s+chose|idem|pareil|et\s+pour|ca\s+marche\s+pour)\b")
_SELL_COMPARE_RE = re.compile(
    r"\b(?:vendre|vente|vendu|revenus?|gagner|rapporte|rapporter|plus\s+(?:cher|rentable|avantageux))\b"
)
_BUY_RESELL_RE = re.compile(r"\b(?:acheter|achat|achete|revendre|revente|depuis|vers|transporter|ramener|importer)\b")
_EITHER_RE = re.compile(r"\b(?:entre|ou|soit)\b")
_MARKET_CHOICE_OPPORTUNITY_RE = re.compile(
    r"\b(?:quel(?:s)?\s+marche(?:s)?|meilleur(?:s)?\s+marche(?:s)?|approprie|opportunite(?:s)?\s+(?:commerciales?|d[\s']?arbitrage)?)\b"
)
_BEGINNER_BUSINESS_RE = re.compile(
    r"\b(?:debuter|debutant|debutante|se\s+lancer|pour\s+commencer|comment\s+commencer|guide\s+debutant|"
    r"par\s+ou\s+(?:commencer|demarrer)|demarrer|demarrage|commencer\s+(?:un|une|dans|le|mon|ma|mes)\b)"
)
_PROFIT_SIM_RE = re.compile(
    r"\b(?:profit|profits|benefice|benefices|marge\s+nette|marges\s+nettes|"
    r"rentable|rentables|rentabilite|combien\s+je\s+gagne|combien\s+puis[\s-]+je\s+gagner|"
    r"seuil\s+de\s+rentabilite|compte\s+d[\s']?exploitation|simuler|simulation|"
    r"capital|budget)\b"
)
_BIZ_TRIGGER_RE = re.compile(
    r"\b(?:profit|profits|benefice|benefices|revenu|revenus|marge|marges|capital|budget|"
    r"debuter|debutant|se\s+lancer|lancer|business|rentable|rentables|rentabilite|"
    r"combien\s+je\s+gagne|investir)\b"
)
# "3 millions", "2,5 m" ...
_LOAN_MILLION_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:millions?|m)\b")
# Montant explicite avec une unité monétaire : "500 000 fcfa", "3.000.000 xaf", "800000 francs".
_LOAN_UNIT_RE = re.compile(r"(\d{1,3}(?:[ .]\d{3})+|\d+)\s*(?:xaf|fcfa|f\s?cfa|cfa|francs?)\b")
_VOL_TONNE_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(?:tonnes?|t(?=\s|$|[.,;!?]))\b")
_VOL_SAC_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*sacs?\b")
_VOL_KG_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(?:kg|kilos?|kilogrammes?)\b")
_TRANSPORT_KW_RE = re.compile(
    r"(?:transport|fret|acheminement|cout\s*(?:de\s*)?transport|frais\s*(?:de\s*)?(?:transport|route|logistique))"
    r"(?:\s*(?:est|de|a|:|=|estime\s*a))?\s*(\d+(?:[.,]\d+)?)"
    r"(?!\s*(?:tonnes?|sacs?|kg|kilos?|kilogrammes?|millions?)\b)"
    r"(?:\s*(?:xaf|fcfa|f\s?cfa|cfa|francs?))?(?:\s*(?:/|par)\s*kg)?"
)
_TRANSPORT_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:xaf|fcfa|f\s?cfa|cfa|francs?)\s*(?:/|par)\s*kg\b"
)
_CAPITAL_CTX_RE = re.compile(
    r"(?:capital|budget|investir|avec|enveloppe|mise|disponible|fonds?)\s*(?:de|d[' ]|est|:|=)?\s*"
    r"(\d{1,3}(?:[ .\u00a0\u202f]\d{3})+|\d+)(?!\s*(?:%|kg|kilos?|kilogrammes?|sacs?|tonnes?)\b)\b"
)
_NON_CAPITAL_FRAG_RE = re.compile(
    r"(?:\d+(?:[.,]\d+)?)\s*(?:tonnes?|sacs?|kg|kilos?|kilogrammes?|%|(?:xaf|fcfa|f\s?cfa|cfa|francs?)\s*(?:/|par)\s*kg)\b"
)
_ORIGIN_PREP_RE = re.compile(r"(?:^|\b)(?:depuis|venant\s+de|partir\s+de|de|du|d')\s*$")
_MIN_LOAN_XAF = 10_000  # même plancher que l'API (/credit-passport)
_DEFAULT_LOAN_XAF = 1_000_000
_DIGITS_RE = re.compile(r"\d+")
_LIST_PREFIX_RE = re.compile(r"(?m)^\s*(?:[-*]\s+|#{1,6}\s+)?(?:\*{1,2})?\d{1,2}[.)](?:\*{1,2})?\s+")
_THOUSAND_GROUP_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[, \u00a0\u202f]\d{3})+)(?!\d)")
# Petits nombres usuels de conversation (0 à 12) + facteurs de conversion standard (100 kg / 1 000 kg)
_IGNORED_CONVERSATION_NUMBERS = {str(i) for i in range(13)} | {"100", "1000"}

_COMMODITY_PATTERNS = [
    (re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"), comm_std)
    for alias, comm_std in sorted(COMMODITY_ALIASES.items(), key=lambda x: -len(x[0]))
]

# Produit nommé par l'utilisateur mais absent de nos données : on le dit, on ne répond pas avec un autre produit.
_UNKNOWN_CAND = (
    r"([a-z][a-z']*(?:\s+[a-z']+){0,2}?)"
    r"(?=\s+(?:a|au|aux|en|dans|pour|sur|entre|et|ou|par|chez|de|du|des|cette|ce|ces|vers|depuis|avec|svp|stp)\b|\s*[?.,;:!]|\s*$)"
)
# Les motifs sont en « lookahead » : ils se chevauchent (« évolution du prix du cacao » contient « prix du cacao »).
_UNKNOWN_PRODUCT_RES = [
    re.compile(rf"(?=\b(?:prix|cout|couts|tarifs?|cours|evolution|tendance|previsions?)\s+(?:du|de\s+la|de\s+l'|des|d')\s*{_UNKNOWN_CAND})"),
    re.compile(
        r"(?=\b(?:acheter|achat|vendre|vente|stocker|stockage|destocker|revendre|investir\s+dans|commercialiser|coute|coutent|vaut|valent)\s+"
        rf"(?:du|de\s+la|de\s+l'|des|d'|le|la|les|l'|un|une)\s*{_UNKNOWN_CAND})"
    ),
    re.compile(rf"(?=^\s*(?:et\s+)?(?:pour|avec|si\s+c'est)\s+(?:le|la|les|l'|du|des|de\s+la)\s*{_UNKNOWN_CAND})"),
]
# Mots qui suivent « prix du… » sans être un produit (« prix du marché », « prix du transport »…).
_NOT_A_PRODUCT = frozenset((
    "marche marches transport transports kilo kilos kg sac sacs tonne tonnes demain mois semaine semaines annee annees jour jours "
    "moment periode saison pays tchad produit produits cereale cereales ensemble tout tous toute toutes credit financement risque "
    "alerte alertes hausse baisse business commerce investissement capital budget region regions province provinces ville villes "
    "zone zones chose choses plus moins meilleur meilleure meilleurs bon bonne difference ecart ecarts revenu revenus benefice "
    "benefices profit marge marges base donnees donnee modele prevision previsions prix cout couts maintenant prochain prochaine "
    "dernier derniere ce cette ces mon ma mes notre nos votre vos ton ta tes son sa ses autre autres meme memes quel quelle quels "
    "quelles chaque aucun aucune plusieurs beaucoup peu rien quelque quelques depart arrivee trajet route routes camion voyage "
    "stock stocks recolte recoltes campagne simulation simulateur guide conseil conseils activite activites agriculture agricole"
).split())

_SECURITY_REFUSAL_REPLY = (
    "Je suis FreeData.AI, dédié exclusivement à l'analyse des marchés agricoles et économiques "
    "au Tchad sur la base de données vérifiées. Je ne peux pas donner suite à cette demande."
)

_FORECAST_HINT_RE = re.compile(
    r"\b(prix|prevision|previsions|prevoir|prediction|evolution|tendance|cout|couter|coute|kg|"
    r"tonne|tonnes|sac|sacs|monter|baisser|baisse|augmentation|augmenter|vendre|acheter|"
    r"marche|cereale|cereales|recolte|saison|simulateur|simuler|debutant|guide)\b"
)
_SECURITY_INJECTION_RE = re.compile(
    r"(?:"
    r"ignore\s+(?:tes|toutes?\s+les|all\s+previous|previous)(?:\s+instructions?)?"
    r"|oublie\s+(?:tes|toutes?\s+les|les)\s+regles?"
    r"|system\s+prompt|prompt\s+systeme"
    r"|\bjailbreak\b"
    r"|\bdan\b(?!\s+(?:le|la|les|l[' ]|un|une|mon|ma|ce|cette|quel|quelles?)\b)"
    r"|mode\s+developpeur"
    r"|(?:affiche|montre|donne|revele|print|show)\s+(?:ta|la|les?|votre)?\s*cles?"
    r"|\bsql\b|\bdrop\s+(?:table|database|schema)\b|\bselect\s+\*"
    r")"
)
