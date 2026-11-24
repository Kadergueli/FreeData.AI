import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import 'ml_benchmark_studio.dart';
import '../core/utils/error_text.dart';

class AdminScreen extends StatefulWidget {
  final ApiService apiService;

  const AdminScreen({super.key, required this.apiService});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  final _tokenCtrl = TextEditingController();
  final _searchCtrl = TextEditingController();
  Map<String, dynamic>? _adminMe;
  Map<String, dynamic>? _overview;
  List<Map<String, dynamic>> _users = const [];
  List<Map<String, dynamic>> _tickets = const [];
  List<Map<String, dynamic>> _paymentRequests = const [];
  List<Map<String, dynamic>> _proKeys = const [];
  List<Map<String, dynamic>> _agroProfiles = const [];
  String _agroFilter = 'all';
  int _tab =
      0; // 0: Système, 1: Utilisateurs, 2: Support, 3: Paiements, 4: Centre IA, 5: Agronomes
  bool _loading = false;
  bool _probing = false;
  String? _error;
  String? _paymentRequestsError;
  String? _proKeysError;
  String? _agroProfilesError;

  String get _token => _tokenCtrl.text.trim();

  Set<String> get _permissions {
    final raw = _adminMe?['permissions'];
    if (raw is List) return raw.map((e) => e.toString()).toSet();
    return const {};
  }

  bool _hasPerm(String perm) => _permissions.contains(perm);

  Future<void> _loadAll() async {
    if (_token.isEmpty) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final me = await widget.apiService.getAdminMe(_token);
      final perms = me['permissions'] is List
          ? (me['permissions'] as List).map((e) => e.toString()).toSet()
          : const <String>{};
      final results = await Future.wait([
        widget.apiService.getAdminOverview(_token),
        widget.apiService.getAdminUsers(_token, search: _searchCtrl.text),
        widget.apiService.getAdminSupportTickets(_token),
      ]);
      List<Map<String, dynamic>> payReqs = const [];
      List<Map<String, dynamic>> proKeys = const [];
      List<Map<String, dynamic>> agroProfiles = const [];
      String? paymentRequestsError;
      String? proKeysError;
      String? agroProfilesError;
      if (perms.contains('manage_subscriptions')) {
        final billingRes = await Future.wait<List<Map<String, dynamic>>>([
          widget.apiService
              .getAdminPaymentRequests(_token)
              .catchError((Object error) {
                paymentRequestsError = errText(error);
                return const <Map<String, dynamic>>[];
              }),
          widget.apiService
              .listAdminProKeys(_token)
              .catchError((Object error) {
                proKeysError = errText(error);
                return const <Map<String, dynamic>>[];
              }),
          widget.apiService
              .getAdminAgroProfiles(_token)
              .catchError((Object error) {
                agroProfilesError = errText(error);
                return _agroProfiles;
              }),
        ]);
        payReqs = billingRes[0];
        proKeys = billingRes[1];
        agroProfiles = billingRes[2];
      }
      if (!mounted) return;
      setState(() {
        _adminMe = me;
        _overview = results[0] as Map<String, dynamic>;
        _users = results[1] as List<Map<String, dynamic>>;
        _tickets = results[2] as List<Map<String, dynamic>>;
        _paymentRequests = payReqs;
        _proKeys = proKeys;
        _agroProfiles = agroProfiles;
        _paymentRequestsError = paymentRequestsError;
        _proKeysError = proKeysError;
        _agroProfilesError = agroProfilesError;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = errText(e);
        _loading = false;
      });
    }
  }


  Widget _sectionLoadWarning(String message) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          color: const Color(0xFFFFF7ED),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: const Color(0xFFFED7AA)),
        ),
        child: Row(
          children: [
            const Icon(Icons.warning_amber_rounded,
                size: 18, color: AppColors.warning),
            const SizedBox(width: 8),
            Expanded(
              child: Text(message,
                  style: const TextStyle(fontSize: 12.5, color: AppColors.ink)),
            ),
            IconButton(
              tooltip: 'Réessayer',
              visualDensity: VisualDensity.compact,
              icon: const Icon(Icons.refresh_rounded, size: 18),
              onPressed: _loadAll,
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _runLiveProbe() async {
    if (_token.isEmpty || _probing) return;
    setState(() {
      _probing = true;
      _error = null;
    });
    try {
      final freshOverview =
          await widget.apiService.getAdminOverview(_token, liveProbe: true);
      if (!mounted) return;
      setState(() {
        _overview = freshOverview;
        _probing = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text('Test de connectivité temps réel terminé.')),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _probing = false;
        _error = errText(e);
      });
    }
  }

  Future<void> _generateProKeyDialog() async {
    int selectedDays = 30;
    final noteCtrl = TextEditingController();
    try {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (ctx) => StatefulBuilder(
          builder: (ctx, setDialogState) => AlertDialog(
            title: const Text('Générer une clé PRO unique'),
            content: SizedBox(
              width: 380,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  DropdownButtonFormField<int>(
                    initialValue: selectedDays,
                    decoration: const InputDecoration(labelText: 'Durée PRO'),
                    items: const [
                      DropdownMenuItem(
                          value: 30, child: Text('30 jours (1 mois)')),
                      DropdownMenuItem(
                          value: 90, child: Text('90 jours (3 mois)')),
                      DropdownMenuItem(
                          value: 180, child: Text('180 jours (6 mois)')),
                      DropdownMenuItem(
                          value: 365, child: Text('365 jours (1 an)')),
                    ],
                    onChanged: (v) =>
                        setDialogState(() => selectedDays = v ?? 30),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: noteCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Client / Référence (optionnel)',
                      hintText: 'Ex. Coopérative Salamat — reçu #142',
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Annuler'),
              ),
              ElevatedButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Générer'),
              ),
            ],
          ),
        ),
      );
      if (confirmed != true || !mounted) return;
      final created = await widget.apiService.createAdminProKey(
        _token,
        durationDays: selectedDays,
        note: noteCtrl.text.trim(),
      );
      await _loadAll();
      if (!mounted) return;
      final plainKey = created['activation_key']?.toString() ?? '';
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Clé PRO unique générée'),
          content: SizedBox(
            width: 400,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Copiez et transmettez cette clé au client. Elle ne sera plus affichée en clair et ne pourra être activée que par un seul compte connecté.',
                  style: TextStyle(fontSize: 13, color: AppColors.muted),
                ),
                const SizedBox(height: 12),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppColors.blueSoft,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: SelectableText(
                    plainKey,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.1,
                      color: AppColors.blueDark,
                    ),
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () {
                Clipboard.setData(ClipboardData(text: plainKey));
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Clé PRO copiée.')),
                );
              },
              child: const Text('Copier'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Fermer'),
            ),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Erreur : ${errText(e)}')));
    }
  }

  Color _statusColor(String status) {
    final s = status.toUpperCase();
    if (s == 'CONNECTED' || s == 'OK' || s == 'FRESH') return AppColors.green;
    if (s == 'CONFIGURED') return AppColors.blue;
    if (s == 'DEGRADED' || s == 'NOT_CONFIGURED' || s == 'AGING') {
      return Colors.orange.shade800;
    }
    if (s == 'UNAVAILABLE' || s == 'ERROR' || s == 'STALE') {
      return AppColors.danger;
    }
    return AppColors.ink;
  }

  Future<void> _showModelCompareDialog(String modelId) async {
    try {
      final res =
          await widget.apiService.compareAdminMlModelVersions(_token, modelId);
      if (!mounted) return;
      final versions = (res['versions'] as List? ?? []).cast<Map>();
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text('Versions ML — $modelId'),
          content: SizedBox(
            width: 480,
            child: versions.isEmpty
                ? const Text('Aucune version enregistrée.')
                : SingleChildScrollView(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: versions.map((v) {
                        final ev = v['evaluation_metrics'] is Map
                            ? (v['evaluation_metrics'] as Map)
                            : const {};
                        final metricsStr = ev.isEmpty
                            ? 'Aucune métrique enregistrée'
                            : ev.entries
                                .map((e) => '${e.key}=${e.value}')
                                .join(' · ');
                        return ListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          title: Text(
                            'v${v['version']} · ${v['lifecycle_status']} '
                            '${v['is_active_production'] == true ? '(ACTIF PROD)' : ''}',
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                          subtitle: Text(
                            'Algo: ${v['algorithm'] ?? '—'} · Dataset: ${v['training_dataset_ref'] ?? '—'}\n'
                            'Métriques: $metricsStr\n'
                            'Exécutions: ${v['execution_count'] ?? 0} · Échecs: ${v['failure_count'] ?? 0}',
                          ),
                        );
                      }).toList(),
                    ),
                  ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Fermer'),
            ),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(errText(e))));
    }
  }

  Future<void> _runAction(Future<void> Function() action, String okMsg) async {
    try {
      await action();
      await _loadAll();
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(okMsg)));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(errText(e))));
    }
  }

  Future<void> _showActivatePlanDialog({String? prefillUserId}) async {
    final userCtrl = TextEditingController(text: prefillUserId ?? '');
    String planId = 'premium';
    final daysCtrl = TextEditingController(text: '30');
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Activer / Modifier un abonnement'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: userCtrl,
                  decoration: const InputDecoration(
                      labelText: 'Identifiant utilisateur (user_id)'),
                ),
                const SizedBox(height: 10),
                DropdownButtonFormField<String>(
                  initialValue: planId,
                  decoration: const InputDecoration(labelText: 'Plan'),
                  items: const [
                    DropdownMenuItem(
                        value: 'free', child: Text('Gratuit (free)')),
                    DropdownMenuItem(
                        value: 'trial', child: Text('Essai PRO (trial)')),
                    DropdownMenuItem(
                        value: 'premium',
                        child: Text('FreeData PRO (premium)')),
                  ],
                  onChanged: (v) => planId = v ?? 'premium',
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: daysCtrl,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'Durée (jours)'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Annuler')),
            ElevatedButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Appliquer')),
          ],
        ),
      );
      if (ok == true && userCtrl.text.trim().isNotEmpty) {
        final days = int.tryParse(daysCtrl.text.trim()) ?? 30;
        await _runAction(
          () => widget.apiService.activateAdminSubscription(
            _token,
            targetUserId: userCtrl.text.trim(),
            planId: planId,
            periodDays: days,
          ),
          'Abonnement mis à jour ($planId).',
        );
      }
    } finally {
      userCtrl.dispose();
      daysCtrl.dispose();
    }
  }

  @override
  void dispose() {
    _tokenCtrl.dispose();
    _searchCtrl.dispose();
    super.dispose();
  }

  Widget _kpiPill(String label, String value, {Color color = AppColors.ink}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.canvas,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label,
              style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
          const SizedBox(height: 2),
          Text(value,
              style: TextStyle(
                  fontSize: 14, fontWeight: FontWeight.w700, color: color)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final health = _overview?['api_health'] as Map? ?? {};
    final metrics = _overview?['api_metrics'] as Map? ?? {};
    final usersSum = _overview?['users_summary'] as Map? ?? {};
    final datasets = (_overview?['datasets'] as List? ?? []).cast<Map>();
    final audits = (_overview?['recent_audit_logs'] as List? ?? []).cast<Map>();
    final modelFlags = (_overview?['model_flags'] as Map? ?? {});

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
          title: const Text('Console Administration FreeData.AI',
              style: TextStyle(fontWeight: FontWeight.w700))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          FDCard(
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _tokenCtrl,
                    obscureText: true,
                    onSubmitted: (_) => _loadAll(),
                    decoration: const InputDecoration(
                      labelText: 'Jeton Administrateur (X-Admin-Token)',
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                FDPrimaryButton(
                  label: 'Charger',
                  icon: Icons.lock_open_rounded,
                  onPressed: _loading ? null : _loadAll,
                ),
              ],
            ),
          ),
          if (_loading) ...[
            const SizedBox(height: 16),
            const Center(child: CircularProgressIndicator())
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            FDCard(
                child: Text(_error!,
                    style: const TextStyle(color: AppColors.danger))),
          ],
          if (_overview != null) ...[
            if (_adminMe != null) ...[
              const SizedBox(height: 12),
              FDCard(
                padding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                child: Row(
                  children: [
                    const Icon(Icons.verified_user_outlined,
                        size: 18, color: AppColors.blue),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Connecté : ${_adminMe!['actor']} · Rôle : ${_adminMe!['role']}',
                        style: const TextStyle(
                            fontWeight: FontWeight.w700, color: AppColors.ink),
                      ),
                    ),
                    if (!_hasPerm('manage_users') && !_hasPerm('manage_system'))
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: AppColors.canvasSoft,
                          borderRadius: BorderRadius.circular(99),
                        ),
                        child: const Text('Lecture seule',
                            style: TextStyle(
                                fontSize: 11.5,
                                color: AppColors.muted,
                                fontWeight: FontWeight.w600)),
                      ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 14),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                ChoiceChip(
                  label: const Text('Système & IA'),
                  selected: _tab == 0,
                  onSelected: (_) => setState(() => _tab = 0),
                ),
                ChoiceChip(
                  label: const Text('Centre IA'),
                  selected: _tab == 4,
                  onSelected: (_) => setState(() => _tab = 4),
                ),
                ChoiceChip(
                  label: Text('Utilisateurs (${_users.length})'),
                  selected: _tab == 1,
                  onSelected: (_) => setState(() => _tab = 1),
                ),
                ChoiceChip(
                  label: Text('Tickets Support (${_tickets.length})'),
                  selected: _tab == 2,
                  onSelected: (_) => setState(() => _tab = 2),
                ),
                if (_hasPerm('manage_subscriptions')) ...[
                  ChoiceChip(
                    label: Text(
                      'Paiements (${_paymentRequests.where((r) => r['status'] == 'pending').length})',
                    ),
                    selected: _tab == 3,
                    onSelected: (_) => setState(() => _tab = 3),
                  ),
                  ChoiceChip(
                    label: Text(
                      'Agronomes (${_agroProfiles.where((p) => p['status'] == 'pending').length})',
                    ),
                    selected: _tab == 5,
                    onSelected: (_) => setState(() => _tab = 5),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 14),
            if (_tab == 0) ...[
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Santé & Opérations',
                        style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink)),
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        _kpiPill('Statut API',
                            '${health['status']} (v${health['version']})',
                            color: AppColors.green),
                        _kpiPill(
                            'Requêtes', '${metrics['total_requests'] ?? 0}',
                            color: AppColors.blue),
                        _kpiPill('Erreurs 5xx', '${metrics['error_5xx'] ?? 0}',
                            color: (metrics['error_5xx'] ?? 0) == 0
                                ? AppColors.green
                                : AppColors.danger),
                        _kpiPill('Latence moy.',
                            '${metrics['avg_latency_ms'] ?? 0} ms'),
                        _kpiPill('Utilisateurs',
                            '${usersSum['total_known_users'] ?? 0}'),
                        if ((metrics['document_indexing_requests'] ?? 0) > 0)
                          _kpiPill('Indexations docs',
                              '${metrics['document_indexing_requests']}'),
                        if (_overview!['deployment_info'] is Map)
                          _kpiPill(
                            'Environnement',
                            '${(_overview!['deployment_info'] as Map)['environment'] ?? '—'}'
                                '${(_overview!['deployment_info'] as Map)['git_commit'] != null ? ' (${(_overview!['deployment_info'] as Map)['git_commit']})' : ''}',
                            color: AppColors.blue,
                          ),
                        if (_overview!['storage_summary'] is Map)
                          _kpiPill(
                            'Persistance DB',
                            '${(_overview!['storage_summary'] as Map)['persistence_backend'] ?? '—'}',
                          ),
                        if (_overview!['background_jobs_summary'] is Map)
                          _kpiPill(
                            'Jobs PDF',
                            '${(_overview!['background_jobs_summary'] as Map)['total_tracked_jobs'] ?? 0} suivis',
                          ),
                      ],
                    ),
                    if (metrics['error_categories'] is Map) ...[
                      const SizedBox(height: 10),
                      Builder(builder: (_) {
                        final cats = metrics['error_categories'] as Map;
                        final nonZero = cats.entries
                            .where(
                                (e) => (e.value is num) && (e.value as num) > 0)
                            .toList();
                        if (nonZero.isEmpty) return const SizedBox.shrink();
                        return Wrap(
                          spacing: 8,
                          runSpacing: 6,
                          children: nonZero
                              .map((e) => _kpiPill(
                                    'Err: ${e.key}',
                                    '${e.value}',
                                    color: AppColors.danger,
                                  ))
                              .toList(),
                        );
                      }),
                    ],
                    if (metrics['recent_errors'] is List &&
                        (metrics['recent_errors'] as List).isNotEmpty) ...[
                      const SizedBox(height: 10),
                      const Text('Erreurs récentes (IDs de corrélation)',
                          style: TextStyle(
                              fontSize: 12.5,
                              fontWeight: FontWeight.w600,
                              color: AppColors.muted)),
                      const SizedBox(height: 4),
                      ...(metrics['recent_errors'] as List)
                          .reversed
                          .take(5)
                          .map((raw) {
                        final err = raw is Map ? raw : const {};
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 3),
                          child: Text(
                            '${err['status_code'] ?? ''} [${err['category'] ?? 'error'}] '
                            '${err['path'] ?? ''} · req=${err['request_id'] ?? '—'}',
                            style: const TextStyle(
                                fontSize: 11.5, color: AppColors.danger),
                          ),
                        );
                      }),
                    ],
                    if (_hasPerm('manage_system')) ...[
                      const SizedBox(height: 14),
                      Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        children: [
                          FDSecondaryButton(
                            label: 'Rafraîchir données Gold',
                            icon: Icons.refresh_rounded,
                            onPressed: () => _runAction(
                                () =>
                                    widget.apiService.refreshAdminData(_token),
                                'Données Gold rechargées.'),
                          ),
                          FDSecondaryButton(
                            label: 'Sauvegarde SQLite',
                            icon: Icons.backup_outlined,
                            onPressed: () => _runAction(
                                () => widget.apiService
                                    .triggerAdminBackup(_token),
                                'Sauvegarde exécutée.'),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
              if (_overview!['operational_warnings'] is List &&
                  (_overview!['operational_warnings'] as List).isNotEmpty) ...[
                const SizedBox(height: 12),
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Alertes opérationnelles',
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.danger)),
                      const SizedBox(height: 8),
                      ...(_overview!['operational_warnings'] as List).map((w) {
                        final item = w is Map ? w : const {};
                        final sev = (item['severity'] ?? 'warning')
                            .toString()
                            .toUpperCase();
                        final isError = sev == 'HIGH' ||
                            sev == 'ERROR' ||
                            sev == 'CRITICAL';
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 6),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(
                                isError
                                    ? Icons.error_outline_rounded
                                    : Icons.warning_amber_rounded,
                                size: 18,
                                color: isError
                                    ? AppColors.danger
                                    : Colors.orange.shade800,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  '[${item['code'] ?? 'ALERT'}] ${item['message'] ?? ''}',
                                  style: TextStyle(
                                    fontSize: 13,
                                    color: isError
                                        ? AppColors.danger
                                        : AppColors.ink,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        );
                      }),
                    ],
                  ),
                ),
              ],
              if (_overview!['providers_health'] is Map ||
                  _overview!['data_freshness'] is Map) ...[
                const SizedBox(height: 12),
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 10,
                        runSpacing: 8,
                        alignment: WrapAlignment.spaceBetween,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          const Text('Santé IA (Groq / Jina) & Services',
                              style: TextStyle(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.ink)),
                          FDSecondaryButton(
                            label: _probing
                                ? 'Test en cours...'
                                : 'Tester connectivité',
                            icon: Icons.network_check_rounded,
                            onPressed: _probing ? null : _runLiveProbe,
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Builder(builder: (_) {
                        final ph = _overview!['providers_health'] is Map
                            ? _overview!['providers_health'] as Map
                            : const {};
                        final services = ph['services'] is Map
                            ? ph['services'] as Map
                            : const {};
                        final df = _overview!['data_freshness'] is Map
                            ? _overview!['data_freshness'] as Map
                            : const {};
                        String svcStatus(
                            String key, String legacyKey, String fallback) {
                          return (services[key] ?? ph[legacyKey] ?? fallback)
                              .toString()
                              .toUpperCase();
                        }

                        final supa = svcStatus(
                            'supabase',
                            'supabase_status',
                            ph['supabase_pg_active'] == true
                                ? 'CONFIGURED'
                                : 'NOT_CONFIGURED');
                        final groq = svcStatus(
                            'groq',
                            'groq_status',
                            ph['groq_llm_configured'] == true
                                ? 'CONFIGURED'
                                : 'NOT_CONFIGURED');
                        final jina = svcStatus(
                            'jina',
                            'jina_status',
                            ph['jina_embed_configured'] == true
                                ? 'CONFIGURED'
                                : 'NOT_CONFIGURED');
                        final ml = svcStatus(
                            'ml_engine', 'ml_engine_status', 'CONNECTED');
                        final rag = svcStatus(
                            'rag_engine', 'rag_engine_status', 'CONNECTED');
                        final idx = svcStatus('document_indexing',
                            'document_indexing_status', 'DEGRADED');
                        final bg = svcStatus('background_jobs',
                            'background_jobs_status', 'CONNECTED');
                        final checkedAt = ph['checked_at_utc']?.toString();
                        final isLive = ph['live_probe_executed'] == true;
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (checkedAt != null && checkedAt.isNotEmpty) ...[
                              Text(
                                'Dernier contrôle : $checkedAt (${isLive ? 'Sonde active' : 'État passif'})',
                                style: const TextStyle(
                                    fontSize: 11.5, color: AppColors.muted),
                              ),
                              const SizedBox(height: 8),
                            ],
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                _kpiPill('Supabase PG', supa,
                                    color: _statusColor(supa)),
                                _kpiPill('Groq LLM', groq,
                                    color: _statusColor(groq)),
                                _kpiPill('Jina Embed', jina,
                                    color: _statusColor(jina)),
                                _kpiPill('Moteur ML', ml,
                                    color: _statusColor(ml)),
                                _kpiPill('Moteur RAG', rag,
                                    color: _statusColor(rag)),
                                _kpiPill('Indexation Docs', idx,
                                    color: _statusColor(idx)),
                                _kpiPill('Tâches arrière-plan', bg,
                                    color: _statusColor(bg)),
                                _kpiPill(
                                  'Dernier mois',
                                  '${df['latest_observation_month'] ?? '—'} (${df['freshness_status'] ?? '—'})',
                                  color: _statusColor(
                                      (df['freshness_status'] ?? '')
                                          .toString()),
                                ),
                              ],
                            ),
                          ],
                        );
                      }),
                    ],
                  ),
                ),
              ],
              if (_overview!['domains_summary'] is Map ||
                  _overview!['ml_registry_summary'] is Map) ...[
                const SizedBox(height: 12),
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                          'Centre de contrôle IA (Domaines & Registre ML)',
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink)),
                      const SizedBox(height: 8),
                      Builder(builder: (_) {
                        final ds = _overview!['domains_summary'] is Map
                            ? _overview!['domains_summary'] as Map
                            : const {};
                        final ms = _overview!['ml_registry_summary'] is Map
                            ? _overview!['ml_registry_summary'] as Map
                            : const {};
                        final byDep = ms['by_deployment_status'] is Map
                            ? ms['by_deployment_status'] as Map
                            : const {};
                        final mlModels =
                            (_overview!['ml_models'] as List? ?? [])
                                .cast<Map>();
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                _kpiPill(
                                  'Domaines actifs',
                                  '${ds['active_domains'] ?? 0} / ${ds['total_domains'] ?? 0}',
                                  color: AppColors.blue,
                                ),
                                _kpiPill(
                                  'Modèles ML enregistrés',
                                  '${ms['total_registered_models'] ?? mlModels.length}',
                                ),
                                _kpiPill(
                                  'Déployés',
                                  '${byDep['DEPLOYED'] ?? 0}',
                                  color: AppColors.green,
                                ),
                                _kpiPill(
                                  'Exécutions ML',
                                  '${ms['total_executions'] ?? 0}',
                                ),
                                _kpiPill(
                                  'Échecs ML',
                                  '${ms['total_failures'] ?? 0}',
                                  color: (ms['total_failures'] ?? 0) == 0
                                      ? AppColors.green
                                      : AppColors.danger,
                                ),
                              ],
                            ),
                            if (mlModels.isNotEmpty) ...[
                              const SizedBox(height: 10),
                              ...mlModels.take(8).map((m) {
                                final st =
                                    (m['lifecycle_status'] ?? 'REGISTERED')
                                        .toString();
                                return ListTile(
                                  dense: true,
                                  contentPadding: EdgeInsets.zero,
                                  title: Text(
                                    '${m['model_id'] ?? m['name']} v${m['version'] ?? 1} (${m['algorithm'] ?? '—'})',
                                    style: const TextStyle(
                                        fontSize: 13,
                                        fontWeight: FontWeight.w600),
                                  ),
                                  subtitle: Text(
                                    'Domaine : ${m['domain'] ?? '—'} · Tâche : ${m['task_type'] ?? '—'} · Dataset : ${m['training_dataset_ref'] ?? '—'}',
                                    style: const TextStyle(fontSize: 11.5),
                                  ),
                                  trailing: Text(
                                    st,
                                    style: TextStyle(
                                      fontSize: 11.5,
                                      fontWeight: FontWeight.w700,
                                      color: _statusColor(
                                          st == 'DEPLOYED' ? 'CONNECTED' : st),
                                    ),
                                  ),
                                );
                              }),
                            ],
                          ],
                        );
                      }),
                    ],
                  ),
                ),
              ],
              if (modelFlags.isNotEmpty) ...[
                const SizedBox(height: 12),
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Profils Modèles IA',
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink)),
                      const SizedBox(height: 6),
                      ...modelFlags.entries.map((e) {
                        final enabled = e.value == true;
                        return SwitchListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          title: Text(e.key,
                              style:
                                  const TextStyle(fontWeight: FontWeight.w600)),
                          value: enabled,
                          onChanged: _hasPerm('manage_models')
                              ? (v) => _runAction(
                                    () => widget.apiService
                                        .toggleAdminModel(_token, e.key, v),
                                    'Profil ${e.key} ${v ? 'activé' : 'désactivé'}.',
                                  )
                              : null,
                        );
                      }),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: 12),
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Jeux de données & Licences',
                        style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink)),
                    const SizedBox(height: 6),
                    ...datasets.map((d) => ListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          title: Text(d['dataset_id'].toString(),
                              style:
                                  const TextStyle(fontWeight: FontWeight.w600)),
                          subtitle: Text(
                              '${d['license_category']} · Statut : ${d['publication_status']}'),
                        )),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Journal d’audit récent',
                        style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink)),
                    const SizedBox(height: 6),
                    if (audits.isEmpty)
                      const Text('Aucune action enregistrée.',
                          style: TextStyle(color: AppColors.muted))
                    else
                      ...audits.take(10).map((a) => ListTile(
                            dense: true,
                            contentPadding: EdgeInsets.zero,
                            title: Text('${a['action']} (${a['resource_id']})'),
                            subtitle: Text(
                                '${a['actor']} [${a['actor_role']}] · ${a['created_at']}'),
                          )),
                  ],
                ),
              ),
            ],
            if (_tab == 4) ...[
              MLBenchmarkStudio(
                apiService: widget.apiService,
                adminToken: _token,
                overview: _overview!,
                canManageModels: _hasPerm('manage_models'),
                onRefreshOverview: _loadAll,
                onCompareModel: _showModelCompareDialog,
                statusColor: _statusColor,
              ),
            ],
            if (_tab == 1) ...[
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _searchCtrl,
                            onSubmitted: (_) => _loadAll(),
                            decoration: const InputDecoration(
                                labelText: 'Rechercher un utilisateur'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        FDSecondaryButton(
                            label: 'Filtrer',
                            icon: Icons.search_rounded,
                            onPressed: _loadAll),
                        if (_hasPerm('manage_subscriptions')) ...[
                          const SizedBox(width: 8),
                          FDPrimaryButton(
                            label: 'Activer plan',
                            icon: Icons.workspace_premium_outlined,
                            onPressed: () => _showActivatePlanDialog(),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 12),
                    if (_users.isEmpty)
                      const Text('Aucun utilisateur enregistré pour le moment.',
                          style: TextStyle(color: AppColors.muted))
                    else
                      ..._users.map((u) {
                        final uid = u['user_id'].toString();
                        final email = u['email']?.toString().trim() ?? '';
                        final displayName =
                            u['display_name']?.toString().trim() ?? '';
                        final status =
                            (u['account_status'] ?? u['status'])?.toString() ??
                                'active';
                        final suspended = status == 'suspended';
                        final titleText = email.isNotEmpty
                            ? (displayName.isNotEmpty
                                ? '$displayName · $email ($uid)'
                                : '$email ($uid)')
                            : uid;
                        return ListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          title: Text(titleText,
                              style:
                                  const TextStyle(fontWeight: FontWeight.w600)),
                          subtitle: Text(
                              'Plan : ${u['plan_id']} · Statut : $status · Rôle : ${u['role']}'),
                          trailing: (_hasPerm('manage_subscriptions') ||
                                  _hasPerm('manage_users'))
                              ? Wrap(
                                  spacing: 6,
                                  children: [
                                    if (_hasPerm('manage_subscriptions'))
                                      TextButton(
                                        onPressed: () =>
                                            _showActivatePlanDialog(
                                                prefillUserId: uid),
                                        child: const Text('Plan'),
                                      ),
                                    if (_hasPerm('manage_users'))
                                      TextButton(
                                        onPressed: () => _runAction(
                                          () => widget.apiService
                                              .setAdminUserStatus(
                                                  _token,
                                                  uid,
                                                  suspended
                                                      ? 'active'
                                                      : 'suspended'),
                                          suspended
                                              ? 'Utilisateur réactivé.'
                                              : 'Utilisateur suspendu.',
                                        ),
                                        child: Text(
                                            suspended
                                                ? 'Réactiver'
                                                : 'Suspendre',
                                            style: TextStyle(
                                                color: suspended
                                                    ? AppColors.green
                                                    : AppColors.danger)),
                                      ),
                                  ],
                                )
                              : null,
                        );
                      }),
                  ],
                ),
              ),
            ],
            if (_tab == 2) ...[
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Tickets Support Utilisateurs',
                        style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink)),
                    const SizedBox(height: 8),
                    if (_tickets.isEmpty)
                      const Text('Aucun ticket support.',
                          style: TextStyle(color: AppColors.muted))
                    else
                      ..._tickets.map((t) {
                        final tid = t['ticket_id'].toString();
                        return ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text('${t['subject']} (${t['category']})',
                              style:
                                  const TextStyle(fontWeight: FontWeight.w600)),
                          subtitle: Text(
                              'De : ${t['owner_id']} · Statut : ${t['status']} · Priorité : ${t['priority']}\n${t['description']}'),
                          trailing: _hasPerm('manage_users')
                              ? PopupMenuButton<String>(
                                  onSelected: (s) => _runAction(
                                    () => widget.apiService
                                        .updateAdminTicketStatus(
                                            _token, tid, s),
                                    'Ticket passé à $s.',
                                  ),
                                  itemBuilder: (_) => const [
                                    PopupMenuItem(
                                        value: 'in_progress',
                                        child: Text('En cours')),
                                    PopupMenuItem(
                                        value: 'resolved',
                                        child: Text('Résolu')),
                                    PopupMenuItem(
                                        value: 'closed', child: Text('Fermé')),
                                  ],
                                )
                              : null,
                        );
                      }),
                  ],
                ),
              ),
            ],
            if (_tab == 3 && _hasPerm('manage_subscriptions')) ...[
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Expanded(
                          child: Text(
                            'Clés d’activation PRO uniques (1 clé = 1 compte)',
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink,
                            ),
                          ),
                        ),
                        FDPrimaryButton(
                          label: 'Générer une clé',
                          icon: Icons.vpn_key_outlined,
                          onPressed: _generateProKeyDialog,
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    if (_proKeysError != null)
                      _sectionLoadWarning(
                          'Impossible de charger les clés PRO : $_proKeysError'),
                    if (_proKeysError == null && _proKeys.isEmpty)
                      const Text(
                        'Aucune clé d’activation unique générée pour le moment.',
                        style: TextStyle(color: AppColors.muted),
                      )
                    else if (_proKeysError == null)
                      ..._proKeys.map((k) {
                        final keyId = k['key_id']?.toString() ?? '';
                        final prefix = k['key_prefix']?.toString() ?? keyId;
                        final status = k['status']?.toString() ?? 'unused';
                        final days = k['duration_days'] ?? 30;
                        final isUnused = status == 'unused';
                        final statusLabel = status == 'redeemed'
                            ? 'Utilisée'
                            : (status == 'revoked' ? 'Révoquée' : 'Disponible');
                        final statusColor = status == 'redeemed'
                            ? AppColors.greenDark
                            : (status == 'revoked'
                                ? AppColors.danger
                                : AppColors.blue);
                        return ListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          title: Text(
                            '$prefix… · $days j',
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                          subtitle: Text(
                            'ID : $keyId · Statut : $statusLabel'
                            '${(k['redeemed_by_user_id']?.toString().isNotEmpty ?? false) ? ' · Compte : ${k['redeemed_by_user_id']}' : ''}'
                            '${(k['note']?.toString().isNotEmpty ?? false) ? '\nNote : ${k['note']}' : ''}',
                          ),
                          trailing: isUnused
                              ? TextButton(
                                  onPressed: () => _runAction(
                                    () => widget.apiService
                                        .revokeAdminProKey(_token, keyId),
                                    'Clé PRO révoquée.',
                                  ),
                                  child: const Text(
                                    'Révoquer',
                                    style: TextStyle(color: AppColors.danger),
                                  ),
                                )
                              : Text(
                                  statusLabel,
                                  style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: statusColor,
                                  ),
                                ),
                        );
                      }),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Demandes de paiement PRO (Mobile Money / Virement)',
                      style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink),
                    ),
                    const SizedBox(height: 8),
                    if (_paymentRequestsError != null)
                      _sectionLoadWarning(
                          'Impossible de charger les demandes de paiement : $_paymentRequestsError'),
                    if (_paymentRequestsError == null && _paymentRequests.isEmpty)
                      const Text('Aucune demande de paiement enregistrée.',
                          style: TextStyle(color: AppColors.muted))
                    else if (_paymentRequestsError == null)
                      ..._paymentRequests.map((r) {
                        final reqId = r['request_id'].toString();
                        final status = r['status']?.toString() ?? 'pending';
                        final isPending = status == 'pending';
                        return ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text(
                            '${r['provider']} · ${r['amount_xaf'] ?? 0} XAF · Réf. ${r['transaction_ref']}',
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          subtitle: Text(
                            'Utilisateur : ${r['user_id']} · Payeur : ${r['phone_or_ref']} · Statut : $status'
                            '${(r['note']?.toString().isNotEmpty ?? false) ? '\nNote : ${r['note']}' : ''}',
                          ),
                          trailing: isPending
                              ? Wrap(
                                  spacing: 6,
                                  children: [
                                    TextButton(
                                      onPressed: () => _runAction(
                                        () => widget.apiService
                                            .reviewAdminPaymentRequest(
                                          _token,
                                          reqId,
                                          decision: 'approved',
                                          periodDays: 30,
                                        ),
                                        'Paiement approuvé : PRO activé (30 j).',
                                      ),
                                      child: const Text('Approuver',
                                          style: TextStyle(
                                              color: AppColors.green)),
                                    ),
                                    TextButton(
                                      onPressed: () => _runAction(
                                        () => widget.apiService
                                            .reviewAdminPaymentRequest(
                                          _token,
                                          reqId,
                                          decision: 'rejected',
                                        ),
                                        'Demande de paiement refusée.',
                                      ),
                                      child: const Text('Refuser',
                                          style: TextStyle(
                                              color: AppColors.danger)),
                                    ),
                                  ],
                                )
                              : Text(
                                  status == 'approved' ? 'Validé' : 'Refusé',
                                  style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: status == 'approved'
                                        ? AppColors.green
                                        : AppColors.danger,
                                  ),
                                ),
                        );
                      }),
                  ],
                ),
              ),
            ],
            if (_tab == 5 && _hasPerm('manage_subscriptions')) ...[
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Certifications officielles Agronome PRO',
                      style: TextStyle(
                        fontSize: 15.5,
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'Vérifiez l’identité et le numéro d’agrément/RCCM des agronomes avant de débloquer la génération de bulletins PDF co-brandés.',
                      style: TextStyle(fontSize: 12.5, color: AppColors.muted),
                    ),
                    const SizedBox(height: 12),
                    if (_agroProfilesError != null)
                      _sectionLoadWarning(
                          'Impossible de charger les profils agronomes : $_agroProfilesError'),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final f in const [
                          ('all', 'Tous'),
                          ('pending', 'En attente'),
                          ('approved', 'Validés'),
                          ('rejected', 'Refusés'),
                        ])
                          ChoiceChip(
                            label: Text(f.$2),
                            selected: _agroFilter == f.$1,
                            onSelected: (_) =>
                                setState(() => _agroFilter = f.$1),
                          ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Builder(
                      builder: (_) {
                        final visible = _agroFilter == 'all'
                            ? _agroProfiles
                            : _agroProfiles
                                .where((p) => p['status'] == _agroFilter)
                                .toList();
                        if (visible.isEmpty) {
                          return const Padding(
                            padding: EdgeInsets.symmetric(vertical: 12),
                            child: Text(
                              'Aucune demande dans cette catégorie.',
                              style: TextStyle(color: AppColors.muted),
                            ),
                          );
                        }
                        return Column(
                          children: visible.map((p) {
                            final oid = p['owner_id'].toString();
                            final st = p['status']?.toString() ?? 'pending';
                            final isPending = st == 'pending';
                            final isOk = st == 'approved';
                            return Container(
                              margin: const EdgeInsets.only(bottom: 10),
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: const Color(0xFFF8FAFC),
                                border:
                                    Border.all(color: const Color(0xFFCBD5E1)),
                                borderRadius: BorderRadius.circular(10),
                              ),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 6,
                                    crossAxisAlignment:
                                        WrapCrossAlignment.center,
                                    children: [
                                      Text(
                                        p['firm_name']?.toString() ?? '—',
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w800,
                                          fontSize: 14.5,
                                          color: AppColors.ink,
                                        ),
                                      ),
                                      FDBadge(
                                        label: isOk
                                            ? 'VALIDÉ'
                                            : (isPending
                                                ? 'EN ATTENTE'
                                                : 'REFUSÉ'),
                                        color: isOk
                                            ? AppColors.greenDark
                                            : (isPending
                                                ? AppColors.blue
                                                : AppColors.danger),
                                        backgroundColor: isOk
                                            ? AppColors.greenSoft
                                            : (isPending
                                                ? AppColors.blueSoft
                                                : const Color(0xFFFEE2E2)),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 6),
                                  Text(
                                    'Agrément / RCCM : ${p['license_number'] ?? '—'}',
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w600,
                                      fontSize: 13,
                                      color: AppColors.ink,
                                    ),
                                  ),
                                  const SizedBox(height: 2),
                                  Text(
                                    'Adresse : ${(p['address']?.toString().isNotEmpty ?? false) ? p['address'] : '—'} · '
                                    'Contact : ${(p['contact']?.toString().isNotEmpty ?? false) ? p['contact'] : '—'}',
                                    style: const TextStyle(
                                        fontSize: 12.5, color: AppColors.muted),
                                  ),
                                  const SizedBox(height: 2),
                                  Text(
                                    'Compte : $oid · Soumis le : ${p['submitted_at'] ?? '—'}',
                                    style: const TextStyle(
                                        fontSize: 11.5, color: AppColors.muted),
                                  ),
                                  if ((p['admin_note']?.toString().isNotEmpty ??
                                      false))
                                    Padding(
                                      padding: const EdgeInsets.only(top: 4),
                                      child: Text(
                                        'Motif : ${p['admin_note']}',
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: AppColors.danger,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ),
                                  const SizedBox(height: 10),
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 6,
                                    children: [
                                      if (!isOk)
                                        FDPrimaryButton(
                                          label: 'Approuver & Débloquer PDF',
                                          icon: Icons.verified_rounded,
                                          onPressed: () => _runAction(
                                            () => widget.apiService
                                                .reviewAdminAgroProfile(
                                              _token,
                                              oid,
                                              status: 'approved',
                                            ),
                                            'Profil agronome approuvé : génération PDF débloquée.',
                                          ),
                                        ),
                                      if (isPending || isOk)
                                        FDSecondaryButton(
                                          label: 'Refuser',
                                          icon: Icons.block_rounded,
                                          onPressed: () =>
                                              _rejectAgroProfileDialog(
                                            oid,
                                            p['firm_name']?.toString() ?? '',
                                          ),
                                        ),
                                    ],
                                  ),
                                ],
                              ),
                            );
                          }).toList(),
                        );
                      },
                    ),
                  ],
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }

  Future<void> _rejectAgroProfileDialog(String ownerId, String firmName) async {
    final noteCtrl = TextEditingController(
        text: 'Numéro d’agrément ou coordonnées officielles incomplets.');
    try {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text('Refuser « $firmName »'),
          content: TextField(
            controller: noteCtrl,
            maxLines: 2,
            decoration: const InputDecoration(
              labelText: 'Motif affiché à l’utilisateur',
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Annuler'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Confirmer le refus'),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted) return;
      await _runAction(
        () => widget.apiService.reviewAdminAgroProfile(
          _token,
          ownerId,
          status: 'rejected',
          adminNote: noteCtrl.text.trim(),
        ),
        'Profil agronome refusé.',
      );
    } finally {
      noteCtrl.dispose();
    }
  }
}
