import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
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
  bool _loading = true;
  bool _includeArchived = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final list = await widget.apiService.listProjects(includeArchived: _includeArchived);
      if (!mounted) return;
      setState(() {
        _projects = list;
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
      await widget.apiService.createProject(name: nameCtrl.text.trim(), description: descCtrl.text.trim());
      _load();
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
      await widget.apiService.updateProject(proj['project_id'].toString(), name: ctrl.text.trim());
      _load();
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
      await widget.apiService.deleteProject(proj['project_id'].toString());
      _load();
    }
  }

  Future<void> _openStudiesAndVersions(Map<String, dynamic> proj) async {
    final full = await widget.apiService.getProject(proj['project_id'].toString());
    if (!mounted) return;
    final studies = (full['studies'] as List? ?? []).cast<Map<String, dynamic>>();
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
                      onPressed: () async {
                        final versions = await widget.apiService.listStudyVersions(
                          full['project_id'].toString(),
                          s['study_id'].toString(),
                        );
                        if (!ctx.mounted) return;
                        _showVersionHistoryDialog(full['project_id'].toString(), s['study_id'].toString(), versions);
                      },
                      child: const Text('Historique'),
                    ),
                  )),
          ],
        ),
      ),
    );
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
                final vNum = v['version_number'] as int;
                final qaStatus = (v['validation'] as Map?)?['overall_status'] ?? '—';
                final avail = v['artifact_available'] == true;
                return ListTile(
                  dense: true,
                  title: Text('Version $vNum · QA: $qaStatus'),
                  subtitle: Text(v['created_at']?.toString() ?? ''),
                  trailing: avail
                      ? IconButton(
                          icon: const Icon(Icons.picture_as_pdf_rounded, color: FDTheme.blue),
                          onPressed: () async {
                            final bytes = await widget.apiService.downloadStudyVersionPdf(projectId, studyId, vNum);
                            triggerPdfDownload(bytes, 'freedata_${studyId}_v$vNum.pdf');
                          },
                        )
                      : const Text('PDF absent', style: TextStyle(fontSize: 11, color: FDTheme.muted)),
                );
              }),
              if (versions.length >= 2) ...[
                const Divider(),
                TextButton.icon(
                  icon: const Icon(Icons.compare_arrows_rounded),
                  label: Text('Comparer v${versions[1]['version_number']} et v${versions[0]['version_number']}'),
                  onPressed: () async {
                    final diff = await widget.apiService.compareStudyVersions(
                      projectId,
                      studyId,
                      versions[1]['version_number'] as int,
                      versions[0]['version_number'] as int,
                    );
                    if (!ctx.mounted) return;
                    showDialog(
                      context: ctx,
                      builder: (c2) => AlertDialog(
                        title: const Text('Comparaison de versions'),
                        content: Text(diff['metrics_diff'].toString()),
                        actions: [TextButton(onPressed: () => Navigator.pop(c2), child: const Text('Fermer'))],
                      ),
                    );
                  },
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
    return Scaffold(
      appBar: AppBar(
        title: const Text('Espace Projets'),
        actions: [
          FilterChip(
            label: const Text('Archivés'),
            selected: _includeArchived,
            onSelected: (v) {
              setState(() => _includeArchived = v);
              _load();
            },
          ),
          const SizedBox(width: 8),
          IconButton(icon: const Icon(Icons.add_rounded), tooltip: 'Nouveau projet', onPressed: _createProjectDialog),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!, style: const TextStyle(color: FDTheme.danger)))
              : _projects.isEmpty
                  ? const Center(child: Text('Aucun projet enregistré. Créez-en un avec le bouton +.'))
                  : ListView.separated(
                      padding: const EdgeInsets.all(16),
                      itemCount: _projects.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 10),
                      itemBuilder: (_, i) {
                        final p = _projects[i];
                        final isArchived = p['status'] == 'archived';
                        return Card(
                          child: ListTile(
                            title: Text(p['name']?.toString() ?? 'Projet', style: const TextStyle(fontWeight: FontWeight.w600)),
                            subtitle: Text(
                              'Statut : ${isArchived ? 'Archivé' : 'Actif'} · Études : ${p['studies_count'] ?? 0} · Maj : ${p['updated_at']}',
                            ),
                            trailing: Wrap(
                              spacing: 4,
                              children: [
                                IconButton(
                                  icon: const Icon(Icons.play_arrow_rounded, color: FDTheme.blue),
                                  tooltip: 'Reprendre',
                                  onPressed: () async {
                                    final full = await widget.apiService.getProject(p['project_id'].toString());
                                    widget.onResumeProject?.call(full);
                                  },
                                ),
                                IconButton(
                                  icon: const Icon(Icons.history_rounded),
                                  tooltip: 'Études & Versions',
                                  onPressed: () => _openStudiesAndVersions(p),
                                ),
                                PopupMenuButton<String>(
                                  onSelected: (act) async {
                                    if (act == 'rename') await _renameProject(p);
                                    if (act == 'archive') {
                                      await widget.apiService.updateProject(
                                        p['project_id'].toString(),
                                        status: isArchived ? 'active' : 'archived',
                                      );
                                      _load();
                                    }
                                    if (act == 'delete') await _confirmDelete(p);
                                  },
                                  itemBuilder: (_) => [
                                    const PopupMenuItem(value: 'rename', child: Text('Renommer')),
                                    PopupMenuItem(value: 'archive', child: Text(isArchived ? 'Restaurer' : 'Archiver')),
                                    const PopupMenuItem(value: 'delete', child: Text('Supprimer')),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
    );
  }
}

