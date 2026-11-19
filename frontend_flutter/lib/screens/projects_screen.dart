import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/formatters.dart';
import '../core/utils/pdf_download.dart';
import '../services/api_service.dart';

class ProjectsScreen extends StatefulWidget {
  final ApiService apiService;
  final void Function(Map<String, dynamic> project)? onResumeProject;

  const ProjectsScreen({
    super.key,
    required this.apiService,
    this.onResumeProject,
  });

  @override
  State<ProjectsScreen> createState() => _ProjectsScreenState();
}

class _ProjectsScreenState extends State<ProjectsScreen> {
  List<Map<String, dynamic>> _projects = [];
  List<String> _commodities = const ['Millet', 'Sorghum (red)', 'Maize (white)', 'Rice (imported)'];
  List<String> _provinces = const ['Lac', "N'Djamena", 'Salamat', 'Logone Occidental', 'Ouaddai'];
  bool _loading = true;
  bool _includeArchived = false;
  String? _error;

  String _loadedUserId = '';

  @override
  void initState() {
    super.initState();
    _loadMetadata();
    _load();
  }

  @override
  void didUpdateWidget(covariant ProjectsScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    // L'identifiant d'espace a changé (Réglages) : la liste affichée appartient à l'ancien espace.
    if (_loadedUserId != widget.apiService.userId && !_loading) {
      _load();
    }
  }

  /// Exécute une action réseau et affiche l'erreur au lieu de l'avaler en silence.
  Future<void> _guard(Future<void> Function() action) async {
    try {
      await action();
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString().replaceFirst('Exception: ', '');
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Action impossible : $msg')));
    }
  }

  /// Accepte « 2 000 000 », « 2,000,000 », « 2000000 » ; null si illisible ou ≤ 0.
  double? _parseCapital(String raw) {
    final cleaned = raw.replaceAll(RegExp(r'[\s\u00A0\u202F,]'), '');
    final v = double.tryParse(cleaned);
    return (v == null || v <= 0) ? null : v;
  }

  Future<void> _loadMetadata() async {
    try {
      final meta = await widget.apiService.getMetadata();
      final legacy = meta['legacy'];
      final rawComms = meta['products'] ??
          meta['commodities'] ??
          meta['passport_products'] ??
          (legacy is Map ? (legacy['products'] ?? legacy['commodities']) : null) ??
          const [];
      final rawProvs = meta['provinces'] ?? (legacy is Map ? legacy['provinces'] : null) ?? const [];
      final comms = rawComms is List
          ? rawComms.map((e) => e.toString().trim()).where((s) => s.isNotEmpty).toSet().toList()
          : <String>[];
      final provs = rawProvs is List
          ? rawProvs.map((e) => e.toString().trim()).where((s) => s.isNotEmpty).toSet().toList()
          : <String>[];
      comms.sort((a, b) => commodityLabelFr(a).compareTo(commodityLabelFr(b)));
      provs.sort();
      if (!mounted) return;
      setState(() {
        if (comms.isNotEmpty) _commodities = comms;
        if (provs.isNotEmpty) _provinces = provs;
      });
    } catch (_) {}
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final uid = widget.apiService.userId;
    try {
      final list = await widget.apiService.listProjects(includeArchived: _includeArchived);
      if (!mounted || uid != widget.apiService.userId) return;
      setState(() {
        _projects = list;
        _loadedUserId = uid;
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

  Future<void> _createProjectDialog() async {
    final nameCtrl = TextEditingController();
    final descCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Nouveau Projet'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(controller: nameCtrl, decoration: const InputDecoration(labelText: 'Nom du projet')),
            const SizedBox(height: 8),
            TextField(controller: descCtrl, decoration: const InputDecoration(labelText: 'Description / Objectif')),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Annuler')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Créer')),
        ],
      ),
    );
    if (ok == true && nameCtrl.text.trim().length >= 2) {
      await _guard(() async {
        await widget.apiService.createProject(name: nameCtrl.text.trim(), description: descCtrl.text.trim());
        await _load();
      });
    }
  }

  Future<void> _renameProject(Map<String, dynamic> proj) async {
    final ctrl = TextEditingController(text: proj['name']?.toString() ?? '');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Renommer le projet'),
        content: TextField(controller: ctrl, decoration: const InputDecoration(labelText: 'Nouveau nom')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Annuler')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Enregistrer')),
        ],
      ),
    );
    if (ok == true && ctrl.text.trim().length >= 2) {
      await _guard(() async {
        await widget.apiService.updateProject(proj['project_id'].toString(), name: ctrl.text.trim());
        await _load();
      });
    }
  }

  Future<void> _confirmDelete(Map<String, dynamic> proj) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Supprimer le projet ?'),
        content: Text('Cette action est irréversible pour « ${proj['name']} » et ses versions d’études.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Annuler')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: FDTheme.danger, foregroundColor: Colors.white),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Supprimer'),
          ),
        ],
      ),
    );
    if (ok == true) {
      await _guard(() async {
        await widget.apiService.deleteProject(proj['project_id'].toString());
        await _load();
      });
    }
  }

  Future<void> _generateStudyDialog(Map<String, dynamic> proj) async {
    String commodity = _commodities.contains('Millet') ? 'Millet' : _commodities.first;
    String origin = _provinces.contains('Lac') ? 'Lac' : _provinces.first;
    String dest = _provinces.contains("N'Djamena") ? "N'Djamena" : _provinces.first;
    final capCtrl = TextEditingController(text: '2000000');
    // Études déjà présentes : permet de créer une NOUVELLE VERSION (historique + comparaison).
    List<Map<String, dynamic>> existing = const [];
    try {
      final full = await widget.apiService.getProject(proj['project_id'].toString());
      existing = (full['studies'] as List? ?? []).whereType<Map>().map((m) => Map<String, dynamic>.from(m)).toList();
    } catch (_) {}
    if (!mounted) return;
    String? targetStudyId; // null = nouvelle étude
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Nouvelle étude PDF — ${proj['name']}'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (existing.isNotEmpty) ...[
              DropdownButtonFormField<String?>(
                initialValue: null,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Étude cible'),
                items: [
                  const DropdownMenuItem<String?>(value: null, child: Text('Nouvelle étude')),
                  ...existing.map((st) => DropdownMenuItem<String?>(
                        value: st['study_id'].toString(),
                        child: Text(
                          'Nouvelle version de : ${st['title'] ?? st['study_id']}',
                          overflow: TextOverflow.ellipsis,
                        ),
                      )),
                ],
                onChanged: (v) => targetStudyId = v,
              ),
              const SizedBox(height: 8),
            ],
            DropdownButtonFormField<String>(
              initialValue: commodity,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Produit / Céréale'),
              items: _commodities
                  .map((c) => DropdownMenuItem(
                        value: c,
                        child: Text(commodityLabelFr(c), overflow: TextOverflow.ellipsis),
                      ))
                  .toList(),
              onChanged: (v) => commodity = v ?? commodity,
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              initialValue: origin,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Province d\'origine'),
              items: _provinces
                  .map((p) => DropdownMenuItem(value: p, child: Text(p, overflow: TextOverflow.ellipsis)))
                  .toList(),
              onChanged: (v) => origin = v ?? origin,
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              initialValue: dest,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Province de destination'),
              items: _provinces
                  .map((p) => DropdownMenuItem(value: p, child: Text(p, overflow: TextOverflow.ellipsis)))
                  .toList(),
              onChanged: (v) => dest = v ?? dest,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: capCtrl,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Capital (XAF)'),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Annuler')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Générer & Sauvegarder')),
        ],
      ),
    );
    if (ok != true) return;
    final cap = _parseCapital(capCtrl.text);
    if (cap == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Capital invalide : saisissez un nombre positif (ex. 2 000 000).')),
      );
      return;
    }
    try {
      final created = await widget.apiService.createProjectStudy(
        proj['project_id'].toString(),
        studyId: targetStudyId,
        commodity: commodity,
        originProvince: origin.trim().isEmpty ? 'Lac' : origin.trim(),
        destProvince: dest.trim(),
        capitalXaf: cap,
      );
      await _load();
      if (!mounted) return;
      final studyId = created['study_id']?.toString() ?? '';
      final vNum = (created['version_number'] as num?)?.toInt() ?? 1;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Étude enregistrée dans le projet (v$vNum).')),
      );
      if (studyId.isNotEmpty) {
        final bytes = await widget.apiService.downloadStudyVersionPdf(
          proj['project_id'].toString(),
          studyId,
          vNum,
        );
        triggerPdfDownload(bytes, 'freedata_${studyId}_v$vNum.pdf');
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _openStudiesAndVersions(Map<String, dynamic> proj) async {
    Map<String, dynamic> full;
    try {
      full = await widget.apiService.getProject(proj['project_id'].toString());
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ouverture impossible : $e')));
      return;
    }
    if (!mounted) return;
    final studies = (full['studies'] as List? ?? []).whereType<Map>().map((m) => Map<String, dynamic>.from(m)).toList();
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Études & Versions — ${full['name']}', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            if (studies.isEmpty)
              const Text('Aucune étude générée pour ce projet.')
            else
              ...studies.map((s) => ListTile(
                    title: Text(s['title']?.toString() ?? s['study_id'].toString()),
                    subtitle: Text('Dernière version : v${s['latest_version']} · Maj : ${s['updated_at']}'),
                    trailing: TextButton(
                      onPressed: () => _guard(() async {
                        final versions = await widget.apiService.listStudyVersions(
                          full['project_id'].toString(),
                          s['study_id'].toString(),
                        );
                        if (!ctx.mounted) return;
                        _showVersionHistoryDialog(full['project_id'].toString(), s['study_id'].toString(), versions);
                      }),
                      child: const Text('Historique'),
                    ),
                  )),
          ],
        ),
      ),
    );
  }

  /// Rend la différence de métriques lisible (une ligne par métrique) au lieu d'un Map brut.
  String _formatDiff(dynamic raw) {
    if (raw is! Map || raw.isEmpty) return 'Aucune différence de métrique détectée.';
    final lines = <String>[];
    raw.forEach((k, v) {
      if (v is Map) {
        final before = v['from'] ?? v['old'] ?? v['before'] ?? v['a'];
        final after = v['to'] ?? v['new'] ?? v['after'] ?? v['b'];
        if (before != null || after != null) {
          lines.add('• $k : ${before ?? '—'} → ${after ?? '—'}');
        } else {
          lines.add('• $k : ${v.entries.map((e) => '${e.key}=${e.value}').join(', ')}');
        }
      } else {
        lines.add('• $k : $v');
      }
    });
    return lines.join('\n');
  }

  void _showVersionHistoryDialog(String projectId, String studyId, List<Map<String, dynamic>> versions) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Versions — $studyId'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ...versions.map((v) {
                final vNum = (v['version_number'] as num).toInt();
                final qaStatus = (v['validation'] as Map?)?['overall_status'] ?? '—';
                final avail = v['artifact_available'] == true;
                return ListTile(
                  dense: true,
                  title: Text('Version $vNum · QA: $qaStatus'),
                  subtitle: Text(v['created_at']?.toString() ?? ''),
                  trailing: avail
                      ? IconButton(
                          icon: const Icon(Icons.picture_as_pdf_rounded, color: FDTheme.blue),
                          onPressed: () => _guard(() async {
                            final bytes = await widget.apiService.downloadStudyVersionPdf(projectId, studyId, vNum);
                            triggerPdfDownload(bytes, 'freedata_${studyId}_v$vNum.pdf');
                          }),
                        )
                      : const Text('PDF absent', style: TextStyle(fontSize: 11, color: FDTheme.muted)),
                );
              }),
              if (versions.length >= 2) ...[
                const Divider(),
                TextButton.icon(
                  icon: const Icon(Icons.compare_arrows_rounded),
                  label: Text('Comparer v${versions[1]['version_number']} et v${versions[0]['version_number']}'),
                  onPressed: () => _guard(() async {
                    final diff = await widget.apiService.compareStudyVersions(
                      projectId,
                      studyId,
                      (versions[1]['version_number'] as num).toInt(),
                      (versions[0]['version_number'] as num).toInt(),
                    );
                    if (!ctx.mounted) return;
                    showDialog(
                      context: ctx,
                      builder: (c2) => AlertDialog(
                        title: const Text('Comparaison de versions'),
                        content: SingleChildScrollView(child: Text(_formatDiff(diff['metrics_diff']))),
                        actions: [TextButton(onPressed: () => Navigator.pop(c2), child: const Text('Fermer'))],
                      ),
                    );
                  }),
                ),
              ],
            ],
          ),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Fermer'))],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // Pas d'AppBar ici : MainShell affiche déjà le titre (sinon deux barres empilées).
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: Row(
              children: [
                FilterChip(
                  label: const Text('Archivés'),
                  selected: _includeArchived,
                  onSelected: (v) {
                    setState(() => _includeArchived = v);
                    _load();
                  },
                ),
                const Spacer(),
                TextButton.icon(
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('Nouveau projet'),
                  onPressed: _createProjectDialog,
                ),
              ],
            ),
          ),
          Expanded(child: _buildBody()),
        ],
      ),
    );
  }

  Widget _buildBody() {
    return _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Padding(padding: const EdgeInsets.all(16), child: Text(_error!, style: const TextStyle(color: FDTheme.danger))))
              : _projects.isEmpty
                  ? const Center(child: Text('Aucun projet enregistré. Créez-en un avec « Nouveau projet ».'))
                  : ListView.separated(
                      padding: const EdgeInsets.all(16),
                      itemCount: _projects.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 10),
                      itemBuilder: (_, i) {
                        final p = _projects[i];
                        final isArchived = p['status'] == 'archived';
                        return FDCard(
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                          child: Column(children: [ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text(p['name']?.toString() ?? 'Projet', style: const TextStyle(fontWeight: FontWeight.w700, color: AppColors.ink)),
                            subtitle: Text(
                              'Statut : ${isArchived ? 'Archivé' : 'Actif'} · Études : ${p['studies_count'] ?? 0} · Maj : ${p['updated_at']}',
                              style: const TextStyle(fontSize: 12.5, color: AppColors.muted),
                            ),
                            trailing: PopupMenuButton<String>(
                              onSelected: (act) => _guard(() async {
                                if (act == 'rename') await _renameProject(p);
                                if (act == 'archive') {
                                  await widget.apiService.updateProject(
                                    p['project_id'].toString(),
                                    status: isArchived ? 'active' : 'archived',
                                  );
                                  await _load();
                                }
                                if (act == 'delete') await _confirmDelete(p);
                              }),
                              itemBuilder: (_) => [
                                const PopupMenuItem(value: 'rename', child: Text('Renommer')),
                                PopupMenuItem(value: 'archive', child: Text(isArchived ? 'Restaurer' : 'Archiver')),
                                const PopupMenuItem(value: 'delete', child: Text('Supprimer')),
                              ],
                            ),
                          ),
                          const SizedBox(height: 4),
                          Wrap(
                            spacing: 4,
                            runSpacing: 0,
                            children: [
                              TextButton.icon(
                                icon: const Icon(Icons.picture_as_pdf_outlined, color: FDTheme.green, size: 18),
                                label: const Text('Étude PDF'),
                                onPressed: () => _guard(() => _generateStudyDialog(p)),
                              ),
                              TextButton.icon(
                                icon: const Icon(Icons.play_arrow_rounded, color: FDTheme.blue, size: 18),
                                label: const Text('Reprendre'),
                                onPressed: () => _guard(() async {
                                  final full = await widget.apiService.getProject(p['project_id'].toString());
                                  widget.onResumeProject?.call(full);
                                }),
                              ),
                              TextButton.icon(
                                icon: const Icon(Icons.history_rounded, size: 18),
                                label: const Text('Versions'),
                                onPressed: () => _openStudiesAndVersions(p),
                              ),
                            ],
                          ),
                          ],
                          ),
                        );
                      },
                    );
  }
}

