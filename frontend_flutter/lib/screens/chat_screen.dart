import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../core/fd_theme.dart';
import '../core/models/chat_models.dart';
import '../core/utils/file_picker.dart';
import '../core/utils/formatters.dart';
import '../core/utils/pdf_download.dart';
import '../services/api_service.dart';
import '../services/conversation_storage.dart';
import '../widgets/chat/chat_widgets.dart';
import '../core/utils/error_text.dart';

class ChatScreen extends StatefulWidget {
  final ApiService apiService;
  final String? conversationId;
  final VoidCallback? onConversationUpdated;
  final String? initialPrompt;
  final VoidCallback? onPromptHandled;
  final Future<bool> Function()? onRequireAuth;
  final Future<PickedDocumentFile?> Function()? onPickDocument;
  final Map<String, dynamic>? activeProject;
  final VoidCallback? onOpenProjects;

  const ChatScreen({
    super.key,
    required this.apiService,
    this.conversationId,
    this.onConversationUpdated,
    this.initialPrompt,
    this.onPromptHandled,
    this.onRequireAuth,
    this.onPickDocument,
    this.activeProject,
    this.onOpenProjects,
  });

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _QuickAction {
  final IconData icon;
  final String label;
  final String prompt;

  const _QuickAction({
    required this.icon,
    required this.label,
    required this.prompt,
  });
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  ConversationThread? _thread;
  bool _loading = false;
  bool _uploadingDoc = false;
  List<Map<String, dynamic>> _userDocuments = const [];
  String? _documentsError;
  String? _lastPrompt;
  String _selectedDomain = 'auto';

  static const List<Map<String, String>> _domainChoices = [
    // « auto » (et non null) : un PopupMenuItem de valeur null n'appelle jamais onSelected.
    {'id': 'auto', 'label': 'Auto (Tchad)'},
    {'id': 'markets_and_prices', 'label': 'Marchés & Prix'},
    {'id': 'agriculture', 'label': 'Agriculture'},
    {'id': 'economy', 'label': 'Économie'},
    {'id': 'health', 'label': 'Santé'},
    {'id': 'population', 'label': 'Population'},
    {'id': 'environment', 'label': 'Environnement'},
    {'id': 'infrastructure', 'label': 'Infrastructures'},
    {'id': 'transport', 'label': 'Transport'},
  ];

  static const List<_QuickAction> _quickActions = [
    _QuickAction(
      icon: Icons.show_chart_rounded,
      label: "Prévision Mil · N'Djamena",
      prompt: "Quelle est la prévision du prix du mil à N'Djamena ?",
    ),
    _QuickAction(
      icon: Icons.shield_outlined,
      label: "Crédit 3M FCFA · Salamat",
      prompt:
          "Évalue le risque de financer 3 millions de FCFA de mil au Salamat.",
    ),
    _QuickAction(
      icon: Icons.warning_amber_rounded,
      label: "Alertes de hausse (>15%)",
      prompt: "Quelles sont les alertes de hausse de prix actuelles ?",
    ),
    _QuickAction(
      icon: Icons.swap_horiz_rounded,
      label: "Tendance Sorgho rouge",
      prompt: "Quelle est la prévision du prix du sorgho rouge au Tchad ?",
    ),
  ];

  static const _QuickAction _proQuickAction = _QuickAction(
    icon: Icons.calendar_month_rounded,
    label: "Saisonnalité & Stockage · Mil",
    prompt:
        "Quel est le meilleur mois pour acheter, stocker et revendre du mil au Salamat ?",
  );

  /// Sauvegarde locale tolérante : si le stockage du navigateur est plein ou indisponible, la conversation reste
  /// affichée en mémoire et l'envoi n'est jamais bloqué (sinon le spinner tournerait indéfiniment).
  Future<void> _safeSave(ConversationThread thread) async {
    try {
      await LocalConversationStorage.instance.saveConversation(thread);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)
        ?..clearSnackBars()
        ..showSnackBar(const SnackBar(
          content: Text(
              'Stockage local plein ou indisponible : cette conversation n’a pas pu être sauvegardée.'),
        ));
    }
  }

  Future<void> _loadDefaultDomain() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString('fd_pref_domain');
      if (!mounted || saved == null) return;
      if (_domainChoices.any((d) => d['id'] == saved)) {
        setState(() => _selectedDomain = saved);
      }
    } catch (_) {}
  }

  String? _activeProjectId() {
    final eff = _effectiveProject();
    final pid = _thread?.projectId ?? eff?['project_id']?.toString();
    return (pid != null && pid.trim().isNotEmpty) ? pid.trim() : null;
  }

  Future<void> _setSelectedDomain(String value) async {
    if (!_domainChoices.any((domain) => domain['id'] == value)) return;
    if (mounted) setState(() => _selectedDomain = value);
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('fd_pref_domain', value);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)
        ?..clearSnackBars()
        ..showSnackBar(const SnackBar(
          content: Text('Le domaine est sélectionné, mais sa préférence n’a pas pu être sauvegardée.'),
        ));
    }
  }

  Future<void> _loadUserDocuments() async {
    if (!widget.apiService.isAuthenticated &&
        !widget.apiService.hasExplicitPremiumKey) {
      if (mounted && (_userDocuments.isNotEmpty || _documentsError != null)) {
        setState(() {
          _userDocuments = const [];
          _documentsError = null;
        });
      }
      return;
    }
    try {
      final docs = await widget.apiService
          .listUserDocuments(projectId: _activeProjectId());
      if (!mounted) return;
      setState(() {
        _userDocuments = docs;
        _documentsError = null;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _documentsError = 'Impossible de charger vos documents. Vérifiez votre connexion puis réessayez.');
    }
  }

  String _friendlyUploadError(Object e) {
    if (e is TimeoutException) {
      return 'Envoi trop long (réseau lent). Réessayez avec une meilleure connexion ou un fichier plus léger.';
    }
    final msg = errText(e);
    if (msg.contains('SocketException') ||
        msg.contains('ClientException') ||
        msg.contains('Failed to fetch')) {
      return 'Connexion perdue pendant l\'envoi. Vérifiez votre réseau puis réessayez.';
    }
    return msg;
  }

  Future<void> _handleAttachDocument() async {
    if (_uploadingDoc) return;
    if (widget.onRequireAuth != null &&
        !widget.apiService.isAuthenticated &&
        !widget.apiService.hasExplicitPremiumKey) {
      final ok = await widget.onRequireAuth!();
      if (!mounted || !ok) return;
      // Sur mobile, le navigateur n'ouvre le sélecteur de fichiers que dans un
      // geste direct de l'utilisateur : après la boîte de connexion le geste est
      // perdu. On demande donc un second appui plutôt que d'échouer en silence.
      ScaffoldMessenger.maybeOf(context)
        ?..clearSnackBars()
        ..showSnackBar(const SnackBar(
          content: Text(
              'Connecté. Touchez de nouveau le trombone pour choisir votre fichier.'),
        ));
      return;
    }

    final picker = widget.onPickDocument ?? pickUserDocumentFile;
    final picked = await picker();
    if (picked == null || !mounted) return;

    setState(() => _uploadingDoc = true);
    ScaffoldMessenger.maybeOf(context)
      ?..clearSnackBars()
      ..showSnackBar(
        SnackBar(
          content:
              Text('Indexation sémantique en cours pour « ${picked.name} »…'),
        ),
      );
    try {
      await _uploadPickedFileWithProgressiveIndexing(picked, chunkOffset: 0);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)
        ?..clearSnackBars()
        ..showSnackBar(
          SnackBar(
            backgroundColor: FDTheme.danger,
            content: Text(_friendlyUploadError(e)),
            duration: const Duration(seconds: 6),
          ),
        );
    } finally {
      if (mounted) setState(() => _uploadingDoc = false);
    }
  }

  Future<void> _uploadPickedFileWithProgressiveIndexing(
    PickedDocumentFile picked, {
    required int chunkOffset,
  }) async {
    final uploaded = await widget.apiService.uploadUserDocument(
      filename: picked.name,
      bytes: picked.bytes,
      mimeType: picked.mimeType,
      projectId: _activeProjectId(),
      chunkOffset: chunkOffset,
    );
    await _loadUserDocuments();
    if (!mounted) return;
    final chunksCount = uploaded['chunks_count'] ?? 1;
    final isTruncated = uploaded['truncated'] == true;
    final nextOffset = uploaded['next_offset'];
    final warning = uploaded['indexing_warning']?.toString();
    final isDuplicate = uploaded['duplicate'] == true;

    final msg = isDuplicate
        ? 'Document « ${picked.name} » déjà indexé dans cet espace.'
        : (isTruncated && warning != null && warning.isNotEmpty)
            ? warning
            : 'Document privé « ${picked.name} » indexé ($chunksCount segments). Posez votre question !';

    ScaffoldMessenger.maybeOf(context)
      ?..clearSnackBars()
      ..showSnackBar(
        SnackBar(
          backgroundColor: isTruncated ? FDTheme.blue : FDTheme.greenDark,
          content: Text(msg),
          duration: Duration(seconds: isTruncated ? 8 : 4),
          action: (isTruncated && nextOffset is int)
              ? SnackBarAction(
                  label: 'Poursuivre',
                  textColor: Colors.white,
                  onPressed: () {
                    _uploadPickedFileWithProgressiveIndexing(
                      picked,
                      chunkOffset: nextOffset,
                    ).catchError((_) {});
                  },
                )
              : null,
        ),
      );
    if (chunkOffset == 0 && _controller.text.trim().isEmpty) {
      setState(() {
        _controller.text =
            'Analyse mon document « ${picked.name} » et résume les points clés.';
      });
    }
  }

  Future<void> _deleteUserDocument(String docId, String filename) async {
    try {
      await widget.apiService.deleteUserDocument(docId);
      if (!mounted) return;
      setState(() {
        _userDocuments =
            _userDocuments.where((d) => d['doc_id'] != docId).toList();
      });
      ScaffoldMessenger.maybeOf(context)
        ?..clearSnackBars()
        ..showSnackBar(
          SnackBar(
            content: Text('Document privé « $filename » supprimé.'),
            duration: const Duration(seconds: 2),
          ),
        );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)
        ?..clearSnackBars()
        ..showSnackBar(SnackBar(content: Text(errText(e))));
    }
  }

  @override
  void initState() {
    super.initState();
    // Pré-réveil silencieux Render (partagé via le cache getMetadata)
    widget.apiService.getMetadata().catchError((_) => <String, dynamic>{});
    _loadConversation(widget.conversationId);
    _loadDefaultDomain();
    _loadUserDocuments();

    if (widget.initialPrompt != null && widget.initialPrompt!.isNotEmpty) {
      final promptToSend = widget.initialPrompt!;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        widget.onPromptHandled?.call();
        _sendOrKeep(promptToSend);
      });
    }
  }

  @override
  void didUpdateWidget(covariant ChatScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    _loadDefaultDomain();
    _loadUserDocuments();
    if (oldWidget.conversationId != widget.conversationId) {
      _loadConversation(widget.conversationId);
    }
    if (widget.initialPrompt != null &&
        widget.initialPrompt!.isNotEmpty &&
        widget.initialPrompt != oldWidget.initialPrompt) {
      final promptToSend = widget.initialPrompt!;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        widget.onPromptHandled?.call();
        _sendOrKeep(promptToSend);
      });
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadConversation(String? id) async {
    if (id != null &&
        _thread?.id == id &&
        (_thread?.messages.isNotEmpty ?? false)) {
      return;
    }

    if (_thread != null && id != _thread!.id) {
      _lastPrompt = null;
      if (widget.initialPrompt == null || widget.initialPrompt!.isEmpty) {
        _controller.clear();
      }
    }

    final now = DateTime.now();
    final activePid = widget.activeProject?['project_id']?.toString();
    final activePname = widget.activeProject?['name']?.toString();
    setState(() {
      _loading = false;
      if (id != null && _thread?.id != id) {
        _thread = ConversationThread(
          id: id,
          title: 'Nouvelle conversation',
          createdAt: now,
          updatedAt: now,
          projectId: activePid,
          projectName: activePname,
        );
      }
    });

    if (id != null) {
      final found = await LocalConversationStorage.instance.getConversation(id);
      if (!mounted || widget.conversationId != id) return;
      if (_thread?.id == id && (_thread?.messages.isNotEmpty ?? false)) return;

      if (found != null) {
        setState(() => _thread = found);
        _ensureProjectLoaded(found.projectId);
        _scrollToBottom();
      } else {
        _ensureProjectLoaded(activePid);
      }
      return;
    }

    // Sinon, charger la plus récente active ou préparer un brouillon vide en mémoire
    final conversations =
        await LocalConversationStorage.instance.loadConversations();
    if (!mounted || widget.conversationId != null) return;

    if (conversations.isNotEmpty) {
      setState(() => _thread = conversations.first);
      _ensureProjectLoaded(conversations.first.projectId);
    } else {
      final draft = await LocalConversationStorage.instance.createConversation(
        projectId: activePid,
        projectName: activePname,
      );
      if (!mounted || widget.conversationId != null) return;
      setState(() => _thread = draft);
      _ensureProjectLoaded(activePid);
    }
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  String _titleFromPrompt(String prompt) {
    final normalized = prompt.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (normalized.length <= 30) return normalized;
    return '${normalized.substring(0, 27)}...';
  }

  List<Map<String, dynamic>> _extractSources(Map<String, dynamic> response) {
    List<Map<String, dynamic>> normalize(dynamic value) {
      if (value is! List) return const [];
      return value.whereType<Map>().map((item) {
        return item.map<String, dynamic>(
          (key, value) => MapEntry(key.toString(), value),
        );
      }).toList();
    }

    final direct = normalize(response['sources']);
    if (direct.isNotEmpty) return direct;
    final metadata = response['metadata'];
    if (metadata is Map) return normalize(metadata['sources']);
    return const [];
  }

  Map<String, dynamic>? _loadedProject;
  String? _loadedProjectId;

  Future<void> _ensureProjectLoaded(String? projectId) async {
    final pid = projectId?.trim();
    if (pid == null || pid.isEmpty) {
      if (_loadedProject != null && mounted) {
        setState(() {
          _loadedProject = null;
          _loadedProjectId = null;
        });
      }
      return;
    }
    if (widget.activeProject != null &&
        widget.activeProject!['project_id']?.toString() == pid) {
      if (_loadedProjectId != pid && mounted) {
        setState(() {
          _loadedProject = Map<String, dynamic>.from(widget.activeProject!);
          _loadedProjectId = pid;
        });
      }
      return;
    }
    if (_loadedProjectId == pid && _loadedProject != null) return;
    try {
      final full = await widget.apiService.getProject(pid);
      if (!mounted) return;
      setState(() {
        _loadedProject = full;
        _loadedProjectId = pid;
      });
    } catch (_) {}
  }

  Map<String, dynamic>? _effectiveProject() {
    final threadPid = _thread?.projectId;
    if (threadPid != null && threadPid.isNotEmpty) {
      if (_loadedProject != null &&
          _loadedProject!['project_id']?.toString() == threadPid) {
        return _loadedProject;
      }
      if (widget.activeProject != null &&
          widget.activeProject!['project_id']?.toString() == threadPid) {
        return widget.activeProject;
      }
      return {
        'project_id': threadPid,
        'name': _thread?.projectName ?? 'Projet PRO',
      };
    }
    if (widget.activeProject != null &&
        (_thread == null || _thread!.messages.isEmpty)) {
      return widget.activeProject;
    }
    return null;
  }

  Map<String, dynamic>? _latestStudyContext() {
    final msgs = _thread?.messages;
    if (msgs != null) {
      for (var i = msgs.length - 1; i >= 0; i--) {
        final cs = msgs[i].metadata['client_state'];
        if (cs is Map && cs['study_context'] is Map) {
          return Map<String, dynamic>.from(cs['study_context'] as Map);
        }
      }
    }
    final proj = _effectiveProject();
    if (proj != null && proj['study_context'] is Map) {
      return Map<String, dynamic>.from(proj['study_context'] as Map);
    }
    return null;
  }

  /// Si une réponse est en cours, le prompt entrant est placé dans le champ de saisie
  /// au lieu d'être abandonné en silence.
  void _sendOrKeep(String prompt) {
    if (_loading) {
      setState(() => _controller.text = prompt);
      return;
    }
    _sendMessage(prompt);
  }

  Future<void> _sendMessage(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty || _loading) return;

    if (widget.onRequireAuth != null &&
        !widget.apiService.isAuthenticated &&
        !widget.apiService.hasExplicitPremiumKey) {
      final authenticated = await widget.onRequireAuth!();
      if (!mounted || !authenticated) {
        if (mounted && _controller.text.trim().isEmpty) {
          _controller.text = trimmed;
        }
        return;
      }
    }

    if (_thread == null) {
      _thread = await LocalConversationStorage.instance.createConversation();
      if (!mounted) return;
    }

    _lastPrompt = trimmed;
    _controller.clear();

    final userMessage = ChatMessage.user(trimmed);
    final currentThread = _thread!;
    final targetThreadId = currentThread.id;
    final updatedMessages = [...currentThread.messages, userMessage];

    final nextTitle = currentThread.title == 'Nouvelle conversation'
        ? _titleFromPrompt(trimmed)
        : currentThread.title;

    final updatedThread = currentThread.copyWith(
      title: nextTitle,
      updatedAt: DateTime.now(),
      messages: updatedMessages,
    );

    setState(() {
      _thread = updatedThread;
      _loading = true;
    });
    _scrollToBottom();
    await _safeSave(updatedThread);
    widget.onConversationUpdated?.call();

    try {
      final validPrevious = currentThread.messages
          .where((m) => m.metadata['error'] != true && m.text.trim().isNotEmpty)
          .toList();
      final historySlice = validPrevious.length > 8
          ? validPrevious.sublist(validPrevious.length - 8)
          : validPrevious;
      final recentHistory = historySlice
          .map((m) => <String, String>{
                'role': m.role == 'assistant' ? 'assistant' : 'user',
                'content': m.text,
              })
          .toList();

      final activePid = _activeProjectId();
      final tierVal = widget.apiService.hasPremiumKey ? 'premium' : 'free';
      Map<String, dynamic> response = const {};
      if (_selectedDomain == 'auto') {
        final streamedBuffer = StringBuffer();
        await for (final evt in widget.apiService.streamChatMessage(
          trimmed,
          history: recentHistory,
          tier: tierVal,
          studyContext: _latestStudyContext(),
          projectId: activePid,
        )) {
          if (!mounted) return;
          final evtName = evt['event']?.toString() ?? '';
          final evtData = evt['data'];
          if (evtName == 'delta' && evtData is Map && evtData['text'] != null) {
            streamedBuffer.write(evtData['text'].toString());
            final partialMsg = ChatMessage.assistant(
              text: streamedBuffer.toString(),
              sources: const [],
              metadata: const {'streaming': true, 'error': false},
            );
            setState(() {
              _thread = updatedThread.copyWith(
                updatedAt: DateTime.now(),
                messages: [...updatedMessages, partialMsg],
              );
            });
            _scrollToBottom();
          } else if (evtName == 'done' && evtData is Map) {
            response = Map<String, dynamic>.from(evtData);
          }
        }
        if (response.isEmpty) {
          response = await widget.apiService.sendChatMessage(
            trimmed,
            history: recentHistory,
            tier: tierVal,
            studyContext: _latestStudyContext(),
            projectId: activePid,
          );
        }
      } else {
        response = await widget.apiService.sendPlatformChatMessage(
          trimmed,
          domain: _selectedDomain,
          history: recentHistory,
          tier: tierVal,
          studyContext: _latestStudyContext(),
          projectId: activePid,
        );
      }

      final raw = Map<String, dynamic>.from(response);
      final reply = raw['reply']?.toString() ??
          raw['message']?.toString() ??
          'Réponse reçue.';

      final assistantMessage = ChatMessage.assistant(
        text: reply,
        sources: _extractSources(raw),
        metadata: {
          'intent': raw['intent'] ?? '',
          'summary': raw['summary'] ?? raw['analysis'],
          'table': raw['table'] ?? raw['data'] ?? raw['results'],
          'chart': raw['chart'] ?? raw['chart_data'],
          if (raw['client_state'] is Map) 'client_state': raw['client_state'],
          if (raw['follow_ups'] is List) 'follow_ups': raw['follow_ups'],
          if (raw['disclaimer'] != null)
            'disclaimer': raw['disclaimer'].toString(),
          'error': false,
        },
      );

      final finalThread = updatedThread.copyWith(
        updatedAt: DateTime.now(),
        messages: [...updatedMessages, assistantMessage],
      );

      await _safeSave(finalThread);
      widget.onConversationUpdated?.call();

      // Resynchroniser automatiquement le StudyContext mis à jour dans le projet actif (silencieux)
      final effProj = _effectiveProject();
      final pid = finalThread.projectId ?? effProj?['project_id']?.toString();
      final newCtx = raw['client_state'] is Map
          ? (raw['client_state'] as Map)['study_context']
          : null;
      if (pid != null &&
          pid.isNotEmpty &&
          newCtx is Map &&
          widget.apiService.hasPremiumKey) {
        final ctxMap = Map<String, dynamic>.from(newCtx);
        widget.apiService
            .updateProject(pid, studyContext: ctxMap)
            .then((updatedProj) {
          if (mounted && _loadedProjectId == pid) {
            setState(() => _loadedProject = updatedProj);
          }
        }).catchError((_) {});
      }

      if (!mounted) return;
      if (_thread?.id == targetThreadId) {
        setState(() {
          _thread = finalThread;
          _loading = false;
        });
        _scrollToBottom();
      }
    } catch (e) {
      final errorText = e.toString().contains('429')
          ? 'Trop de messages envoyés en peu de temps. Veuillez patienter une minute.'
          : (kDebugMode
              ? 'Erreur : $e'
              : 'Une erreur est survenue lors de la communication avec le serveur. Veuillez réessayer.');

      final errorMessage = ChatMessage.assistant(
        text: errorText,
        metadata: {'error': true},
      );

      final finalThread = updatedThread.copyWith(
        updatedAt: DateTime.now(),
        messages: [...updatedMessages, errorMessage],
      );

      await _safeSave(finalThread);
      widget.onConversationUpdated?.call();
      if (!mounted) return;
      if (_thread?.id == targetThreadId) {
        setState(() {
          _thread = finalThread;
          _loading = false;
        });
        _scrollToBottom();
      }
    }
  }

  Future<void> _toggleSaveLibrary() async {
    if (_thread == null || _thread!.messages.isEmpty) return;
    final next = !_thread!.isSavedInLibrary;
    final updated =
        _thread!.copyWith(isSavedInLibrary: next, updatedAt: DateTime.now());
    setState(() => _thread = updated);
    await LocalConversationStorage.instance.saveConversation(updated);
    widget.onConversationUpdated?.call();

    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(next
            ? 'Conversation ajoutée à la Library'
            : 'Conversation retirée de la Library'),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  Widget _buildActiveProjectBanner() {
    final proj = _effectiveProject();
    if (proj == null) return const SizedBox.shrink();
    final name = proj['name']?.toString().trim() ?? 'Projet PRO';
    final ctx = proj['study_context'];
    final chips = <String>[];
    if (ctx is Map) {
      final prod = ctx['product_activity'];
      if (prod is Map &&
          (prod['commodity']?.toString().trim().isNotEmpty ?? false)) {
        chips.add(commodityLabelFr(prod['commodity'].toString()));
      }
      final geo = ctx['geography'];
      if (geo is Map) {
        final orig = geo['origin_province']?.toString().trim() ?? '';
        final dest = geo['dest_province']?.toString().trim() ?? '';
        if (orig.isNotEmpty && dest.isNotEmpty) {
          chips.add('$orig → $dest');
        } else if (orig.isNotEmpty) {
          chips.add(orig);
        }
      }
      final bud = ctx['budget_and_assumptions'];
      if (bud is Map && bud['capital_xaf'] is num) {
        chips.add('${formatXaf((bud['capital_xaf'] as num).toDouble())} FCFA');
      }
    }
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: const BoxDecoration(
        color: FDTheme.blueSoft,
        border: Border(bottom: BorderSide(color: FDTheme.line)),
      ),
      child: Row(
        children: [
          const Icon(Icons.folder_special_rounded,
              size: 16, color: FDTheme.blue),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              chips.isEmpty
                  ? 'Projet actif : $name'
                  : 'Projet : $name · ${chips.join(' · ')}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w600,
                color: FDTheme.ink,
              ),
            ),
          ),
          if (widget.onOpenProjects != null)
            TextButton(
              onPressed: widget.onOpenProjects,
              style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                minimumSize: const Size(0, 28),
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              child: const Text(
                'Ouvrir le dossier',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
              ),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final messages = _thread?.messages ?? const <ChatMessage>[];

    return ColoredBox(
      color: Colors.white,
      child: Column(
        children: [
          _buildActiveProjectBanner(),
          Expanded(
            child: messages.isEmpty
                ? _buildEmptyState()
                : _buildConversationState(messages),
          ),
          _buildInputBar(messages),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    final activeProj = _effectiveProject();
    final isPro = widget.apiService.hasPremiumKey;
    final actions = isPro
        ? <_QuickAction>[..._quickActions.take(3), _proQuickAction]
        : _quickActions;

    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Text(
                activeProj != null
                    ? 'Projet « ${activeProj['name'] ?? 'PRO'} »'
                    : 'Que souhaitez-vous analyser ?',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w700,
                  letterSpacing: -0.4,
                  color: FDTheme.ink,
                ),
              ),
              if (activeProj != null) ...[
                const SizedBox(height: 8),
                const Text(
                  'Vos paramètres métier et documents de ce dossier sont pris en compte automatiquement.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 13.5,
                    color: FDTheme.muted,
                    height: 1.4,
                  ),
                ),
              ],
              const SizedBox(height: 24),
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 10,
                runSpacing: 10,
                children: [
                  for (var i = 0; i < actions.length; i++)
                    _buildQuickActionButton(
                      actions[i],
                      isPro: isPro && i == actions.length - 1,
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildQuickActionButton(_QuickAction action, {bool isPro = false}) {
    return Material(
      color: isPro ? FDTheme.greenSoft : FDTheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(20),
        side: BorderSide(
            color: isPro ? FDTheme.greenBorder : FDTheme.line, width: 1),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: () => _sendMessage(action.prompt),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 9),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(action.icon,
                  size: 16, color: isPro ? FDTheme.green : FDTheme.blue),
              const SizedBox(width: 7),
              Flexible(
                child: Text(
                  action.label,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w500,
                    color: isPro ? FDTheme.greenDark : FDTheme.ink,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildConversationState(List<ChatMessage> messages) {
    final isSaved = _thread?.isSavedInLibrary ?? false;
    final lastAssistantIndex = messages.lastIndexWhere((m) => m.role != 'user');

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 820),
        child: ListView.builder(
          controller: _scrollController,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          itemCount: messages.length + (_loading ? 1 : 0),
          itemBuilder: (context, index) {
            if (index == messages.length && _loading) {
              return const LoadingIndicator();
            }
            final msg = messages[index];
            if (msg.role == 'user') {
              return UserMessageBubble(message: msg);
            } else {
              return AssistantMessage(
                message: msg,
                isSavedInLibrary: isSaved,
                showSaveButton: index == lastAssistantIndex,
                onRetry: _lastPrompt != null
                    ? () => _sendMessage(_lastPrompt!)
                    : null,
                onSaveToLibrary: _toggleSaveLibrary,
              );
            }
          },
        ),
      ),
    );
  }

  Future<void> _exportMarketStudyPdf(
      Map<String, dynamic> kp, List<String> instructions) async {
    final comm = kp['commodity']?.toString() ?? '';
    final orig = kp['origin_province']?.toString() ?? '';
    final cap = (kp['capital_xaf'] as num?)?.toDouble() ?? 0;
    if (comm.isEmpty || orig.isEmpty || cap <= 0) return;

    final effProj = _effectiveProject();
    final activePid = _thread?.projectId ?? effProj?['project_id']?.toString();

    ScaffoldMessenger.maybeOf(context)
      ?..clearSnackBars()
      ..showSnackBar(SnackBar(
          content: Text(activePid != null && activePid.isNotEmpty
              ? 'Génération et enregistrement du PDF PRO dans le projet...'
              : 'Génération du dossier PDF PRO en cours...')));
    try {
      if (activePid != null && activePid.isNotEmpty) {
        final created = await widget.apiService.createProjectStudy(
          activePid,
          commodity: comm,
          originProvince: orig,
          destProvince: kp['dest_province']?.toString(),
          capitalXaf: cap,
          promoterName: kp['promoter_name']?.toString(),
        );
        final studyId = created['study_id']?.toString() ?? '';
        final vNum = (created['version_number'] as num?)?.toInt() ?? 1;
        if (studyId.isNotEmpty) {
          final bytes = await widget.apiService
              .downloadStudyVersionPdf(activePid, studyId, vNum);
          triggerPdfDownload(bytes, 'freedata_${studyId}_v$vNum.pdf');
        }
        widget.onConversationUpdated?.call();
        if (!mounted) return;
        ScaffoldMessenger.maybeOf(context)
          ?..clearSnackBars()
          ..showSnackBar(SnackBar(
              content: Text(
                  'Étude PDF enregistrée dans le projet (v$vNum) et téléchargée.')));
      } else {
        final bytes = await widget.apiService.downloadMarketStudyPdf(
          commodity: comm,
          originProvince: orig,
          destProvince: kp['dest_province']?.toString(),
          capitalXaf: cap,
          transportCostPerKg: (kp['transport_cost_per_kg'] as num?)?.toDouble(),
          promoterName: kp['promoter_name']?.toString(),
          userInstructions: instructions,
          studyContext: _latestStudyContext(),
        );
        final slug = comm.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), '_');
        triggerPdfDownload(bytes, 'freedata_etude_$slug.pdf');
        if (!mounted) return;
        ScaffoldMessenger.maybeOf(context)
          ?..clearSnackBars()
          ..showSnackBar(
              const SnackBar(content: Text('Étude PDF PRO téléchargée.')));
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.maybeOf(context)
        ?..clearSnackBars()
        ..showSnackBar(SnackBar(content: Text(errText(e))));
    }
  }

  String _selectedDomainLabel() {
    for (final item in _domainChoices) {
      if (item['id'] == _selectedDomain) return item['label'] ?? 'Auto';
    }
    return 'Auto';
  }

  Widget _buildInputBar(List<ChatMessage> messages) {
    final lastAssistant = messages.isNotEmpty && !_loading
        ? messages.lastWhere(
            (m) => m.role == 'assistant' && m.metadata['error'] != true,
            orElse: () => ChatMessage.assistant(text: ''),
          )
        : null;
    final rawFollowUps = lastAssistant?.metadata['follow_ups'];
    final followUps = rawFollowUps is List
        ? rawFollowUps
            .map((e) => e.toString())
            .where((s) => s.trim().isNotEmpty)
            .take(3)
            .toList()
        : <String>[];
    final stateMap = lastAssistant?.metadata['client_state'] is Map
        ? Map<String, dynamic>.from(
            lastAssistant!.metadata['client_state'] as Map)
        : const <String, dynamic>{};
    final kp = stateMap['known_params'] is Map
        ? Map<String, dynamic>.from(stateMap['known_params'] as Map)
        : const <String, dynamic>{};
    final instructions = stateMap['user_instructions'] is List
        ? (stateMap['user_instructions'] as List)
            .map((e) => e.toString())
            .toList()
        : <String>[];
    final canExportPdf = widget.apiService.hasPremiumKey &&
        kp['commodity'] != null &&
        kp['origin_province'] != null &&
        kp['capital_xaf'] != null;

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Container(
            decoration: BoxDecoration(
              color: FDTheme.surface,
              border: Border.all(color: FDTheme.borderStrong, width: 1),
              borderRadius: BorderRadius.circular(24),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x0C0F172A),
                  blurRadius: 14,
                  offset: Offset(0, 3),
                ),
              ],
            ),
            padding: const EdgeInsets.fromLTRB(16, 8, 10, 8),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (_userDocuments.isNotEmpty) ...[
                  SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(
                      children: _userDocuments.take(6).map((doc) {
                        final docId = doc['doc_id']?.toString() ?? '';
                        final fname =
                            doc['filename']?.toString() ?? 'Document.pdf';
                        return Padding(
                          padding: const EdgeInsets.only(right: 6),
                          child: Container(
                            padding: const EdgeInsets.fromLTRB(9, 4, 4, 4),
                            decoration: BoxDecoration(
                              color: FDTheme.blueSoft,
                              borderRadius: BorderRadius.circular(99),
                              border: Border.all(
                                  color: FDTheme.blue.withValues(alpha: 0.25)),
                            ),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Icon(Icons.description_outlined,
                                    size: 13.5, color: FDTheme.blue),
                                const SizedBox(width: 5),
                                ConstrainedBox(
                                  constraints:
                                      const BoxConstraints(maxWidth: 160),
                                  child: Text(
                                    fname,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      fontSize: 11.5,
                                      fontWeight: FontWeight.w600,
                                      color: FDTheme.blueDark,
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 2),
                                InkWell(
                                  borderRadius: BorderRadius.circular(99),
                                  onTap: () =>
                                      _deleteUserDocument(docId, fname),
                                  child: const Padding(
                                    padding: EdgeInsets.all(2),
                                    child: Icon(Icons.close_rounded,
                                        size: 14, color: FDTheme.blueDark),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        );
                      }).toList(),
                    ),
                  ),
                ],
                TextField(
                  controller: _controller,
                  minLines: 1,
                  maxLines: 5,
                  textInputAction: TextInputAction.send,
                  inputFormatters: [
                    LengthLimitingTextInputFormatter(4000),
                  ],
                  style: const TextStyle(
                    color: FDTheme.ink,
                    fontSize: 15.5,
                    height: 1.45,
                  ),
                  onSubmitted: (_) {
                    if (!_loading) _sendMessage(_controller.text);
                  },
                  decoration: const InputDecoration(
                    hintText: 'Posez une question ou joignez un document…',
                    hintStyle: TextStyle(
                      color: FDTheme.subtle,
                      fontSize: 15,
                    ),
                    filled: false,
                    hoverColor: Colors.transparent,
                    border: InputBorder.none,
                    enabledBorder: InputBorder.none,
                    focusedBorder: InputBorder.none,
                    disabledBorder: InputBorder.none,
                    errorBorder: InputBorder.none,
                    focusedErrorBorder: InputBorder.none,
                    isDense: true,
                    contentPadding: EdgeInsets.symmetric(vertical: 8),
                  ),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    // Bouton Joindre un document privé (PDF / CSV / TXT / MD / JSON)
                    Tooltip(
                      message: 'Joindre un document privé (PDF, CSV, TXT, MD)',
                      child: InkWell(
                        borderRadius: BorderRadius.circular(99),
                        onTap: _uploadingDoc ? null : _handleAttachDocument,
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 9, vertical: 6),
                          decoration: BoxDecoration(
                            color: _userDocuments.isNotEmpty
                                ? FDTheme.blueSoft
                                : FDTheme.canvasSoft,
                            borderRadius: BorderRadius.circular(99),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (_uploadingDoc)
                                const SizedBox(
                                  width: 13,
                                  height: 13,
                                  child:
                                      CircularProgressIndicator(strokeWidth: 2),
                                )
                              else
                                Icon(
                                  Icons.attach_file_rounded,
                                  size: 15,
                                  color: _userDocuments.isNotEmpty
                                      ? FDTheme.blue
                                      : FDTheme.ink,
                                ),
                              if (_userDocuments.isNotEmpty) ...[
                                const SizedBox(width: 3),
                                Text(
                                  '${_userDocuments.length}',
                                  style: const TextStyle(
                                    fontSize: 11.5,
                                    fontWeight: FontWeight.w700,
                                    color: FDTheme.blue,
                                  ),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 6),
                    // Sélecteur de domaine compact (style ChatGPT / Claude)
                    PopupMenuButton<String>(
                      tooltip: 'Choisir le domaine IA',
                      onSelected: _setSelectedDomain,
                      itemBuilder: (_) => _domainChoices
                          .map((d) => PopupMenuItem<String>(
                                value: d['id']!,
                                child: Row(
                                  children: [
                                    Icon(
                                      _selectedDomain == d['id']
                                          ? Icons.check_rounded
                                          : Icons.circle_outlined,
                                      size: 16,
                                      color: _selectedDomain == d['id']
                                          ? FDTheme.blue
                                          : FDTheme.subtle,
                                    ),
                                    const SizedBox(width: 8),
                                    Text(d['label'] ?? 'Auto'),
                                  ],
                                ),
                              ))
                          .toList(),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 10, vertical: 6),
                        decoration: BoxDecoration(
                          color: FDTheme.canvasSoft,
                          borderRadius: BorderRadius.circular(99),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.auto_awesome_outlined,
                                size: 14, color: FDTheme.blue),
                            const SizedBox(width: 5),
                            Text(
                              _selectedDomainLabel(),
                              style: const TextStyle(
                                  fontSize: 12.5,
                                  fontWeight: FontWeight.w600,
                                  color: FDTheme.ink),
                            ),
                            const SizedBox(width: 2),
                            const Icon(Icons.keyboard_arrow_down_rounded,
                                size: 16, color: FDTheme.muted),
                          ],
                        ),
                      ),
                    ),
                    if (followUps.isNotEmpty) ...[
                      const SizedBox(width: 6),
                      PopupMenuButton<String>(
                        tooltip: 'Suggestions de suite',
                        onSelected: _sendMessage,
                        itemBuilder: (_) => followUps
                            .map((p) => PopupMenuItem<String>(
                                  value: p,
                                  child: Text(p,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis),
                                ))
                            .toList(),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 10, vertical: 6),
                          decoration: BoxDecoration(
                            color: FDTheme.canvasSoft,
                            borderRadius: BorderRadius.circular(99),
                          ),
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.lightbulb_outline_rounded,
                                  size: 14, color: FDTheme.muted),
                              SizedBox(width: 4),
                              Text('Suite',
                                  style: TextStyle(
                                      fontSize: 12.5,
                                      fontWeight: FontWeight.w600,
                                      color: FDTheme.ink)),
                            ],
                          ),
                        ),
                      ),
                    ],
                    if (canExportPdf) ...[
                      const SizedBox(width: 6),
                      InkWell(
                        borderRadius: BorderRadius.circular(99),
                        onTap: () => _exportMarketStudyPdf(kp, instructions),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 10, vertical: 6),
                          decoration: BoxDecoration(
                            color: FDTheme.blueSoft,
                            borderRadius: BorderRadius.circular(99),
                          ),
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.picture_as_pdf_outlined,
                                  size: 14, color: FDTheme.blue),
                              SizedBox(width: 4),
                              Text('PDF PRO',
                                  style: TextStyle(
                                      fontSize: 12.5,
                                      fontWeight: FontWeight.w700,
                                      color: FDTheme.blue)),
                            ],
                          ),
                        ),
                      ),
                    ],
                    IconButton(
                      tooltip: 'Envoyer le message',
                      onPressed: _loading
                          ? null
                          : () => _sendMessage(_controller.text),
                      icon: const Icon(Icons.arrow_upward_rounded, size: 20),
                      style: IconButton.styleFrom(
                        backgroundColor: FDTheme.blue,
                        foregroundColor: Colors.white,
                        disabledBackgroundColor: FDTheme.line,
                        disabledForegroundColor: FDTheme.subtle,
                        shape: const CircleBorder(),
                        padding: const EdgeInsets.all(8),
                        minimumSize: const Size(36, 36),
                      ),
                    ),
                  ],
                ),
                if (_selectedDomain != 'auto' &&
                    _selectedDomain != 'markets_and_prices' &&
                    _selectedDomain != 'agriculture') ...[
                  const SizedBox(height: 4),
                  const Align(
                    alignment: Alignment.centerLeft,
                    child: Text(
                      'Domaine Tchad en préparation : analyse basée sur vos documents privés et les données Marchés & Prix disponibles.',
                      style: TextStyle(fontSize: 10.5, color: FDTheme.subtle),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
