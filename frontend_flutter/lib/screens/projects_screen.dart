import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/file_picker.dart';
import '../core/utils/formatters.dart';
import '../core/utils/pdf_download.dart';
import '../services/api_service.dart';
import '../services/conversation_storage.dart';
import '../widgets/auth_dialog.dart';
import 'campaign_plan_screen.dart';
import 'farm_operating_account_screen.dart';

class ProjectsScreen extends StatefulWidget {
  final ApiService apiService;
  final void Function(Map<String, dynamic> project)? onResumeProject;
  final void Function(
    Map<String, dynamic> project, {
    String? conversationId,
    String? initialPrompt,
    bool forceNewConversation,
  })? onOpenProjectChat;
  final int refreshToken;
  final List<ConversationThread>? conversations;

  const ProjectsScreen({
    super.key,
    required this.apiService,
    this.onResumeProject,
    this.onOpenProjectChat,
    this.refreshToken = 0,
    this.conversations,
  });

  @override
  State<ProjectsScreen> createState() => _ProjectsScreenState();
}

class _ProjectsScreenState extends State<ProjectsScreen> {
  List<Map<String, dynamic>> _projects = [];
  List<String> _commodities = const [
    'Millet',
    'Sorghum (red)',
    'Maize (white)',
    'Rice (imported)'
  ];
  List<String> _provinces = const [
    'Lac',
    "N'Djamena",
    'Salamat',
    'Logone Occidental',
    'Ouaddai'
  ];
  bool _loading = true;
  bool _includeArchived = false;
  String? _error;

  String _loadedUserId = '';
  Map<String, dynamic>? _selectedProject;
  List<ConversationThread> _projectConversations = [];
  List<Map<String, dynamic>> _projectDocuments = [];
  List<Map<String, dynamic>> _projectAgroAssessments = [];
  bool _uploadingDoc = false;
  bool _loadingWorkspace = false;
  final TextEditingController _workspacePromptCtrl = TextEditingController();
  final TextEditingController _searchCtrl = TextEditingController();
  String _searchQuery = '';

  @override
  void dispose() {
    _workspacePromptCtrl.dispose();
    _searchCtrl.dispose();
    super.dispose();
  }

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
    if (oldWidget.refreshToken != widget.refreshToken ||
        oldWidget.conversations != widget.conversations) {
      if (_selectedProject != null) {
        _openWorkspace(_selectedProject!, silent: true);
      } else if (oldWidget.refreshToken != widget.refreshToken) {
        _load();
      }
    }
  }

  /// Exécute une action réseau et affiche l'erreur au lieu de l'avaler en silence.
  Future<void> _guard(Future<void> Function() action) async {
    try {
      await action();
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString().replaceFirst('Exception: ', '');
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Action impossible : $msg')));
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
      final legacy = meta['legacy_fields'] ?? meta['legacy'];
      final rawComms = meta['products'] ??
          meta['commodities'] ??
          meta['passport_products'] ??
          (legacy is Map
              ? (legacy['products'] ?? legacy['commodities'])
              : null) ??
          const [];
      final rawProvs = meta['provinces'] ??
          (legacy is Map ? legacy['provinces'] : null) ??
          const [];
      final comms = rawComms is List
          ? rawComms
              .map((e) => e.toString().trim())
              .where((s) => s.isNotEmpty)
              .toSet()
              .toList()
          : <String>[];
      final provs = rawProvs is List
          ? rawProvs
              .map((e) => e.toString().trim())
              .where((s) => s.isNotEmpty)
              .toSet()
              .toList()
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

  bool get _canAccessProjects =>
      widget.apiService.isAuthenticated ||
      widget.apiService.hasExplicitPremiumKey;

  Future<void> _openAuth({bool register = false}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AuthDialog(
        apiService: widget.apiService,
        initialRegisterMode: register,
      ),
    );
    if (ok == true && mounted) {
      await _load();
    }
  }

  Future<void> _load() async {
    if (!_canAccessProjects) {
      if (!mounted) return;
      setState(() {
        _projects = [];
        _loading = false;
        _error = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    final uid = widget.apiService.userId;
    try {
      final list = await widget.apiService
          .listProjects(includeArchived: _includeArchived);
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

  Future<void> _openWorkspace(Map<String, dynamic> projSummary,
      {bool silent = false}) async {
    final pid = projSummary['project_id']?.toString() ?? '';
    if (pid.isEmpty) return;
    if (!silent) {
      setState(() {
        _loadingWorkspace = true;
        _selectedProject = Map<String, dynamic>.from(projSummary);
      });
    }
    try {
      final results = await Future.wait([
        widget.apiService.getProject(pid),
        LocalConversationStorage.instance.listProjectConversations(pid),
        widget.apiService
            .listUserDocuments(projectId: pid)
            .catchError((_) => <Map<String, dynamic>>[]),
        widget.apiService
            .listAgroFieldAssessments(projectId: pid)
            .catchError((_) => <Map<String, dynamic>>[]),
      ]);
      if (!mounted) return;
      final liveConvs = widget.conversations != null
          ? widget.conversations!.where((c) => c.projectId == pid).toList()
          : (results[1] as List<ConversationThread>);
      setState(() {
        _selectedProject = results[0] as Map<String, dynamic>;
        _projectConversations = liveConvs;
        _projectDocuments = results[2] as List<Map<String, dynamic>>;
        _projectAgroAssessments = results[3] as List<Map<String, dynamic>>;
        _loadingWorkspace = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loadingWorkspace = false);
      if (!silent) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Ouverture impossible : $e')));
      }
    }
  }

  Future<void> _createProjectDialog() async {
    final nameCtrl = TextEditingController();
    final descCtrl = TextEditingController();
    final capCtrl = TextEditingController();
    final instCtrl = TextEditingController();
    String? commodity;
    String? origin;
    String? dest;
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => StatefulBuilder(
          builder: (ctx, setLocal) => AlertDialog(
            title: const Text('Nouveau Projet PRO'),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: nameCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Nom du projet (min. 2 car.) *',
                      hintText: 'Ex. Négoce Mil Salamat → N’Djamena',
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: descCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Objectif / Description',
                      hintText: 'Ex. Préparer un dossier de financement IMF',
                    ),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String?>(
                    initialValue: commodity,
                    isExpanded: true,
                    decoration: const InputDecoration(
                        labelText: 'Filière / Produit (optionnel)'),
                    items: [
                      const DropdownMenuItem<String?>(
                          value: null, child: Text('Non spécifié')),
                      ..._commodities.map((c) => DropdownMenuItem<String?>(
                            value: c,
                            child: Text(commodityLabelFr(c),
                                overflow: TextOverflow.ellipsis),
                          )),
                    ],
                    onChanged: (v) => setLocal(() => commodity = v),
                  ),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String?>(
                    initialValue: origin,
                    isExpanded: true,
                    decoration: const InputDecoration(
                        labelText: 'Province d’origine (optionnel)'),
                    items: [
                      const DropdownMenuItem<String?>(
                          value: null, child: Text('Non spécifiée')),
                      ..._provinces.map((p) => DropdownMenuItem<String?>(
                            value: p,
                            child: Text(p, overflow: TextOverflow.ellipsis),
                          )),
                    ],
                    onChanged: (v) => setLocal(() => origin = v),
                  ),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String?>(
                    initialValue: dest,
                    isExpanded: true,
                    decoration: const InputDecoration(
                        labelText: 'Province de destination (optionnel)'),
                    items: [
                      const DropdownMenuItem<String?>(
                          value: null, child: Text('Non spécifiée')),
                      ..._provinces.map((p) => DropdownMenuItem<String?>(
                            value: p,
                            child: Text(p, overflow: TextOverflow.ellipsis),
                          )),
                    ],
                    onChanged: (v) => setLocal(() => dest = v),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: capCtrl,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Capital estimé en FCFA (optionnel)',
                      hintText: 'Ex. 2 000 000',
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: instCtrl,
                    maxLines: 2,
                    decoration: const InputDecoration(
                      labelText: 'Consignes permanentes pour l’IA (optionnel)',
                      hintText:
                          'Ex. Sans périssables, fret 20 XAF/kg, ton concis',
                    ),
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
                  child: const Text('Créer le projet')),
            ],
          ),
        ),
      );
      if (ok != true) return;
      final name = nameCtrl.text.trim();
      if (name.length < 2) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text(
                    'Le nom du projet doit contenir au moins 2 caractères.')),
          );
        }
        return;
      }
      final cap = capCtrl.text.trim().isNotEmpty
          ? _parseCapital(capCtrl.text.trim())
          : null;
      final instText = instCtrl.text.trim();
      final studyCtx = <String, dynamic>{
        'product_activity': {
          if (commodity != null) 'commodity': commodity,
        },
        'geography': {
          if (origin != null) 'origin_province': origin,
          if (dest != null) 'dest_province': dest,
          'provinces_mentioned': [
            if (origin != null) origin!,
            if (dest != null && dest != origin) dest!,
          ],
        },
        'budget_and_assumptions': {
          if (cap != null) 'capital_xaf': cap,
        },
        if (instText.isNotEmpty) 'user_instructions': [instText],
      };
      await _guard(() async {
        final created = await widget.apiService.createProject(
          name: name,
          description: descCtrl.text.trim(),
          studyContext: studyCtx,
        );
        await _load();
        if (mounted && created['project_id'] != null) {
          await _openWorkspace(created);
        }
      });
    } finally {
      nameCtrl.dispose();
      descCtrl.dispose();
      capCtrl.dispose();
      instCtrl.dispose();
    }
  }

  Future<void> _renameProject(Map<String, dynamic> proj) async {
    final ctrl = TextEditingController(text: proj['name']?.toString() ?? '');
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Renommer le projet'),
          content: TextField(
              controller: ctrl,
              decoration: const InputDecoration(
                  labelText: 'Nouveau nom (min. 2 car.)')),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Annuler')),
            ElevatedButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Enregistrer')),
          ],
        ),
      );
      if (ok != true) return;
      final name = ctrl.text.trim();
      if (name.length < 2) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text(
                    'Le nouveau nom doit contenir au moins 2 caractères.')),
          );
        }
        return;
      }
      await _guard(() async {
        await widget.apiService
            .updateProject(proj['project_id'].toString(), name: name);
        await _load();
      });
    } finally {
      ctrl.dispose();
    }
  }

  Widget _kpiChip(String label, String value) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: FDTheme.blueSoft,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          '$label : $value',
          style: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: FDTheme.blueDark,
          ),
        ),
      );

  void _openToolDialog(String title, Widget child) {
    showDialog<void>(
      context: context,
      builder: (ctx) => Dialog(
        insetPadding: const EdgeInsets.all(16),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 960, maxHeight: 760),
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 8, 6),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        title,
                        style: const TextStyle(
                            fontSize: 15, fontWeight: FontWeight.w800),
                      ),
                    ),
                    IconButton(
                      onPressed: () => Navigator.of(ctx).pop(),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(child: child),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _shareProject(Map<String, dynamic> proj) async {
    final pid = proj['project_id']?.toString() ?? '';
    if (pid.isEmpty) return;
    try {
      final res = await widget.apiService.createProjectShareLink(pid);
      if (!mounted) return;
      final sharePath = res['share_path']?.toString() ?? '';
      final fullUrl = '${ApiService.baseUrl}$sharePath';
      final exp = res['expires_at_utc']?.toString() ?? '';
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Lien de partage (lecture seule)'),
          content: SizedBox(
            width: 440,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Ce lien donne un accès en lecture seule au projet « ${proj['name'] ?? ''} » jusqu\'au $exp.',
                  style: const TextStyle(fontSize: 12.5),
                ),
                const SizedBox(height: 10),
                SelectableText(
                  fullUrl,
                  style: const TextStyle(
                      fontSize: 12, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('Fermer'),
            ),
            FilledButton.icon(
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: fullUrl));
                if (!ctx.mounted) return;
                Navigator.of(ctx).pop();
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                      content: Text(
                          'Lien de partage copié dans le presse-papiers.')),
                );
              },
              icon: const Icon(Icons.copy_rounded, size: 16),
              label: const Text('Copier le lien'),
            ),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.toString().replaceFirst('Exception: ', ''))),
      );
    }
  }

  Future<void> _confirmDelete(Map<String, dynamic> proj) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Supprimer le projet ?'),
        content: Text(
            'Cette action est irréversible pour « ${proj['name']} », ses versions d’études et les documents privés rattachés à ce projet (vos discussions restent conservées dans votre historique général).'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Annuler')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: FDTheme.danger, foregroundColor: Colors.white),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Supprimer'),
          ),
        ],
      ),
    );
    if (ok == true) {
      final pid = proj['project_id'].toString();
      await _guard(() async {
        await widget.apiService.deleteProject(pid);
        await LocalConversationStorage.instance.detachProject(pid);
        if (mounted && _selectedProject?['project_id']?.toString() == pid) {
          setState(() {
            _selectedProject = null;
            _projectConversations = [];
            _projectDocuments = [];
          });
        }
        await _load();
      });
    }
  }

  Future<void> _generateStudyDialog(Map<String, dynamic> proj) async {
    String commodity =
        _commodities.contains('Millet') ? 'Millet' : _commodities.first;
    String origin = _provinces.contains('Lac') ? 'Lac' : _provinces.first;
    String dest =
        _provinces.contains("N'Djamena") ? "N'Djamena" : _provinces.first;
    final capCtrl = TextEditingController(text: '2000000');
    try {
      // Études déjà présentes + pré-remplissage intelligent depuis le StudyContext du projet.
      List<Map<String, dynamic>> existing = const [];
      try {
        final full =
            await widget.apiService.getProject(proj['project_id'].toString());
        existing = (full['studies'] as List? ?? [])
            .whereType<Map>()
            .map((m) => Map<String, dynamic>.from(m))
            .toList();
        final ctx = full['study_context'];
        if (ctx is Map) {
          final prod = ctx['product_activity'];
          if (prod is Map) {
            final c = prod['commodity']?.toString().trim() ?? '';
            if (c.isNotEmpty && _commodities.contains(c)) commodity = c;
          }
          final geo = ctx['geography'];
          if (geo is Map) {
            final o = geo['origin_province']?.toString().trim() ?? '';
            final d = geo['dest_province']?.toString().trim() ?? '';
            if (o.isNotEmpty && _provinces.contains(o)) origin = o;
            if (d.isNotEmpty && _provinces.contains(d)) dest = d;
          }
          final bud = ctx['budget_and_assumptions'];
          if (bud is Map && bud['capital_xaf'] is num) {
            capCtrl.text = (bud['capital_xaf'] as num).round().toString();
          }
        }
      } catch (_) {}
      if (!mounted) return;
      String? targetStudyId; // null = nouvelle étude
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text('Nouvelle étude PDF — ${proj['name']}'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (existing.isNotEmpty) ...[
                  DropdownButtonFormField<String?>(
                    initialValue: null,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: 'Étude cible'),
                    items: [
                      const DropdownMenuItem<String?>(
                          value: null, child: Text('Nouvelle étude')),
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
                  decoration:
                      const InputDecoration(labelText: 'Produit / Céréale'),
                  items: _commodities
                      .map((c) => DropdownMenuItem(
                            value: c,
                            child: Text(commodityLabelFr(c),
                                overflow: TextOverflow.ellipsis),
                          ))
                      .toList(),
                  onChanged: (v) => commodity = v ?? commodity,
                ),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  initialValue: origin,
                  isExpanded: true,
                  decoration:
                      const InputDecoration(labelText: 'Province d\'origine'),
                  items: _provinces
                      .map((p) => DropdownMenuItem(
                          value: p,
                          child: Text(p, overflow: TextOverflow.ellipsis)))
                      .toList(),
                  onChanged: (v) => origin = v ?? origin,
                ),
                const SizedBox(height: 8),
                DropdownButtonFormField<String>(
                  initialValue: dest,
                  isExpanded: true,
                  decoration: const InputDecoration(
                      labelText: 'Province de destination'),
                  items: _provinces
                      .map((p) => DropdownMenuItem(
                          value: p,
                          child: Text(p, overflow: TextOverflow.ellipsis)))
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
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Annuler')),
            ElevatedButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Générer & Sauvegarder')),
          ],
        ),
      );
      if (ok != true) return;
      final cap = _parseCapital(capCtrl.text);
      if (cap == null) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text(
                    'Capital invalide : saisissez un nombre positif (ex. 2 000 000).')),
          );
        }
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
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.toString())));
      }
    } finally {
      capCtrl.dispose();
    }
  }

  Future<void> _openStudiesAndVersions(Map<String, dynamic> proj) async {
    Map<String, dynamic> full;
    try {
      full = await widget.apiService.getProject(proj['project_id'].toString());
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Ouverture impossible : $e')));
      return;
    }
    if (!mounted) return;
    final studies = (full['studies'] as List? ?? [])
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => SafeArea(
        child: ConstrainedBox(
          constraints:
              BoxConstraints(maxHeight: MediaQuery.sizeOf(ctx).height * 0.75),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Études & Versions — ${full['name']}',
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                if (studies.isEmpty)
                  const Text('Aucune étude générée pour ce projet.')
                else
                  ...studies.map((s) => ListTile(
                        title: Text(
                            s['title']?.toString() ?? s['study_id'].toString()),
                        subtitle: Text(
                            'Dernière version : v${s['latest_version']} · Maj : ${s['updated_at']}'),
                        trailing: TextButton(
                          onPressed: () => _guard(() async {
                            final versions =
                                await widget.apiService.listStudyVersions(
                              full['project_id'].toString(),
                              s['study_id'].toString(),
                            );
                            if (!ctx.mounted) return;
                            _showVersionHistoryDialog(
                                full['project_id'].toString(),
                                s['study_id'].toString(),
                                versions);
                          }),
                          child: const Text('Historique'),
                        ),
                      )),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// Rend la différence de métriques lisible (une ligne par métrique) au lieu d'un Map brut.
  String _formatDiff(dynamic raw) {
    if (raw is! Map || raw.isEmpty)
      return 'Aucune différence de métrique détectée.';
    final lines = <String>[];
    raw.forEach((k, v) {
      if (v is Map) {
        final before = v['from'] ?? v['old'] ?? v['before'] ?? v['a'];
        final after = v['to'] ?? v['new'] ?? v['after'] ?? v['b'];
        if (before != null || after != null) {
          lines.add('• $k : ${before ?? '—'} → ${after ?? '—'}');
        } else {
          lines.add(
              '• $k : ${v.entries.map((e) => '${e.key}=${e.value}').join(', ')}');
        }
      } else {
        lines.add('• $k : $v');
      }
    });
    return lines.join('\n');
  }

  void _showVersionHistoryDialog(
      String projectId, String studyId, List<Map<String, dynamic>> versions) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Versions — $studyId'),
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ...versions.map((v) {
                  final vNum = (v['version_number'] as num).toInt();
                  final qaStatus =
                      (v['validation'] as Map?)?['overall_status'] ?? '—';
                  final avail = v['artifact_available'] == true;
                  return ListTile(
                    dense: true,
                    title: Text('Version $vNum · QA: $qaStatus'),
                    subtitle: Text(v['created_at']?.toString() ?? ''),
                    trailing: avail
                        ? IconButton(
                            icon: const Icon(Icons.picture_as_pdf_rounded,
                                color: FDTheme.blue),
                            onPressed: () => _guard(() async {
                              final bytes = await widget.apiService
                                  .downloadStudyVersionPdf(
                                      projectId, studyId, vNum);
                              triggerPdfDownload(
                                  bytes, 'freedata_${studyId}_v$vNum.pdf');
                            }),
                          )
                        : const Text('PDF absent',
                            style:
                                TextStyle(fontSize: 11, color: FDTheme.muted)),
                  );
                }),
                if (versions.length >= 2) ...[
                  const Divider(),
                  TextButton.icon(
                    icon: const Icon(Icons.compare_arrows_rounded),
                    label: Text(
                        'Comparer v${versions[1]['version_number']} et v${versions[0]['version_number']}'),
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
                          content: SingleChildScrollView(
                              child: Text(_formatDiff(diff['metrics_diff']))),
                          actions: [
                            TextButton(
                                onPressed: () => Navigator.pop(c2),
                                child: const Text('Fermer'))
                          ],
                        ),
                      );
                    }),
                  ),
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Fermer'))
        ],
      ),
    );
  }

  void _triggerProjectChat(
    Map<String, dynamic> proj, {
    String? conversationId,
    String? initialPrompt,
    bool forceNewConversation = false,
  }) {
    if (widget.onOpenProjectChat != null) {
      widget.onOpenProjectChat!(
        proj,
        conversationId: conversationId,
        initialPrompt: initialPrompt,
        forceNewConversation: forceNewConversation,
      );
      return;
    }
    widget.onResumeProject?.call(proj);
  }

  Future<void> _uploadProjectDocument(Map<String, dynamic> proj,
      {PickedDocumentFile? existingPicked, int chunkOffset = 0}) async {
    final pid = proj['project_id']?.toString() ?? '';
    if (pid.isEmpty || _uploadingDoc) return;
    final picked = existingPicked ?? await pickUserDocumentFile();
    if (picked == null || !mounted) return;
    setState(() => _uploadingDoc = true);
    try {
      final uploaded = await widget.apiService.uploadUserDocument(
        filename: picked.name,
        bytes: picked.bytes,
        mimeType: picked.mimeType,
        projectId: pid,
        chunkOffset: chunkOffset,
      );
      if (!mounted) return;
      await _openWorkspace(proj, silent: true);
      if (!mounted) return;
      final isTruncated = uploaded['truncated'] == true;
      final nextOffset = uploaded['next_offset'];
      final warning = uploaded['indexing_warning']?.toString();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            (isTruncated && warning != null && warning.isNotEmpty)
                ? warning
                : 'Document « ${picked.name} » indexé dans ce projet.',
          ),
          duration: Duration(seconds: isTruncated ? 8 : 4),
          action: (isTruncated && nextOffset is int)
              ? SnackBarAction(
                  label: 'Poursuivre',
                  onPressed: () => _uploadProjectDocument(
                    proj,
                    existingPicked: picked,
                    chunkOffset: nextOffset,
                  ),
                )
              : null,
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _uploadingDoc = false);
    }
  }

  Widget _buildProjectWorkspace(Map<String, dynamic> proj) {
    final name = proj['name']?.toString() ?? 'Projet PRO';
    final desc = proj['description']?.toString().trim() ?? '';
    final ctx = proj['study_context'] is Map
        ? Map<String, dynamic>.from(proj['study_context'] as Map)
        : const <String, dynamic>{};
    final studies = (proj['studies'] as List? ?? [])
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();

    final summaryChips = <String>[];
    final prod = ctx['product_activity'];
    if (prod is Map &&
        (prod['commodity']?.toString().trim().isNotEmpty ?? false)) {
      summaryChips.add(commodityLabelFr(prod['commodity'].toString()));
    }
    final geo = ctx['geography'];
    if (geo is Map) {
      final o = geo['origin_province']?.toString().trim() ?? '';
      final d = geo['dest_province']?.toString().trim() ?? '';
      if (o.isNotEmpty && d.isNotEmpty) {
        summaryChips.add('$o → $d');
      } else if (o.isNotEmpty) {
        summaryChips.add(o);
      }
    }
    final bud = ctx['budget_and_assumptions'];
    if (bud is Map && bud['capital_xaf'] is num) {
      summaryChips
          .add('${formatXaf((bud['capital_xaf'] as num).toDouble())} FCFA');
    }
    final instructions = (ctx['user_instructions'] as List? ?? const [])
        .map((e) => e.toString().trim())
        .where((s) => s.isNotEmpty)
        .toList();

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 16, 6),
            child: Row(
              children: [
                TextButton.icon(
                  icon: const Icon(Icons.arrow_back_rounded, size: 18),
                  label: const Text('Tous les projets'),
                  onPressed: () => setState(() => _selectedProject = null),
                ),
                const Spacer(),
                TextButton.icon(
                  icon: const Icon(Icons.share_outlined,
                      size: 18, color: FDTheme.blue),
                  label: const Text('Partager'),
                  onPressed: () => _guard(() => _shareProject(proj)),
                ),
                TextButton.icon(
                  icon: const Icon(Icons.picture_as_pdf_outlined,
                      size: 18, color: FDTheme.green),
                  label: const Text('Étude PDF'),
                  onPressed: () => _guard(() async {
                    await _generateStudyDialog(proj);
                    if (mounted) await _openWorkspace(proj);
                  }),
                ),
              ],
            ),
          ),
          Expanded(
            child: _loadingWorkspace
                ? const Center(child: CircularProgressIndicator())
                : ListView(
                    padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
                    children: [
                      FDCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const Icon(Icons.folder_special_rounded,
                                    color: FDTheme.blue, size: 22),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    name,
                                    style: const TextStyle(
                                      fontSize: 18,
                                      fontWeight: FontWeight.w700,
                                      color: AppColors.ink,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            if (desc.isNotEmpty) ...[
                              const SizedBox(height: 6),
                              Text(desc,
                                  style: const TextStyle(
                                      fontSize: 13.5, color: AppColors.muted)),
                            ],
                            const SizedBox(height: 10),
                            Wrap(
                              spacing: 8,
                              runSpacing: 6,
                              children: [
                                _kpiChip('Études PDF', '${studies.length}'),
                                _kpiChip(
                                    'Documents', '${_projectDocuments.length}'),
                                _kpiChip('Discussions',
                                    '${_projectConversations.length}'),
                                _kpiChip('Audits Agro',
                                    '${_projectAgroAssessments.length}'),
                              ],
                            ),
                            const SizedBox(height: 10),
                            Wrap(
                              spacing: 8,
                              runSpacing: 6,
                              children: [
                                OutlinedButton.icon(
                                  onPressed: () => _openToolDialog(
                                    'Plan de Campagne & Investissement',
                                    CampaignPlanScreen(
                                        apiService: widget.apiService),
                                  ),
                                  icon: const Icon(Icons.calculate_outlined,
                                      size: 16),
                                  label: const Text('Simuler Plan Campagne'),
                                ),
                                OutlinedButton.icon(
                                  onPressed: () {
                                    final originProv = geo is Map
                                        ? geo['origin_province']?.toString()
                                        : null;
                                    _openToolDialog(
                                      'Compte d’Exploitation (OPEX / CAPEX)',
                                      FarmOperatingAccountScreen(
                                        apiService: widget.apiService,
                                        initialProvince: originProv,
                                      ),
                                    );
                                  },
                                  icon: const Icon(Icons.assessment_outlined,
                                      size: 16),
                                  label: const Text('Compte d’Exploitation'),
                                ),
                              ],
                            ),
                            if (_projectAgroAssessments.isNotEmpty) ...[
                              const SizedBox(height: 12),
                              const Text(
                                'Audits parcellaires rattachés',
                                style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.ink,
                                ),
                              ),
                              const SizedBox(height: 6),
                              for (final a in _projectAgroAssessments.take(4))
                                Padding(
                                  padding: const EdgeInsets.only(bottom: 4),
                                  child: Text(
                                    '• ${a['report_verification_code'] ?? a['id']} · ${a['province_hub'] ?? ''} (${a['area_hectares'] ?? '—'} ha) — Score ${a['computed_scores']?['weighted_score']?['total_score'] ?? '—'}/100',
                                    style: const TextStyle(
                                        fontSize: 12.5, color: AppColors.muted),
                                  ),
                                ),
                            ],
                            if (summaryChips.isNotEmpty) ...[
                              const SizedBox(height: 10),
                              Wrap(
                                spacing: 6,
                                runSpacing: 6,
                                children: summaryChips
                                    .map((c) => Container(
                                          padding: const EdgeInsets.symmetric(
                                              horizontal: 10, vertical: 4),
                                          decoration: BoxDecoration(
                                            color: FDTheme.blueSoft,
                                            borderRadius:
                                                BorderRadius.circular(99),
                                          ),
                                          child: Text(
                                            c,
                                            style: const TextStyle(
                                              fontSize: 12,
                                              fontWeight: FontWeight.w600,
                                              color: FDTheme.blue,
                                            ),
                                          ),
                                        ))
                                    .toList(),
                              ),
                            ],
                            if (instructions.isNotEmpty) ...[
                              const SizedBox(height: 10),
                              Text(
                                'Consignes IA : ${instructions.join(' · ')}',
                                style: const TextStyle(
                                    fontSize: 12.5,
                                    color: AppColors.muted,
                                    fontStyle: FontStyle.italic),
                              ),
                            ],
                          ],
                        ),
                      ),
                      const SizedBox(height: 14),
                      // Champ de saisie direct façon ChatGPT Projects
                      FDCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Nouvelle discussion dans ce projet',
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w700,
                                color: AppColors.ink,
                              ),
                            ),
                            const SizedBox(height: 8),
                            Row(
                              children: [
                                Expanded(
                                  child: TextField(
                                    controller: _workspacePromptCtrl,
                                    decoration: InputDecoration(
                                      hintText:
                                          'Posez une question dans « $name »...',
                                      isDense: true,
                                      border: OutlineInputBorder(
                                        borderRadius: BorderRadius.circular(12),
                                      ),
                                    ),
                                    onSubmitted: (val) {
                                      final t = val.trim();
                                      if (t.isEmpty) return;
                                      _workspacePromptCtrl.clear();
                                      _triggerProjectChat(
                                        proj,
                                        initialPrompt: t,
                                        forceNewConversation: true,
                                      );
                                    },
                                  ),
                                ),
                                const SizedBox(width: 8),
                                ElevatedButton.icon(
                                  icon: const Icon(Icons.arrow_upward_rounded,
                                      size: 18),
                                  label: const Text('Démarrer'),
                                  onPressed: () {
                                    final t = _workspacePromptCtrl.text.trim();
                                    _workspacePromptCtrl.clear();
                                    _triggerProjectChat(
                                      proj,
                                      initialPrompt: t.isEmpty ? null : t,
                                      forceNewConversation: true,
                                    );
                                  },
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 14),
                      // Discussions existantes du projet (reprise sans réinitialisation)
                      Row(
                        children: [
                          Text(
                            'Discussions du projet (${_projectConversations.length})',
                            style: const TextStyle(
                              fontSize: 14.5,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink,
                            ),
                          ),
                          const Spacer(),
                          if (_projectConversations.isNotEmpty)
                            TextButton.icon(
                              icon: const Icon(Icons.play_arrow_rounded,
                                  size: 18),
                              label: const Text('Continuer la dernière'),
                              onPressed: () => _triggerProjectChat(
                                proj,
                                conversationId: _projectConversations.first.id,
                              ),
                            ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      if (_projectConversations.isEmpty)
                        const FDCard(
                          child: Text(
                            'Aucune discussion enregistrée dans ce projet pour le moment. Saisissez une question ci-dessus pour démarrer avec le contexte du projet.',
                            style:
                                TextStyle(fontSize: 13, color: AppColors.muted),
                          ),
                        )
                      else
                        ..._projectConversations.map((conv) => Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: FDCard(
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 12, vertical: 6),
                                child: ListTile(
                                  contentPadding: EdgeInsets.zero,
                                  leading: const Icon(
                                      Icons.chat_bubble_outline_rounded,
                                      color: FDTheme.blue,
                                      size: 20),
                                  title: Text(
                                    conv.title,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w600,
                                      color: AppColors.ink,
                                    ),
                                  ),
                                  subtitle: Text(
                                    '${conv.messages.length} message(s) · ${conv.previewText}',
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                        fontSize: 12.5, color: AppColors.muted),
                                  ),
                                  trailing: const Icon(
                                      Icons.chevron_right_rounded,
                                      color: AppColors.muted),
                                  onTap: () => _triggerProjectChat(
                                    proj,
                                    conversationId: conv.id,
                                  ),
                                ),
                              ),
                            )),
                      const SizedBox(height: 14),
                      Text(
                        'Études PDF & Versions (${studies.length})',
                        style: const TextStyle(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 6),
                      if (studies.isEmpty)
                        const FDCard(
                          child: Text(
                            'Aucune étude PDF générée dans ce dossier.',
                            style:
                                TextStyle(fontSize: 13, color: AppColors.muted),
                          ),
                        )
                      else
                        ...studies.map((s) => Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: FDCard(
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 12, vertical: 6),
                                child: ListTile(
                                  contentPadding: EdgeInsets.zero,
                                  leading: const Icon(
                                      Icons.picture_as_pdf_rounded,
                                      color: FDTheme.green,
                                      size: 20),
                                  title: Text(s['title']?.toString() ??
                                      s['study_id'].toString()),
                                  subtitle: Text(
                                      'Dernière version : v${s['latest_version']} · Maj : ${s['updated_at']}'),
                                  trailing: TextButton(
                                    onPressed: () => _guard(() async {
                                      final versions = await widget.apiService
                                          .listStudyVersions(
                                        proj['project_id'].toString(),
                                        s['study_id'].toString(),
                                      );
                                      if (!mounted) return;
                                      _showVersionHistoryDialog(
                                        proj['project_id'].toString(),
                                        s['study_id'].toString(),
                                        versions,
                                      );
                                    }),
                                    child: const Text('Historique'),
                                  ),
                                ),
                              ),
                            )),
                      const SizedBox(height: 14),
                      Row(
                        children: [
                          Text(
                            'Documents privés du projet (${_projectDocuments.length})',
                            style: const TextStyle(
                              fontSize: 14.5,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink,
                            ),
                          ),
                          const Spacer(),
                          TextButton.icon(
                            icon: _uploadingDoc
                                ? const SizedBox(
                                    width: 14,
                                    height: 14,
                                    child: CircularProgressIndicator(
                                        strokeWidth: 2),
                                  )
                                : const Icon(Icons.attach_file_rounded,
                                    size: 18),
                            label: const Text('Ajouter un PDF/CSV'),
                            onPressed: _uploadingDoc
                                ? null
                                : () => _uploadProjectDocument(proj),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      if (_projectDocuments.isEmpty)
                        const FDCard(
                          child: Text(
                            'Aucun document privé attaché à ce projet. Ajoutez un devis, contrat ou rapport PDF : seuls les chats de ce projet l’utiliseront.',
                            style:
                                TextStyle(fontSize: 13, color: AppColors.muted),
                          ),
                        )
                      else
                        ..._projectDocuments.map((doc) {
                          final docId = doc['doc_id']?.toString() ?? '';
                          final fname =
                              doc['filename']?.toString() ?? 'Document';
                          final chunks = doc['chunks_count'] ?? 0;
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: FDCard(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 12, vertical: 6),
                              child: ListTile(
                                contentPadding: EdgeInsets.zero,
                                leading: const Icon(Icons.description_outlined,
                                    color: FDTheme.blue, size: 20),
                                title: Text(fname,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis),
                                subtitle: Text(
                                  '$chunks segment(s) · Document privé indexé',
                                  style: const TextStyle(
                                      fontSize: 12, color: AppColors.muted),
                                ),
                                trailing: IconButton(
                                  icon: const Icon(Icons.delete_outline_rounded,
                                      color: FDTheme.danger, size: 20),
                                  tooltip: 'Supprimer du projet',
                                  onPressed: () => _guard(() async {
                                    await widget.apiService
                                        .deleteUserDocument(docId);
                                    if (mounted) {
                                      await _openWorkspace(proj, silent: true);
                                    }
                                  }),
                                ),
                              ),
                            ),
                          );
                        }),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_selectedProject != null) {
      return _buildProjectWorkspace(_selectedProject!);
    }
    // Pas d'AppBar ici : MainShell affiche déjà le titre (sinon deux barres empilées).
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: !_canAccessProjects
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 460),
                  child: FDCard(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Vos projets & études enregistrées',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w800,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 8),
                        const Text(
                          'Connectez-vous ou créez un compte gratuit pour créer des dossiers projets, conserver vos discussions associées et générer des études PDF versionnées.',
                          style: TextStyle(
                            fontSize: 13.5,
                            color: AppColors.muted,
                            height: 1.45,
                          ),
                        ),
                        const SizedBox(height: 16),
                        Wrap(
                          spacing: 10,
                          runSpacing: 8,
                          children: [
                            FDPrimaryButton(
                              label: 'Se connecter',
                              icon: Icons.login_rounded,
                              onPressed: () => _openAuth(register: false),
                            ),
                            FDSecondaryButton(
                              label: 'Créer un compte',
                              icon: Icons.person_add_alt_1_rounded,
                              onPressed: () => _openAuth(register: true),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            )
          : Column(
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
        ? const FDLoadingState(message: 'Chargement de vos projets…')
        : _error != null
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 440),
                    child: FDErrorState(
                      message: _error!.contains('TimeoutException')
                          ? 'Le serveur met plus de temps que prévu à répondre (démarrage en cours).'
                          : _error!,
                      onRetry: _load,
                    ),
                  ),
                ),
              )
            : _projects.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 420),
                        child: FDCard(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.folder_special_outlined,
                                  size: 36, color: FDTheme.blue),
                              const SizedBox(height: 10),
                              const Text(
                                'Aucun projet enregistré',
                                style: TextStyle(
                                  fontSize: 15.5,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.ink,
                                ),
                              ),
                              const SizedBox(height: 6),
                              const Text(
                                'Créez un dossier projet pour conserver vos paramètres métier, vos discussions et vos études PDF versionnées.',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                    fontSize: 13, color: AppColors.muted),
                              ),
                              const SizedBox(height: 14),
                              FDPrimaryButton(
                                label: 'Créer mon premier projet',
                                icon: Icons.add_rounded,
                                onPressed: _createProjectDialog,
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  )
                : Column(
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                        child: TextField(
                          controller: _searchCtrl,
                          onChanged: (v) => setState(
                              () => _searchQuery = v.trim().toLowerCase()),
                          decoration: InputDecoration(
                            hintText:
                                'Rechercher un projet par nom ou description…',
                            prefixIcon:
                                const Icon(Icons.search_rounded, size: 19),
                            suffixIcon: _searchQuery.isNotEmpty
                                ? IconButton(
                                    icon: const Icon(Icons.clear_rounded,
                                        size: 18),
                                    onPressed: () {
                                      _searchCtrl.clear();
                                      setState(() => _searchQuery = '');
                                    },
                                  )
                                : null,
                            isDense: true,
                          ),
                        ),
                      ),
                      Expanded(
                        child: Builder(builder: (context) {
                          final filtered = _searchQuery.isEmpty
                              ? _projects
                              : _projects.where((p) {
                                  final n = (p['name'] ?? '')
                                      .toString()
                                      .toLowerCase();
                                  final d = (p['description'] ?? '')
                                      .toString()
                                      .toLowerCase();
                                  return n.contains(_searchQuery) ||
                                      d.contains(_searchQuery);
                                }).toList();
                          if (filtered.isEmpty) {
                            return const Center(
                              child: Text(
                                'Aucun projet ne correspond à votre recherche.',
                                style: TextStyle(
                                    fontSize: 13, color: AppColors.muted),
                              ),
                            );
                          }
                          return ListView.separated(
                            padding: const EdgeInsets.all(16),
                            itemCount: filtered.length,
                            separatorBuilder: (_, __) =>
                                const SizedBox(height: 10),
                            itemBuilder: (_, i) {
                              final p = filtered[i];
                              final isArchived = p['status'] == 'archived';
                              return FDCard(
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 14, vertical: 10),
                                child: Column(
                                  children: [
                                    ListTile(
                                      contentPadding: EdgeInsets.zero,
                                      onTap: () => _openWorkspace(p),
                                      title: Text(
                                          p['name']?.toString() ?? 'Projet',
                                          style: const TextStyle(
                                              fontWeight: FontWeight.w700,
                                              color: AppColors.ink)),
                                      subtitle: Text(
                                        'Statut : ${isArchived ? 'Archivé' : 'Actif'} · Études : ${p['studies_count'] ?? 0} · Maj : ${p['updated_at']}',
                                        style: const TextStyle(
                                            fontSize: 12.5,
                                            color: AppColors.muted),
                                      ),
                                      trailing: PopupMenuButton<String>(
                                        onSelected: (act) => _guard(() async {
                                          if (act == 'rename') {
                                            await _renameProject(p);
                                          }
                                          if (act == 'archive') {
                                            await widget.apiService
                                                .updateProject(
                                              p['project_id'].toString(),
                                              status: isArchived
                                                  ? 'active'
                                                  : 'archived',
                                            );
                                            await _load();
                                          }
                                          if (act == 'share') {
                                            await _shareProject(p);
                                          }
                                          if (act == 'delete') {
                                            await _confirmDelete(p);
                                          }
                                        }),
                                        itemBuilder: (_) => [
                                          const PopupMenuItem(
                                              value: 'share',
                                              child: Text(
                                                  'Partager (lecture seule)')),
                                          const PopupMenuItem(
                                              value: 'rename',
                                              child: Text('Renommer')),
                                          PopupMenuItem(
                                              value: 'archive',
                                              child: Text(isArchived
                                                  ? 'Restaurer'
                                                  : 'Archiver')),
                                          const PopupMenuItem(
                                              value: 'delete',
                                              child: Text('Supprimer')),
                                        ],
                                      ),
                                    ),
                                    const SizedBox(height: 4),
                                    Wrap(
                                      spacing: 4,
                                      runSpacing: 0,
                                      children: [
                                        TextButton.icon(
                                          icon: const Icon(
                                              Icons.picture_as_pdf_outlined,
                                              color: FDTheme.green,
                                              size: 18),
                                          label: const Text('Étude PDF'),
                                          onPressed: () => _guard(
                                              () => _generateStudyDialog(p)),
                                        ),
                                        TextButton.icon(
                                          icon: const Icon(Icons.share_outlined,
                                              color: FDTheme.blue, size: 17),
                                          label: const Text('Partager'),
                                          onPressed: () =>
                                              _guard(() => _shareProject(p)),
                                        ),
                                        TextButton.icon(
                                          icon: const Icon(
                                              Icons.folder_open_rounded,
                                              color: FDTheme.blue,
                                              size: 18),
                                          label: const Text('Ouvrir'),
                                          onPressed: () => _openWorkspace(p),
                                        ),
                                        TextButton.icon(
                                          icon: const Icon(
                                              Icons.play_arrow_rounded,
                                              color: FDTheme.blue,
                                              size: 18),
                                          label: const Text('Reprendre'),
                                          onPressed: () => _guard(() async {
                                            final full = await widget.apiService
                                                .getProject(
                                                    p['project_id'].toString());
                                            final existingConvs =
                                                await LocalConversationStorage
                                                    .instance
                                                    .listProjectConversations(
                                                        p['project_id']
                                                            .toString());
                                            if (!mounted) return;
                                            _triggerProjectChat(
                                              full,
                                              conversationId:
                                                  existingConvs.isNotEmpty
                                                      ? existingConvs.first.id
                                                      : null,
                                            );
                                          }),
                                        ),
                                        TextButton.icon(
                                          icon: const Icon(
                                              Icons.history_rounded,
                                              size: 18),
                                          label: const Text('Versions'),
                                          onPressed: () =>
                                              _openStudiesAndVersions(p),
                                        ),
                                      ],
                                    ),
                                  ],
                                ),
                              );
                            },
                          );
                        }),
                      ),
                    ],
                  );
  }
}
