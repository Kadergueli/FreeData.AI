import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../core/fd_theme.dart';
import '../core/models/chat_models.dart';
import '../services/api_service.dart';
import '../services/conversation_storage.dart';
import '../widgets/chat/chat_widgets.dart';

class ChatScreen extends StatefulWidget {
  final ApiService apiService;
  final String? conversationId;
  final VoidCallback? onConversationUpdated;
  final String? initialPrompt;
  final VoidCallback? onPromptHandled;

  const ChatScreen({
    super.key,
    required this.apiService,
    this.conversationId,
    this.onConversationUpdated,
    this.initialPrompt,
    this.onPromptHandled,
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
  String? _lastPrompt;

  static const List<_QuickAction> _quickActions = [
    _QuickAction(
      icon: Icons.show_chart_rounded,
      label: "Prévision Mil · N'Djamena",
      prompt: "Quelle est la prévision du prix du mil à N'Djamena ?",
    ),
    _QuickAction(
      icon: Icons.shield_outlined,
      label: "Crédit 3M FCFA · Salamat",
      prompt: "Évalue le risque de financer 3 millions de FCFA de mil au Salamat.",
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

  static const List<_QuickAction> _proQuickActions = [
    _QuickAction(
      icon: Icons.calendar_month_rounded,
      label: "Saisonnalité & Stockage · Mil",
      prompt: "Quel est le meilleur mois pour acheter, stocker et revendre du mil au Salamat ?",
    ),
    _QuickAction(
      icon: Icons.radar_rounded,
      label: "Radar Anomalies & Qualité",
      prompt: "Quelles sont les anomalies de prix ou séries figées récentes sur les marchés ?",
    ),
  ];

  @override
  void initState() {
    super.initState();
    // Pré-réveil silencieux Render (partagé via le cache getMetadata)
    widget.apiService.getMetadata().catchError((_) => <String, dynamic>{});
    _loadConversation(widget.conversationId);

    if (widget.initialPrompt != null && widget.initialPrompt!.isNotEmpty) {
      final promptToSend = widget.initialPrompt!;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        widget.onPromptHandled?.call();
        _sendMessage(promptToSend);
      });
    }
  }

  @override
  void didUpdateWidget(covariant ChatScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
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
        _sendMessage(promptToSend);
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
    if (id != null && _thread?.id == id && (_thread?.messages.isNotEmpty ?? false)) {
      return;
    }

    if (_thread != null && id != _thread!.id) {
      _lastPrompt = null;
      if (widget.initialPrompt == null || widget.initialPrompt!.isEmpty) {
        _controller.clear();
      }
    }

    setState(() {
      _loading = false;
    });

    if (id != null) {
      final found = await LocalConversationStorage.instance.getConversation(id);
      if (!mounted || widget.conversationId != id) return;
      if (_thread?.id == id && (_thread?.messages.isNotEmpty ?? false)) return;

      if (found != null) {
        setState(() => _thread = found);
        _scrollToBottom();
        return;
      }

      final now = DateTime.now();
      setState(() {
        _thread = ConversationThread(
          id: id,
          title: 'Nouvelle conversation',
          createdAt: now,
          updatedAt: now,
        );
      });
      return;
    }

    // Sinon, charger la plus récente active ou préparer un brouillon vide en mémoire
    final conversations = await LocalConversationStorage.instance.loadConversations();
    if (!mounted || widget.conversationId != null) return;

    if (conversations.isNotEmpty) {
      setState(() => _thread = conversations.first);
    } else {
      final draft = await LocalConversationStorage.instance.createConversation();
      if (!mounted || widget.conversationId != null) return;
      setState(() => _thread = draft);
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
    final rawSources = response['sources'];
    if (rawSources is List) {
      return rawSources.map((item) => Map<String, dynamic>.from(item as Map)).toList();
    }
    final metadataSources = response['metadata'];
    if (metadataSources is Map && metadataSources['sources'] is List) {
      return (metadataSources['sources'] as List)
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();
    }
    return const [];
  }

  Future<void> _sendMessage(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty || _loading) return;

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
    await LocalConversationStorage.instance.saveConversation(updatedThread);
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

      final response = await widget.apiService.sendChatMessage(
        trimmed,
        history: recentHistory,
        tier: widget.apiService.hasPremiumKey ? 'premium' : 'free',
      );

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
          if (raw['disclaimer'] != null) 'disclaimer': raw['disclaimer'].toString(),
          'error': false,
        },
      );

      final finalThread = updatedThread.copyWith(
        updatedAt: DateTime.now(),
        messages: [...updatedMessages, assistantMessage],
      );

      await LocalConversationStorage.instance.saveConversation(finalThread);
      widget.onConversationUpdated?.call();
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

      await LocalConversationStorage.instance.saveConversation(finalThread);
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
    final updated = _thread!.copyWith(isSavedInLibrary: next, updatedAt: DateTime.now());
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

  @override
  Widget build(BuildContext context) {
    final messages = _thread?.messages ?? const <ChatMessage>[];

    return ColoredBox(
      color: Colors.white,
      child: Column(
        children: [
          Expanded(
            child: messages.isEmpty
                ? _buildEmptyState()
                : _buildConversationState(messages),
          ),
          _buildInputBar(),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              const Text(
                'Que souhaitez-vous analyser ?',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  color: FDTheme.ink,
                ),
              ),
              const SizedBox(height: 18),
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 8,
                runSpacing: 8,
                children: [
                  ..._quickActions.map((a) => _buildQuickActionButton(a)),
                  if (widget.apiService.hasPremiumKey)
                    ..._proQuickActions.map((a) => _buildQuickActionButton(a, isPro: true)),
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
        side: BorderSide(color: isPro ? FDTheme.greenBorder : FDTheme.line, width: 1),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: () => _sendMessage(action.prompt),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 9),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(action.icon, size: 16, color: isPro ? FDTheme.green : FDTheme.blue),
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
                onRetry: _lastPrompt != null ? () => _sendMessage(_lastPrompt!) : null,
                onSaveToLibrary: _toggleSaveLibrary,
              );
            }
          },
        ),
      ),
    );
  }

  Widget _buildInputBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 820),
          child: Container(
            decoration: BoxDecoration(
              color: FDTheme.canvas,
              border: Border.all(color: FDTheme.borderStrong, width: 1),
              borderRadius: BorderRadius.circular(26),
            ),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    minLines: 1,
                    maxLines: 4,
                    textInputAction: TextInputAction.send,
                    inputFormatters: [
                      LengthLimitingTextInputFormatter(1000),
                    ],
                    style: const TextStyle(
                      color: FDTheme.ink,
                      fontSize: 16,
                      height: 1.45,
                    ),
                    onSubmitted: (_) {
                      if (!_loading) _sendMessage(_controller.text);
                    },
                    decoration: const InputDecoration(
                      hintText: 'Interroger un marché, un produit ou un risque...',
                      hintStyle: TextStyle(
                        color: FDTheme.subtle,
                        fontSize: 15.5,
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
                      contentPadding: EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: IconButton(
                    onPressed: _loading ? null : () => _sendMessage(_controller.text),
                    icon: const Icon(Icons.arrow_upward_rounded, size: 22),
                    style: IconButton.styleFrom(
                      backgroundColor: FDTheme.blue,
                      foregroundColor: Colors.white,
                      disabledBackgroundColor: FDTheme.line,
                      disabledForegroundColor: FDTheme.subtle,
                      shape: const CircleBorder(),
                      padding: const EdgeInsets.all(10),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
