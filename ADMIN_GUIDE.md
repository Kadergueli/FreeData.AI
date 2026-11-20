# FreeData.AI — Administrator Guide

## 1. Roles & Permissions (`src/admin.py`)
| Role | Permissions |
| :--- | :--- |
| `read_only_analyst` | `read_overview` (health, metrics, datasets, audit logs) |
| `support_admin` | `read_overview`, `manage_users` (suspend/reactivate), `manage_subscriptions` |
| `platform_admin` | `support_admin` + `manage_models`, `manage_data_governance`, `manage_system` |
| `super_admin` | All permissions including `manage_roles` and `delete_user_data` |

## 2. Security Rules
- All admin endpoints require `X-Admin-Token` (`ADMIN_TOKEN`) and fail closed (`503`) if `ADMIN_TOKEN` is unset.
- Support and admin views return user metadata, subscription status, and usage counts — **never** private conversations or uploaded document contents.
- Every administrative mutation is recorded in `admin_audit_logs` (`actor`, `actor_role`, `action`, `resource_type`, `resource_id`, `details`, `created_at`).


## Rôles attribués en console et révocation d'un jeton

Les jetons `ADMIN_TOKENS` fixent le rôle **maximal** d'une personne. Un `super_admin` peut en plus attribuer un rôle à l'acteur d'un jeton
(route d'attribution de rôle, `target_user_id` = nom de l'acteur) :

- un rôle **plus faible** que celui du jeton le restreint immédiatement (le rôle effectif est le plus restrictif des deux) ;
- le rôle **`user`** révoque le jeton (403 « Accès administrateur révoqué ») sans redéployer Render ;
- un rôle plus élevé en base **n'élève jamais** un jeton ; on ne peut pas modifier son propre rôle (anti-verrouillage).

`GET /api/v1/admin/me` renvoie le rôle effectif.

## Clés d'activation PRO

- Génération : écran Admin → « Générer une clé » (permission `manage_subscriptions`). La clé `FDPRO-XXXX-XXXX-XXXX-XXXX` n'est affichée **qu'une fois** ; seul son hash SHA-256 est stocké.
- Usage unique, liée au compte connecté qui l'active, valable 365 jours avant activation, plan `premium` uniquement (1 à 365 jours d'abonnement).
- Activer une 2ᵉ clé sur un abonnement actif cumule les durées.
- Révocation possible tant que la clé n'est pas utilisée. Toutes les actions sont inscrites au journal d'audit des abonnements.
- Protection : 5 tentatives invalides par compte et par 15 minutes, puis blocage temporaire.
