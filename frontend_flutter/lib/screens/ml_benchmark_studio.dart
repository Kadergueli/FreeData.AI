import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/file_picker.dart';
import '../services/api_service.dart';

/// Phase 13 — Professional ML Benchmark Studio & AI Control Center workspace.
///
/// Organised into 6 distinct operational views:
/// 0. Vue d'ensemble (Studio Overview)
/// 1. Expériences (5-step guided CSV Benchmark workflow)
/// 2. Comparaison (Side-by-side Model Comparison DataTable)
/// 3. Registre ML (Model Lifecycle Management + Human Approval Deployment)
/// 4. Historique (Searchable/Filterable Experiment History)
/// 5. Monitoring IA (AI Domains & Infrastructure Telemetry)
class MLBenchmarkStudio extends StatefulWidget {
  final ApiService apiService;
  final String adminToken;
  final Map<String, dynamic> overview;
  final bool canManageModels;
  final Future<void> Function() onRefreshOverview;
  final Future<void> Function(String modelId) onCompareModel;
  final Color Function(String status) statusColor;
  final Future<PickedDocumentFile?> Function()? onPickCsv;
  final Duration pollInterval;

  const MLBenchmarkStudio({
    super.key,
    required this.apiService,
    required this.adminToken,
    required this.overview,
    required this.canManageModels,
    required this.onRefreshOverview,
    required this.onCompareModel,
    required this.statusColor,
    this.onPickCsv,
    this.pollInterval = const Duration(milliseconds: 1200),
  });

  @override
  State<MLBenchmarkStudio> createState() => _MLBenchmarkStudioState();
}

class _MLBenchmarkStudioState extends State<MLBenchmarkStudio> {
  static const int _maxCsvBytes = 5 * 1024 * 1024;
  static const int _maxPollTicks = 60;

  static const Map<String, List<String>> _compatibleAlgorithmsByTask = {
    'forecasting': [
      'naive_last',
      'moving_average_3',
      'seasonal_naive_12',
      'ridge_causal_lags_a1',
      'ridge_causal_lags_a10',
    ],
    'regression': ['naive_mean', 'linear_ols', 'ridge_l2'],
    'classification': ['majority_class', 'logistic_l2', 'knn_k5'],
    'clustering': ['kmeans_k3', 'kmeans_k4', 'kmeans_k5'],
  };

  int _section = 0;

  // --- Experiment 5-step workflow state ---
  int _expStep =
      0; // 0: Dataset, 1: Config, 2: Review, 3: Execution, 4: Results
  PickedDocumentFile? _pickedCsv;
  List<String> _csvHeaders = const [];
  String? _csvValidationError;
  String _selectedDomain = 'agriculture';
  String _selectedTask = 'forecasting';
  String? _targetColumn;
  String? _timeColumn;
  final Set<String> _featureColumns = {};
  final TextEditingController _expNameCtrl = TextEditingController();
  final TextEditingController _expDescCtrl = TextEditingController();
  bool _submitting = false;
  Map<String, dynamic>? _activeJob;
  Timer? _pollTimer;
  int _pollTicks = 0;

  // --- History & Registry Filters ---
  List<Map<String, dynamic>> _historyJobs = const [];
  bool _loadingHistory = false;
  String? _historyError;
  final TextEditingController _historySearchCtrl = TextEditingController();
  String _historyDomainFilter = 'all';
  String _historyTaskFilter = 'all';
  String _historyStatusFilter = 'all';
  bool _historySortNewestFirst = true;

  String _registryDomainFilter = 'all';
  String _registryTaskFilter = 'all';
  String _registryStatusFilter = 'all';

  @override
  void initState() {
    super.initState();
    final domains = _availableDomains;
    if (domains.isNotEmpty) {
      _selectedDomain =
          (domains.first['domain_id'] ?? 'agriculture').toString();
    }
    _loadHistory();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _expNameCtrl.dispose();
    _expDescCtrl.dispose();
    _historySearchCtrl.dispose();
    super.dispose();
  }

  List<Map<String, dynamic>> get _availableDomains {
    final ds = widget.overview['domains_summary'];
    if (ds is Map && ds['domains'] is List) {
      return (ds['domains'] as List)
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
    }
    return const [];
  }

  List<Map<String, dynamic>> get _allModels {
    final raw = widget.overview['ml_models'];
    if (raw is List) {
      return raw
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
    }
    return const [];
  }

  Map<String, dynamic> get _mlSummary {
    final raw = widget.overview['ml_registry_summary'];
    return raw is Map ? Map<String, dynamic>.from(raw) : const {};
  }

  Future<void> _loadHistory() async {
    if (widget.adminToken.isEmpty) return;
    setState(() {
      _loadingHistory = true;
      _historyError = null;
    });
    try {
      final list = await widget.apiService
          .listAdminBenchmarkJobs(widget.adminToken, limit: 30);
      if (!mounted) return;
      setState(() {
        _historyJobs = list;
        _loadingHistory = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _historyError = e.toString();
        _loadingHistory = false;
      });
    }
  }

  Future<void> _pickCsvFile() async {
    final picker = widget.onPickCsv ?? pickUserDocumentFile;
    final picked = await picker();
    if (picked == null || !mounted) return;

    if (!picked.name.toLowerCase().endsWith('.csv')) {
      setState(() {
        _pickedCsv = null;
        _csvHeaders = const [];
        _csvValidationError =
            'Format refusé : seul un fichier .csv (UTF-8) est accepté.';
      });
      return;
    }
    if (picked.bytes.isEmpty || picked.bytes.length > _maxCsvBytes) {
      setState(() {
        _pickedCsv = null;
        _csvHeaders = const [];
        _csvValidationError =
            'Taille invalide : le CSV doit être non vide et ≤ 5 Mo.';
      });
      return;
    }

    try {
      final text = utf8.decode(picked.bytes);
      final lines = text
          .split(RegExp(r'\r?\n'))
          .where((l) => l.trim().isNotEmpty)
          .toList();
      if (lines.length < 2) {
        setState(() {
          _pickedCsv = null;
          _csvHeaders = const [];
          _csvValidationError =
              'Le CSV doit contenir une ligne d’en-tête et au moins une ligne de données.';
        });
        return;
      }
      final headers = lines.first
          .split(',')
          .map((h) => h.trim().replaceAll('"', '').replaceAll("'", ''))
          .where((h) => h.isNotEmpty)
          .toList();
      if (headers.toSet().length != headers.length) {
        setState(() {
          _pickedCsv = null;
          _csvHeaders = const [];
          _csvValidationError =
              'Colonnes en double détectées dans l’en-tête CSV.';
        });
        return;
      }
      setState(() {
        _pickedCsv = picked;
        _csvHeaders = headers;
        _csvValidationError = null;
        _targetColumn = headers.isNotEmpty ? headers.last : null;
        _timeColumn = headers.isNotEmpty ? headers.first : null;
        _featureColumns
          ..clear()
          ..addAll(headers.where((h) => h != _targetColumn));
        if (_expNameCtrl.text.trim().isEmpty) {
          _expNameCtrl.text = picked.name;
        }
      });
    } catch (_) {
      setState(() {
        _pickedCsv = null;
        _csvHeaders = const [];
        _csvValidationError = 'Encodage CSV invalide : UTF-8 requis.';
      });
    }
  }

  List<String> _validateExperimentConfig() {
    final warnings = <String>[];
    if (_pickedCsv == null) {
      warnings.add('Aucun fichier CSV sélectionné.');
    }
    if (_selectedTask != 'clustering' &&
        (_targetColumn == null || _targetColumn!.isEmpty)) {
      warnings.add('Colonne cible requise pour la tâche $_selectedTask.');
    }
    if (_selectedTask == 'forecasting' &&
        (_timeColumn == null || _timeColumn!.isEmpty)) {
      warnings
          .add('Colonne temporelle requise pour la prévision (forecasting).');
    }
    if (_selectedTask != 'forecasting' && _featureColumns.isEmpty) {
      warnings.add('Sélectionnez au moins une colonne explicative (feature).');
    }
    if (_selectedTask != 'clustering' &&
        _targetColumn != null &&
        _featureColumns.contains(_targetColumn)) {
      warnings.add(
          'Fuite de cible : la colonne cible ne doit pas figurer dans les features.');
    }
    return warnings;
  }

  Future<void> _launchBenchmark() async {
    if (!widget.canManageModels || _submitting || _pickedCsv == null) return;
    final issues = _validateExperimentConfig();
    if (issues.isNotEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(issues.first)));
      return;
    }

    setState(() {
      _submitting = true;
      _expStep = 3;
    });
    try {
      final b64 = base64Encode(_pickedCsv!.bytes);
      final job = await widget.apiService.launchAdminBenchmark(
        widget.adminToken,
        domain: _selectedDomain,
        taskType: _selectedTask,
        featureColumns: _featureColumns
            .where((c) => _selectedTask == 'clustering' || c != _targetColumn)
            .toList(),
        targetColumn: _selectedTask == 'clustering' ? null : _targetColumn,
        timeColumn: _selectedTask == 'forecasting' ? _timeColumn : null,
        datasetName: _expNameCtrl.text.trim().isEmpty
            ? _pickedCsv!.name
            : _expNameCtrl.text.trim(),
        datasetScope: 'platform_public',
        datasetProvenance: {
          if (_expDescCtrl.text.trim().isNotEmpty)
            'description': _expDescCtrl.text.trim(),
          'source_filename': _pickedCsv!.name,
        },
        csvBase64: b64,
      );
      if (!mounted) return;
      setState(() {
        _activeJob = job;
        _submitting = false;
      });
      _startBoundedPolling(job['job_id'].toString());
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _activeJob = {
          'status': 'failed',
          'error': e.toString(),
        };
      });
    }
  }

  void _startBoundedPolling(String jobId) {
    _pollTimer?.cancel();
    _pollTicks = 0;
    _pollTimer = Timer.periodic(widget.pollInterval, (timer) async {
      if (!mounted) {
        timer.cancel();
        return;
      }
      _pollTicks += 1;
      if (_pollTicks > _maxPollTicks) {
        timer.cancel();
        return;
      }
      try {
        final st = await widget.apiService
            .getAdminBenchmarkJob(widget.adminToken, jobId);
        if (!mounted) {
          timer.cancel();
          return;
        }
        final status = (st['status'] ?? '').toString();
        setState(() {
          _activeJob = st;
          if (status == 'completed') {
            _expStep = 4;
          }
        });
        if (status == 'completed' ||
            status == 'failed' ||
            status == 'timed_out') {
          timer.cancel();
          await _loadHistory();
          await widget.onRefreshOverview();
        }
      } catch (_) {
        // Keep polling up to bounded limit on transient errors
      }
    });
  }

  Future<void> _confirmAndDeployModel(Map<String, dynamic> model) async {
    if (!widget.canManageModels) return;
    final modelId = (model['model_id'] ?? model['name'] ?? '').toString();
    final version = (model['version'] is int)
        ? model['version'] as int
        : int.tryParse('${model['version']}') ?? 1;
    final domain = (model['domain'] ?? '—').toString();
    final task = (model['task_type'] ?? '—').toString();
    final metrics = model['evaluation_metrics'] is Map
        ? (model['evaluation_metrics'] as Map)
        : const {};

    final currentProd = _allModels.cast<Map<String, dynamic>?>().firstWhere(
          (m) =>
              m != null &&
              m['model_id'] == modelId &&
              m['is_active_production'] == true,
          orElse: () => null,
        );

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Approbation de déploiement en production'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Modèle : $modelId (v$version)',
                  style: const TextStyle(fontWeight: FontWeight.w700)),
              Text('Domaine : $domain · Tâche : $task'),
              const SizedBox(height: 8),
              Text(
                'Métriques réelles : ${metrics.isEmpty ? 'Aucune' : metrics.entries.map((e) => '${e.key}=${e.value}').join(' · ')}',
                style: const TextStyle(fontSize: 12.5),
              ),
              const SizedBox(height: 8),
              Text(
                currentProd != null
                    ? 'Modèle actuellement en production : ${currentProd['model_id']} v${currentProd['version']} (sera remplacé).'
                    : 'Aucun modèle actif actuellement pour cet identifiant.',
                style: TextStyle(
                    fontSize: 12.5,
                    color: currentProd != null
                        ? Colors.orange.shade800
                        : AppColors.muted),
              ),
              const SizedBox(height: 8),
              const Text(
                'Conséquence : cette version deviendra la version active sélectionnée par le registre ML. L’action est enregistrée dans le journal d’audit.',
                style: TextStyle(fontSize: 12, color: AppColors.muted),
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
            child: const Text('Confirmer le déploiement'),
          ),
        ],
      ),
    );

    if (confirmed != true || !mounted) return;
    try {
      await widget.apiService.transitionAdminMlModelStatus(
        widget.adminToken,
        modelId,
        version: version,
        lifecycleStatus: 'DEPLOYED',
        setActive: true,
        enabled: true,
        reason: 'Manual approval via ML Benchmark Studio',
      );
      await widget.onRefreshOverview();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Modèle $modelId v$version déployé.')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Widget _kpiTile(String label, String value, {Color color = AppColors.ink}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.canvas,
        borderRadius: BorderRadius.circular(10),
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
    const sections = [
      (0, 'Vue d’ensemble', Icons.dashboard_outlined),
      (1, 'Expériences', Icons.science_outlined),
      (2, 'Comparaison', Icons.compare_arrows_rounded),
      (3, 'Registre ML', Icons.inventory_2_outlined),
      (4, 'Historique', Icons.history_rounded),
      (5, 'Monitoring IA', Icons.monitor_heart_outlined),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        FDCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      'ML Benchmark Studio & Centre de Contrôle IA',
                      style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink),
                    ),
                  ),
                  if (!widget.canManageModels)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: AppColors.canvas,
                        borderRadius: BorderRadius.circular(99),
                        border: Border.all(color: AppColors.line),
                      ),
                      child: const Text('Lecture seule',
                          style:
                              TextStyle(fontSize: 11, color: AppColors.muted)),
                    ),
                ],
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: sections
                    .map(
                      (s) => ChoiceChip(
                        avatar: Icon(s.$3, size: 16),
                        label: Text(s.$2),
                        selected: _section == s.$1,
                        onSelected: (_) {
                          setState(() => _section = s.$1);
                          if (s.$1 == 4) _loadHistory();
                        },
                      ),
                    )
                    .toList(),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        if (_section == 0) _buildOverviewSection(),
        if (_section == 1) _buildExperimentSection(),
        if (_section == 2) _buildComparisonSection(),
        if (_section == 3) _buildRegistrySection(),
        if (_section == 4) _buildHistorySection(),
        if (_section == 5) _buildMonitoringSection(),
      ],
    );
  }

  // -------------------------------------------------------------------------
  // 0. Studio Overview
  // -------------------------------------------------------------------------
  Widget _buildOverviewSection() {
    final models = _allModels;
    final evalCount =
        models.where((m) => m['lifecycle_status'] == 'EVALUATION').length;
    final deployedCount =
        models.where((m) => m['lifecycle_status'] == 'DEPLOYED').length;
    final failedJobs = _historyJobs
        .where((j) => j['status'] == 'failed' || j['status'] == 'timed_out')
        .length;
    final activeDomains =
        _availableDomains.where((d) => d['active'] != false).length;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        FDCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Indicateurs Opérationnels du Studio',
                  style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.ink)),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _kpiTile('Expériences', '${_historyJobs.length}',
                      color: AppColors.blue),
                  _kpiTile('En évaluation', '$evalCount',
                      color: Colors.orange.shade800),
                  _kpiTile('Déployés', '$deployedCount',
                      color: AppColors.green),
                  _kpiTile('Échecs', '$failedJobs',
                      color:
                          failedJobs == 0 ? AppColors.green : AppColors.danger),
                  _kpiTile('Domaines actifs',
                      '$activeDomains / ${_availableDomains.length}'),
                  _kpiTile(
                      'Persistance ML',
                      (_mlSummary['persistence_backend'] ?? 'local_sqlite')
                          .toString()),
                  _kpiTile(
                    'Cache LRU RAM',
                    '${_mlSummary['loaded_count'] ?? 0} / ${_mlSummary['max_loaded_models'] ?? 4}',
                  ),
                ],
              ),
              if (widget.canManageModels) ...[
                const SizedBox(height: 12),
                FDPrimaryButton(
                  label: 'Nouvelle expérience CSV',
                  icon: Icons.play_arrow_rounded,
                  onPressed: () => setState(() => _section = 1),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 12),
        FDCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Activité récente des benchmarks',
                  style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.ink)),
              const SizedBox(height: 8),
              if (_historyJobs.isEmpty)
                const Text('Aucune expérience exécutée dans cette session.',
                    style: TextStyle(color: AppColors.muted))
              else
                ..._historyJobs.take(5).map((j) => ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                          '${j['dataset_name']} · ${j['domain']} (${j['task_type']})',
                          style: const TextStyle(fontWeight: FontWeight.w600)),
                      subtitle:
                          Text('Job ${j['job_id']} · ${j['created_at'] ?? ''}'),
                      trailing: Text(
                        (j['status'] ?? '').toString().toUpperCase(),
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 11.5,
                          color: widget.statusColor(j['status'] == 'completed'
                              ? 'CONNECTED'
                              : (j['status'] ?? '').toString()),
                        ),
                      ),
                      onTap: () {
                        setState(() {
                          _activeJob = j;
                          _section = 2;
                        });
                      },
                    )),
            ],
          ),
        ),
      ],
    );
  }

  // -------------------------------------------------------------------------
  // 1. Guided 5-Step Experiment Workspace
  // -------------------------------------------------------------------------
  Widget _buildExperimentSection() {
    if (!widget.canManageModels) {
      return const FDCard(
        child: Text(
          'Permission manage_models requise pour lancer un benchmark CSV.',
          style: TextStyle(color: AppColors.muted),
        ),
      );
    }

    final algos = _compatibleAlgorithmsByTask[_selectedTask] ?? const [];
    final warnings = _validateExperimentConfig();
    final domains = _availableDomains;

    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final step in const [
                (0, '1. Dataset'),
                (1, '2. Config'),
                (2, '3. Revue'),
                (3, '4. Exécution'),
                (4, '5. Résultats'),
              ])
                ChoiceChip(
                  label: Text(step.$2),
                  selected: _expStep == step.$1,
                  onSelected: (_) => setState(() => _expStep = step.$1),
                ),
            ],
          ),
          const SizedBox(height: 14),
          if (_expStep == 0) ...[
            const Text('Étape 1 — Jeu de données CSV (platform_public, ≤ 5 Mo)',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5)),
            const SizedBox(height: 6),
            const Text(
              'Seuls les datasets autorisés (platform_public) sont acceptés. Aucun fichier privé utilisateur ne peut entraîner un modèle global.',
              style: TextStyle(fontSize: 12, color: AppColors.muted),
            ),
            const SizedBox(height: 10),
            FDSecondaryButton(
              label: 'Sélectionner un fichier CSV',
              icon: Icons.upload_file_rounded,
              onPressed: _pickCsvFile,
            ),
            if (_csvValidationError != null) ...[
              const SizedBox(height: 8),
              Text(_csvValidationError!,
                  style: const TextStyle(color: AppColors.danger)),
            ],
            if (_pickedCsv != null) ...[
              const SizedBox(height: 10),
              Text(
                'Fichier : ${_pickedCsv!.name} (${(_pickedCsv!.bytes.length / 1024).toStringAsFixed(1)} Ko) · ${_csvHeaders.length} colonnes détectées',
                style: const TextStyle(
                    fontWeight: FontWeight.w600, color: AppColors.green),
              ),
              const SizedBox(height: 10),
              FDPrimaryButton(
                label: 'Continuer vers la configuration',
                icon: Icons.arrow_forward_rounded,
                onPressed: () => setState(() => _expStep = 1),
              ),
            ],
          ],
          if (_expStep == 1) ...[
            const Text('Étape 2 — Configuration de l’expérience',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5)),
            const SizedBox(height: 10),
            TextField(
              controller: _expNameCtrl,
              decoration:
                  const InputDecoration(labelText: 'Nom de l’expérience / CSV'),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _expDescCtrl,
              decoration:
                  const InputDecoration(labelText: 'Description (optionnel)'),
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<String>(
              initialValue:
                  domains.any((d) => d['domain_id'] == _selectedDomain)
                      ? _selectedDomain
                      : (domains.isNotEmpty
                          ? domains.first['domain_id'].toString()
                          : null),
              decoration: const InputDecoration(labelText: 'Domaine IA'),
              items: domains
                  .map((d) => DropdownMenuItem<String>(
                        value: d['domain_id'].toString(),
                        child: Text('${d['label_fr']} (${d['domain_id']})'),
                      ))
                  .toList(),
              onChanged: (v) {
                if (v != null) setState(() => _selectedDomain = v);
              },
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<String>(
              initialValue: _selectedTask,
              decoration: const InputDecoration(labelText: 'Type de tâche ML'),
              items: const [
                DropdownMenuItem(
                    value: 'forecasting',
                    child: Text('Prévision (forecasting)')),
                DropdownMenuItem(
                    value: 'regression',
                    child: Text('Régression (regression)')),
                DropdownMenuItem(
                    value: 'classification',
                    child: Text('Classification binaire (classification)')),
                DropdownMenuItem(
                    value: 'clustering',
                    child: Text('Clustering (clustering)')),
              ],
              onChanged: (v) {
                if (v != null) setState(() => _selectedTask = v);
              },
            ),
            if (_csvHeaders.isNotEmpty) ...[
              if (_selectedTask != 'clustering') ...[
                const SizedBox(height: 10),
                DropdownButtonFormField<String>(
                  initialValue: _csvHeaders.contains(_targetColumn)
                      ? _targetColumn
                      : _csvHeaders.last,
                  decoration:
                      const InputDecoration(labelText: 'Colonne cible (y)'),
                  items: _csvHeaders
                      .map((h) =>
                          DropdownMenuItem<String>(value: h, child: Text(h)))
                      .toList(),
                  onChanged: (v) {
                    setState(() {
                      _targetColumn = v;
                      if (v != null) _featureColumns.remove(v);
                    });
                  },
                ),
              ],
              if (_selectedTask == 'forecasting') ...[
                const SizedBox(height: 10),
                DropdownButtonFormField<String>(
                  initialValue: _csvHeaders.contains(_timeColumn)
                      ? _timeColumn
                      : _csvHeaders.first,
                  decoration: const InputDecoration(
                      labelText: 'Colonne temporelle (tri chronologique)'),
                  items: _csvHeaders
                      .map((h) =>
                          DropdownMenuItem<String>(value: h, child: Text(h)))
                      .toList(),
                  onChanged: (v) => setState(() => _timeColumn = v),
                ),
              ],
              const SizedBox(height: 10),
              const Text('Colonnes explicatives (features) :',
                  style:
                      TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: _csvHeaders
                    .where((h) =>
                        _selectedTask == 'clustering' || h != _targetColumn)
                    .map((h) => FilterChip(
                          label: Text(h),
                          selected: _featureColumns.contains(h),
                          onSelected: (sel) {
                            setState(() {
                              if (sel) {
                                _featureColumns.add(h);
                              } else {
                                _featureColumns.remove(h);
                              }
                            });
                          },
                        ))
                    .toList(),
              ),
            ],
            const SizedBox(height: 10),
            Text(
              'Algorithmes compatibles évalués : ${algos.join(', ')}',
              style: const TextStyle(fontSize: 12, color: AppColors.blue),
            ),
            const SizedBox(height: 12),
            FDPrimaryButton(
              label: 'Passer à la revue',
              icon: Icons.fact_check_outlined,
              onPressed: () => setState(() => _expStep = 2),
            ),
          ],
          if (_expStep == 2) ...[
            const Text('Étape 3 — Revue avant exécution',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5)),
            const SizedBox(height: 8),
            Text(
                'Dataset : ${_pickedCsv?.name ?? 'Aucun'} (portée : platform_public)'),
            Text('Domaine : $_selectedDomain · Tâche : $_selectedTask'),
            if (_selectedTask != 'clustering')
              Text('Colonne cible : ${_targetColumn ?? '—'}'),
            if (_selectedTask == 'forecasting')
              Text('Colonne temporelle : ${_timeColumn ?? '—'}'),
            Text('Features : ${_featureColumns.join(', ')}'),
            Text('Algorithmes : ${algos.join(', ')}'),
            if (warnings.isNotEmpty) ...[
              const SizedBox(height: 8),
              ...warnings.map((w) => Text('• $w',
                  style: const TextStyle(color: AppColors.danger))),
            ],
            const SizedBox(height: 12),
            FDPrimaryButton(
              label: _submitting ? 'Envoi...' : 'Lancer le benchmark',
              icon: Icons.rocket_launch_outlined,
              onPressed: (_submitting || warnings.isNotEmpty)
                  ? null
                  : _launchBenchmark,
            ),
          ],
          if (_expStep == 3) ...[
            const Text('Étape 4 — Exécution en arrière-plan',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5)),
            const SizedBox(height: 10),
            if (_activeJob == null)
              const LinearProgressIndicator()
            else ...[
              Text('Job : ${_activeJob!['job_id'] ?? '—'}'),
              Text(
                'Statut : ${(_activeJob!['status'] ?? 'queued').toString().toUpperCase()} '
                '(${_activeJob!['progress_pct'] ?? 0}%)',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              if (_activeJob!['status'] == 'queued' ||
                  _activeJob!['status'] == 'running') ...[
                const SizedBox(height: 8),
                const LinearProgressIndicator(),
              ],
              if (_activeJob!['error'] != null) ...[
                const SizedBox(height: 8),
                Text(_activeJob!['error'].toString(),
                    style: const TextStyle(color: AppColors.danger)),
              ],
            ],
          ],
          if (_expStep == 4) ...[
            const Text('Étape 5 — Résultats du benchmark',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14.5)),
            const SizedBox(height: 8),
            const Text(
              'Tous les candidats ont été enregistrés dans le Registre ML au statut EVALUATION (aucun déploiement automatique).',
              style: TextStyle(fontSize: 12, color: AppColors.green),
            ),
            const SizedBox(height: 10),
            _buildCandidatesTable(_activeJob),
            const SizedBox(height: 10),
            FDPrimaryButton(
              label: 'Ouvrir dans le Registre ML pour approuver',
              icon: Icons.inventory_2_outlined,
              onPressed: () => setState(() => _section = 3),
            ),
          ],
        ],
      ),
    );
  }

  // -------------------------------------------------------------------------
  // 2. Model Comparison
  // -------------------------------------------------------------------------
  Widget _buildComparisonSection() {
    final job =
        _activeJob ?? (_historyJobs.isNotEmpty ? _historyJobs.first : null);
    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Comparaison des Modèles Candidats',
              style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppColors.ink)),
          const SizedBox(height: 8),
          if (job == null)
            const Text(
              'Sélectionnez une expérience dans l’Historique ou lancez un benchmark pour comparer les algorithmes.',
              style: TextStyle(color: AppColors.muted),
            )
          else ...[
            Text(
              'Expérience : ${job['dataset_name']} · Domaine : ${job['domain']} · Tâche : ${job['task_type']} · Hash : ${(job['dataset_hash'] ?? '').toString().substring(0, ((job['dataset_hash'] ?? '').toString().length).clamp(0, 12))}',
              style: const TextStyle(fontSize: 12, color: AppColors.muted),
            ),
            const SizedBox(height: 10),
            _buildCandidatesTable(job),
          ],
        ],
      ),
    );
  }

  Widget _buildCandidatesTable(Map<String, dynamic>? job) {
    final res = job?['result'];
    final candidates = (res is Map && res['candidates'] is List)
        ? (res['candidates'] as List).cast<Map>()
        : const <Map>[];
    if (candidates.isEmpty) {
      return const Text('Aucun candidat évalué pour cette expérience.',
          style: TextStyle(color: AppColors.muted));
    }
    final task = (job?['task_type'] ?? '').toString();
    final metricCols = switch (task) {
      'classification' => const ['accuracy', 'precision', 'recall', 'f1_score'],
      'clustering' => const ['inertia', 'silhouette_score'],
      _ => const ['mae', 'rmse', 'mape_pct', 'r2'],
    };

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        columns: [
          const DataColumn(label: Text('Algorithme')),
          const DataColumn(label: Text('Statut')),
          ...metricCols.map((c) => DataColumn(label: Text(c.toUpperCase()))),
          const DataColumn(label: Text('Durée (ms)')),
        ],
        rows: candidates.map((c) {
          final m = c['metrics'] is Map ? (c['metrics'] as Map) : const {};
          return DataRow(cells: [
            DataCell(Text('${c['algorithm']} (v${c['version']})')),
            DataCell(Text((c['lifecycle_status'] ?? 'EVALUATION').toString())),
            ...metricCols.map((k) => DataCell(Text(m[k]?.toString() ?? '—'))),
            DataCell(Text('${c['duration_ms'] ?? '—'}')),
          ]);
        }).toList(),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // 3. Model Management Workspace (Human Approval)
  // -------------------------------------------------------------------------
  Widget _buildRegistrySection() {
    final models = _allModels.where((m) {
      if (_registryDomainFilter != 'all' &&
          m['domain'] != _registryDomainFilter) {
        return false;
      }
      if (_registryTaskFilter != 'all' &&
          m['task_type'] != _registryTaskFilter) {
        return false;
      }
      if (_registryStatusFilter != 'all' &&
          m['lifecycle_status'] != _registryStatusFilter) {
        return false;
      }
      return true;
    }).toList();

    final domains = _allModels
        .map((m) => (m['domain'] ?? '').toString())
        .where((s) => s.isNotEmpty)
        .toSet()
        .toList()
      ..sort();

    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Registre ML & Approbation Humaine',
              style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppColors.ink)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              DropdownButton<String>(
                value: _registryDomainFilter,
                items: [
                  const DropdownMenuItem(
                      value: 'all', child: Text('Tous domaines')),
                  ...domains
                      .map((d) => DropdownMenuItem(value: d, child: Text(d))),
                ],
                onChanged: (v) =>
                    setState(() => _registryDomainFilter = v ?? 'all'),
              ),
              DropdownButton<String>(
                value: _registryTaskFilter,
                items: const [
                  DropdownMenuItem(value: 'all', child: Text('Toutes tâches')),
                  DropdownMenuItem(
                      value: 'forecasting', child: Text('forecasting')),
                  DropdownMenuItem(
                      value: 'regression', child: Text('regression')),
                  DropdownMenuItem(
                      value: 'classification', child: Text('classification')),
                  DropdownMenuItem(
                      value: 'clustering', child: Text('clustering')),
                ],
                onChanged: (v) =>
                    setState(() => _registryTaskFilter = v ?? 'all'),
              ),
              DropdownButton<String>(
                value: _registryStatusFilter,
                items: const [
                  DropdownMenuItem(value: 'all', child: Text('Tous statuts')),
                  DropdownMenuItem(
                      value: 'REGISTERED', child: Text('REGISTERED')),
                  DropdownMenuItem(
                      value: 'EVALUATION', child: Text('EVALUATION')),
                  DropdownMenuItem(value: 'APPROVED', child: Text('APPROVED')),
                  DropdownMenuItem(value: 'DEPLOYED', child: Text('DEPLOYED')),
                  DropdownMenuItem(
                      value: 'DEPRECATED', child: Text('DEPRECATED')),
                  DropdownMenuItem(value: 'FAILED', child: Text('FAILED')),
                ],
                onChanged: (v) =>
                    setState(() => _registryStatusFilter = v ?? 'all'),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (models.isEmpty)
            const Text('Aucun modèle correspondant aux filtres.',
                style: TextStyle(color: AppColors.muted))
          else
            ...models.map((m) {
              final modelId = (m['model_id'] ?? m['name'] ?? '').toString();
              final ver = (m['version'] is int)
                  ? m['version'] as int
                  : int.tryParse('${m['version']}') ?? 1;
              final status = (m['lifecycle_status'] ?? 'REGISTERED').toString();
              final isActiveProd = m['is_active_production'] == true;
              final metrics = m['evaluation_metrics'] is Map
                  ? (m['evaluation_metrics'] as Map)
                  : const {};
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AppColors.canvas,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.line),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              '$modelId v$ver · ${m['algorithm'] ?? '—'}',
                              style:
                                  const TextStyle(fontWeight: FontWeight.w700),
                            ),
                          ),
                          Text(
                            isActiveProd ? '$status · ACTIF PROD' : status,
                            style: TextStyle(
                              fontSize: 11.5,
                              fontWeight: FontWeight.w700,
                              color: widget.statusColor(
                                  status == 'DEPLOYED' ? 'CONNECTED' : status),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Domaine: ${m['domain'] ?? '—'} · Tâche: ${m['task_type'] ?? '—'} · Dataset: ${m['training_dataset_ref'] ?? '—'}',
                        style: const TextStyle(
                            fontSize: 12, color: AppColors.muted),
                      ),
                      if (metrics.isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(
                          metrics.entries
                              .take(6)
                              .map((e) => '${e.key}: ${e.value}')
                              .join(' · '),
                          style: const TextStyle(
                              fontSize: 11.5,
                              fontWeight: FontWeight.w600,
                              color: AppColors.blue),
                        ),
                      ],
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        runSpacing: 6,
                        children: [
                          OutlinedButton(
                            onPressed: () => widget.onCompareModel(modelId),
                            child: const Text('Comparer'),
                          ),
                          if (widget.canManageModels && !isActiveProd)
                            ElevatedButton(
                              onPressed: () => _confirmAndDeployModel(m),
                              child: const Text('Approuver & Déployer'),
                            ),
                          if (widget.canManageModels && ver > 1)
                            OutlinedButton(
                              onPressed: () async {
                                await widget.apiService.rollbackAdminMlModel(
                                  widget.adminToken,
                                  modelId,
                                  targetVersion: ver - 1,
                                );
                                await widget.onRefreshOverview();
                              },
                              child: Text('Rollback → v${ver - 1}'),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              );
            }),
        ],
      ),
    );
  }

  // -------------------------------------------------------------------------
  // 4. Experiment History
  // -------------------------------------------------------------------------
  Widget _buildHistorySection() {
    final q = _historySearchCtrl.text.trim().toLowerCase();
    final filtered = _historyJobs.where((j) {
      if (_historyDomainFilter != 'all' &&
          j['domain'] != _historyDomainFilter) {
        return false;
      }
      if (_historyTaskFilter != 'all' && j['task_type'] != _historyTaskFilter) {
        return false;
      }
      if (_historyStatusFilter != 'all' &&
          j['status'] != _historyStatusFilter) {
        return false;
      }
      if (q.isNotEmpty) {
        final hay =
            '${j['job_id']} ${j['dataset_name']} ${j['domain']} ${j['task_type']}'
                .toLowerCase();
        if (!hay.contains(q)) return false;
      }
      return true;
    }).toList();

    filtered.sort((a, b) {
      final ca = (a['created_at'] ?? '').toString();
      final cb = (b['created_at'] ?? '').toString();
      return _historySortNewestFirst ? cb.compareTo(ca) : ca.compareTo(cb);
    });

    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text('Historique des Expériences',
                    style: TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ink)),
              ),
              IconButton(
                tooltip: 'Rafraîchir',
                icon: const Icon(Icons.refresh_rounded),
                onPressed: _loadHistory,
              ),
            ],
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _historySearchCtrl,
            decoration: const InputDecoration(
              labelText: 'Rechercher par dataset, job ID ou domaine',
              prefixIcon: Icon(Icons.search_rounded),
            ),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              DropdownButton<String>(
                value: _historyStatusFilter,
                items: const [
                  DropdownMenuItem(value: 'all', child: Text('Tous statuts')),
                  DropdownMenuItem(
                      value: 'completed', child: Text('completed')),
                  DropdownMenuItem(value: 'running', child: Text('running')),
                  DropdownMenuItem(value: 'failed', child: Text('failed')),
                  DropdownMenuItem(
                      value: 'timed_out', child: Text('timed_out')),
                ],
                onChanged: (v) =>
                    setState(() => _historyStatusFilter = v ?? 'all'),
              ),
              TextButton.icon(
                icon: Icon(_historySortNewestFirst
                    ? Icons.arrow_downward_rounded
                    : Icons.arrow_upward_rounded),
                label: Text(
                    _historySortNewestFirst ? 'Plus récents' : 'Plus anciens'),
                onPressed: () => setState(
                    () => _historySortNewestFirst = !_historySortNewestFirst),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (_loadingHistory)
            const Center(child: CircularProgressIndicator())
          else if (_historyError != null)
            Text(_historyError!,
                style: const TextStyle(color: AppColors.danger))
          else if (filtered.isEmpty)
            const Text('Aucune expérience trouvée.',
                style: TextStyle(color: AppColors.muted))
          else
            ...filtered.map((j) => ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(
                      '${j['dataset_name']} · ${j['domain']} (${j['task_type']})',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  subtitle: Text(
                      '${j['job_id']} · ${j['created_at'] ?? ''} · hash ${(j['dataset_hash'] ?? '').toString().substring(0, ((j['dataset_hash'] ?? '').toString().length).clamp(0, 10))}'),
                  trailing: Text(
                    (j['status'] ?? '').toString().toUpperCase(),
                    style: const TextStyle(
                        fontWeight: FontWeight.w700, fontSize: 11.5),
                  ),
                  onTap: () => setState(() {
                    _activeJob = j;
                    _section = 2;
                  }),
                )),
        ],
      ),
    );
  }

  // -------------------------------------------------------------------------
  // 5. AI Monitoring (Domains & Infrastructure)
  // -------------------------------------------------------------------------
  Widget _buildMonitoringSection() {
    final infra = widget.overview['ai_infrastructure'] is Map
        ? (widget.overview['ai_infrastructure'] as Map)
        : const {};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        FDCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Infrastructure IA',
                  style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.ink)),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: infra.entries
                    .map((e) => _kpiTile(
                          e.key.toString(),
                          e.value.toString(),
                          color: widget.statusColor(e.value.toString()),
                        ))
                    .toList(),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        FDCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Gestion des Domaines IA (${_availableDomains.length})',
                style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: AppColors.ink),
              ),
              const SizedBox(height: 8),
              ..._availableDomains.map((d) {
                final domId = (d['domain_id'] ?? '').toString();
                final active = d['active'] != false;
                return SwitchListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text('${d['label_fr'] ?? domId} ($domId)',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  subtitle: Text(
                      'Tier: ${d['required_tier'] ?? 'free'} · Usages: ${d['usage_count'] ?? 0}'),
                  value: active,
                  onChanged: widget.canManageModels
                      ? (val) async {
                          await widget.apiService.setAdminDomainStatus(
                              widget.adminToken, domId, val);
                          await widget.onRefreshOverview();
                        }
                      : null,
                );
              }),
            ],
          ),
        ),
      ],
    );
  }
}
