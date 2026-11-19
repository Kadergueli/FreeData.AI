import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';

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
  int _tab = 0; // 0: Système, 1: Utilisateurs, 2: Support, 3: Paiements
  bool _loading = false;
  bool _probing = false;
  String? _error;

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
      if (perms.contains('manage_subscriptions')) {
        try {
          payReqs = await widget.apiService.getAdminPaymentRequests(_token);
        } catch (_) {}
      }
      if (!mounted) return;
      setState(() {
        _adminMe = me;
        _overview = results[0] as Map<String, dynamic>;
        _users = results[1] as List<Map<String, dynamic>>;
        _tickets = results[2] as List<Map<String, dynamic>>;
        _paymentRequests = payReqs;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
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
        _error = e.toString();
      });
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
          .showSnackBar(SnackBar(content: Text(e.toString())));
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
                        child: Text('Partenaire PRO (premium)')),
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
                  label: Text('Utilisateurs (${_users.length})'),
                  selected: _tab == 1,
                  onSelected: (_) => setState(() => _tab = 1),
                ),
                ChoiceChip(
                  label: Text('Tickets Support (${_tickets.length})'),
                  selected: _tab == 2,
                  onSelected: (_) => setState(() => _tab = 2),
                ),
                if (_hasPerm('manage_subscriptions'))
                  ChoiceChip(
                    label: Text(
                      'Paiements (${_paymentRequests.where((r) => r['status'] == 'pending').length})',
                    ),
                    selected: _tab == 3,
                    onSelected: (_) => setState(() => _tab = 3),
                  ),
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
                    const Text(
                      'Demandes de paiement PRO (Mobile Money / Virement)',
                      style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink),
                    ),
                    const SizedBox(height: 8),
                    if (_paymentRequests.isEmpty)
                      const Text('Aucune demande de paiement enregistrée.',
                          style: TextStyle(color: AppColors.muted))
                    else
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
          ],
        ],
      ),
    );
  }
}
