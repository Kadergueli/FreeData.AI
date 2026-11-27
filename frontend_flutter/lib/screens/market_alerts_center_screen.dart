import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';

/// Vue transversale des trois mécanismes de surveillance existants.
/// Les règles et leurs sources restent indépendantes : cet écran ne fait que
/// les présenter ensemble et déléguer les actions aux API déjà en place.
class MarketAlertsCenterScreen extends StatefulWidget {
  final ApiService apiService;

  const MarketAlertsCenterScreen({super.key, required this.apiService});

  @override
  State<MarketAlertsCenterScreen> createState() =>
      _MarketAlertsCenterScreenState();
}

class _MarketAlertsCenterScreenState extends State<MarketAlertsCenterScreen> {
  bool _loading = true;
  bool _refreshing = false;
  List<dynamic> _observedAlerts = const [];
  List<dynamic> _customRules = const [];
  List<dynamic> _forecastWatchlists = const [];
  String? _observedError;
  String? _customError;
  String? _watchlistError;
  final Set<String> _pendingActions = {};

  bool get _isPro => widget.apiService.hasPremiumKey;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<Map<String, dynamic>> _safe(
    Future<dynamic> Function() request,
  ) async {
    try {
      return {'data': await request()};
    } catch (error) {
      return {'error': error.toString()};
    }
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() {
      _loading = _observedAlerts.isEmpty &&
          _customRules.isEmpty &&
          _forecastWatchlists.isEmpty;
      _refreshing = true;
    });

    final futures = <Future<Map<String, dynamic>>>[
      _safe(() => widget.apiService.getAlerts()),
      if (_isPro) _safe(() => widget.apiService.getMarketIntelAlerts()),
      if (_isPro) _safe(() => widget.apiService.getMarketProOverview()),
    ];
    final results = await Future.wait(futures);
    if (!mounted) return;

    final observed = results[0];
    final custom = _isPro ? results[1] : <String, dynamic>{};
    final watchlists = _isPro ? results[2] : <String, dynamic>{};
    setState(() {
      _observedAlerts = (observed['data'] as List?) ?? const [];
      _observedError = observed['error']?.toString();
      _customRules = ((custom['data'] as Map?)?['rules'] as List?) ?? const [];
      _customError = custom['error']?.toString();
      _forecastWatchlists =
          (((watchlists['data'] as Map?)?['watchlists']) as List?) ?? const [];
      _watchlistError = watchlists['error']?.toString();
      _loading = false;
      _refreshing = false;
    });
  }

  Future<void> _runAction(String id, Future<void> Function() action) async {
    if (_pendingActions.contains(id)) return;
    setState(() => _pendingActions.add(id));
    try {
      await action();
      await _load();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Action impossible : $error')),
        );
      }
    } finally {
      if (mounted) setState(() => _pendingActions.remove(id));
    }
  }

  Widget _section({
    required String title,
    required String description,
    required List<Widget> children,
    String? error,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w800,
                color: AppColors.ink,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              description,
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.muted,
              ),
            ),
            if (error != null) ...[
              const SizedBox(height: 8),
              Text(
                error,
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.danger,
                ),
              ),
            ] else if (children.isEmpty) ...[
              const SizedBox(height: 10),
              const Text(
                'Aucun élément pour le moment.',
                style: TextStyle(
                  fontSize: 12.5,
                  color: AppColors.muted,
                ),
              ),
            ] else ...[
              const Divider(height: 22),
              ...children,
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    final observedRows = _observedAlerts.whereType<Map>().toList();
    final customRows = _customRules.whereType<Map>().toList();
    final watchRows = _forecastWatchlists.whereType<Map>().toList();

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  'Surveillance des marchés',
                  style: TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w800,
                      color: AppColors.ink),
                ),
              ),
              if (_refreshing)
                const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else
                IconButton(
                  tooltip: 'Actualiser',
                  onPressed: _load,
                  icon: const Icon(Icons.refresh_rounded),
                ),
            ],
          ),
          const Text(
            'Un point d’accès commun, sans mélanger les règles ni les sources de calcul.',
            style: TextStyle(fontSize: 12.5, color: AppColors.muted),
          ),
          const SizedBox(height: 14),
          _section(
            title: 'Écarts de prix observés',
            description:
                'Détection automatique des écarts supérieurs au seuil choisi par défaut (15 %) entre le prix observé et le prix attendu.',
            error: _observedError,
            children: observedRows
                .map((r) => ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.trending_up_rounded,
                          color: AppColors.warning),
                      title: Text(
                        '${r['market_name'] ?? 'Marché'} · ${r['province'] ?? '—'}',
                      ),
                      subtitle: Text(
                        '${r['commodity_std'] ?? 'Produit'} · observé ${r['value'] ?? r['last_observed_price'] ?? '—'} XAF/kg · attendu ${r['predicted_price'] ?? '—'} XAF/kg',
                      ),
                      trailing: Text(
                        '${r['deviation_pct'] ?? '—'}%',
                        style: const TextStyle(
                            fontWeight: FontWeight.w800,
                            color: AppColors.danger),
                      ),
                    ))
                .toList(),
          ),
          _section(
            title: 'Règles personnalisées · prix observés',
            description:
                'Règles créées dans Intelligence : seuil, variation, écart médian ou nouvelle donnée. Elles sont évaluées sur l’historique observé.',
            error: _isPro ? _customError : 'Fonctionnalité réservée à PRO.',
            children: customRows.map((r) {
              final id = r['rule_id']?.toString() ?? '';
              final isNewData = r['kind'] == 'new_data';
              final triggered = r['triggered'] == true;
              return ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  triggered
                      ? Icons.notifications_active_rounded
                      : Icons.notifications_none_rounded,
                  color: triggered ? AppColors.warning : AppColors.muted,
                ),
                title: Text(
                  r['message']?.toString() ?? 'Règle de surveillance',
                ),
                subtitle: Text(
                  'Prix observé · ${r['as_of'] ?? 'date inconnue'} · ${triggered ? 'Déclenchée' : 'En attente'}',
                ),
                trailing: Wrap(
                  spacing: 0,
                  children: [
                    if (triggered && isNewData)
                      IconButton(
                        tooltip: 'Marquer comme lu',
                        onPressed: _pendingActions.contains(id)
                            ? null
                            : () => _runAction(
                                  id,
                                  () => widget.apiService.ackMarketIntelAlert(
                                    id,
                                  ),
                                ),
                        icon: const Icon(Icons.done_rounded),
                      ),
                    IconButton(
                      tooltip: 'Supprimer la règle',
                      onPressed: id.isEmpty || _pendingActions.contains(id)
                          ? null
                          : () => _runAction(
                                id,
                                () => widget.apiService.deleteMarketIntelAlert(
                                  id,
                                ),
                              ),
                      icon: const Icon(Icons.delete_outline_rounded),
                    ),
                  ],
                ),
              );
            }).toList(),
          ),
          _section(
            title: 'Watchlists · prix prévisionnels',
            description:
                'Seuils comparés au prix prévu ; si aucune prévision n’est disponible, le moteur utilise le dernier prix observé.',
            error: _isPro ? _watchlistError : 'Fonctionnalité réservée à PRO.',
            children: watchRows.map((r) {
              final id = r['watch_id']?.toString() ?? '';
              final triggered = r['triggered'] == true;
              return ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  triggered
                      ? Icons.notifications_active_rounded
                      : Icons.notifications_none_rounded,
                  color: triggered ? AppColors.warning : AppColors.muted,
                ),
                title: Text(
                  '${r['label_fr'] ?? r['commodity_std'] ?? 'Culture'} '
                  '${r['direction'] == 'above' ? '≥' : '≤'} '
                  '${r['threshold_xaf_kg'] ?? '—'} XAF/kg',
                ),
                subtitle: Text(
                  'Prévision : ${r['predicted_xaf_kg'] ?? '—'} XAF/kg · '
                  '${r['province']?.toString().isNotEmpty == true ? r['province'] : 'Toutes provinces'} · '
                  '${triggered ? 'Seuil atteint' : 'Sous surveillance'}',
                ),
                trailing: IconButton(
                  tooltip: 'Supprimer la watchlist',
                  onPressed: id.isEmpty || _pendingActions.contains(id)
                      ? null
                      : () => _runAction(
                            id,
                            () => widget.apiService.deleteMarketWatchlist(id),
                          ),
                  icon: const Icon(Icons.delete_outline_rounded),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }
}
