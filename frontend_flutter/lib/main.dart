import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'core/fd_theme.dart';
import 'services/api_service.dart';
import 'services/conversation_storage.dart';
import 'screens/chat_screen.dart';
import 'screens/explore_screen.dart';
import 'screens/library_screen.dart';
import 'screens/analytics_screen.dart';
import 'screens/docs_screen.dart';
import 'screens/forecast_screen.dart';
import 'screens/passport_screen.dart';
import 'screens/projects_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/subscription_screen.dart';
import 'screens/support_screen.dart';

void main() => runApp(const FreeDataAIApp());

class FreeDataAIApp extends StatelessWidget {
  const FreeDataAIApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'FreeData.AI',
      debugShowCheckedModeBanner: false,
      theme: FDTheme.light(),
      home: const MainShell(),
    );
  }
}

class MainShell extends StatefulWidget {
  final Uri? initialUri;
  final ApiService? apiService;
  const MainShell({super.key, this.initialUri, this.apiService});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  static const String _premiumKeyStorageKey = 'fd_ai_premium_key_v1';

  int _selectedIndex = 0;
  final Set<int> _visitedTabs = {0};
  late final ApiService _apiService = widget.apiService ?? ApiService();
  String? _activeConversationId;
  String? _pendingPrompt;
  List<ConversationThread> _conversations = const [];

  @override
  void initState() {
    super.initState();
    _loadPremiumKey();
    _reloadConversations();
  }

  void _showSnackBar(SnackBar snackBar) {
    ScaffoldMessenger.maybeOf(context)
      ?..clearSnackBars()
      ..showSnackBar(snackBar);
  }

  void _showSnackBarAfterFrame(SnackBar snackBar) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _showSnackBar(snackBar);
    });
  }

  Future<void> _loadPremiumKey() async {
    final uri = widget.initialUri ?? Uri.base;
    final urlKey = (uri.queryParameters['key'] ?? uri.queryParameters['premium_key'])?.trim();
    final prefs = await SharedPreferences.getInstance();
    if (urlKey != null && urlKey.isNotEmpty) {
      try {
        final isValid = await _apiService.verifyPremiumKey(urlKey);
        if (isValid) {
          await prefs.setString(_premiumKeyStorageKey, urlKey);
          _apiService.setRuntimePremiumKey(urlKey);
          if (mounted) setState(() {});
        } else {
          await prefs.remove(_premiumKeyStorageKey);
          _apiService.setRuntimePremiumKey(null);
          if (mounted) setState(() {});
          _showSnackBarAfterFrame(
            const SnackBar(
              backgroundColor: FDTheme.danger,
              content: Text('Clé d’accès refusée : clé invalide.'),
              duration: Duration(seconds: 3),
            ),
          );
        }
      } on ApiHttpException catch (e) {
        _apiService.setRuntimePremiumKey(null);
        if (mounted) setState(() {});
        _showSnackBarAfterFrame(
          SnackBar(
            backgroundColor: FDTheme.danger,
            content: Text(e.message),
            duration: const Duration(seconds: 4),
          ),
        );
      } catch (_) {
        _apiService.setRuntimePremiumKey(null);
        if (mounted) setState(() {});
        _showSnackBarAfterFrame(
          const SnackBar(
            backgroundColor: FDTheme.danger,
            content: Text(
              'Serveur momentanément injoignable pour vérifier la clé. Réessayez dans quelques instants.',
            ),
            duration: Duration(seconds: 3),
          ),
        );
      }
      return;
    }

    final saved = prefs.getString(_premiumKeyStorageKey);
    if (saved != null && saved.trim().isNotEmpty) {
      try {
        final isValid = await _apiService.verifyPremiumKey(saved);
        if (isValid) {
          _apiService.setRuntimePremiumKey(saved);
          if (mounted) setState(() {});
        } else {
          await prefs.remove(_premiumKeyStorageKey);
          _apiService.setRuntimePremiumKey(null);
          if (mounted) setState(() {});
        }
      } on ApiHttpException catch (e) {
        _apiService.setRuntimePremiumKey(null);
        if (mounted) setState(() {});
        _showSnackBarAfterFrame(
          SnackBar(
            backgroundColor: FDTheme.danger,
            content: Text(e.message),
            duration: const Duration(seconds: 4),
          ),
        );
      } catch (_) {
        _apiService.setRuntimePremiumKey(null);
        if (mounted) setState(() {});
      }
    }
  }

  Future<void> _configurePremiumKey() async {
    final action = await showDialog<String>(
      context: context,
      builder: (_) => _PremiumKeyDialog(
        initialKey: _apiService.activePremiumKey,
        hasActiveKey: _apiService.hasPremiumKey,
      ),
    );
    if (action == null) return;

    final prefs = await SharedPreferences.getInstance();
    if (action.isEmpty) {
      await prefs.remove(_premiumKeyStorageKey);
      _apiService.setRuntimePremiumKey(null);
      if (!mounted) return;
      setState(() {});
      _showSnackBar(
        const SnackBar(
          content: Text('Accès standard rétabli'),
          duration: Duration(seconds: 2),
        ),
      );
      return;
    }

    try {
      final isValid = await _apiService.verifyPremiumKey(action);
      if (!mounted) return;
      if (isValid) {
        await prefs.setString(_premiumKeyStorageKey, action);
        _apiService.setRuntimePremiumKey(action);
        if (!mounted) return;
        setState(() {});
        _showSnackBar(
          const SnackBar(
            backgroundColor: FDTheme.greenDark,
            content: Text('Clé vérifiée : Accès Partenaire activé'),
            duration: Duration(seconds: 2),
          ),
        );
      } else {
        _showSnackBar(
          const SnackBar(
            backgroundColor: FDTheme.danger,
            content: Text(
              'Clé d’accès refusée : seule la clé configurée sur le serveur est valide.',
            ),
            duration: Duration(seconds: 3),
          ),
        );
      }
    } on ApiHttpException catch (e) {
      if (!mounted) return;
      _showSnackBar(
        SnackBar(
          backgroundColor: FDTheme.danger,
          content: Text(e.message),
          duration: const Duration(seconds: 4),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      _showSnackBar(
        const SnackBar(
          backgroundColor: FDTheme.danger,
          content: Text(
            'Impossible de vérifier la clé auprès du serveur. Réessayez dans quelques instants.',
          ),
          duration: Duration(seconds: 3),
        ),
      );
    }
  }

  void _selectTab(int index) {
    setState(() {
      _selectedIndex = index;
      _visitedTabs.add(index);
    });
  }

  Future<void> _reloadConversations() async {
    final activeAtStart = _activeConversationId;
    final wasSaved = activeAtStart != null &&
        _conversations.any((c) => c.id == activeAtStart);
    final list = await LocalConversationStorage.instance.loadConversations();
    if (!mounted) return;

    String? replacementId;
    final shouldReplace = wasSaved && !list.any((c) => c.id == activeAtStart);
    if (shouldReplace) {
      if (list.isNotEmpty) {
        replacementId = list.first.id;
      } else {
        final draft = await LocalConversationStorage.instance.createConversation();
        if (!mounted) return;
        replacementId = draft.id;
      }
    }

    setState(() {
      _conversations = list;
      if (_activeConversationId == activeAtStart) {
        if (shouldReplace) {
          _activeConversationId = replacementId;
        } else if (_activeConversationId == null && list.isNotEmpty) {
          _activeConversationId = list.first.id;
        }
      }
    });
  }

  Future<void> _createNewConversation() async {
    final newThread = await LocalConversationStorage.instance.createConversation();
    if (!mounted) return;
    setState(() {
      _selectedIndex = 0;
      _visitedTabs.add(0);
      _activeConversationId = newThread.id;
      _pendingPrompt = null;
    });
    await _reloadConversations();
  }

  Future<void> _openPromptInChat(String prompt) async {
    final newThread = await LocalConversationStorage.instance.createConversation();
    if (!mounted) return;
    setState(() {
      _selectedIndex = 0;
      _visitedTabs.add(0);
      _activeConversationId = newThread.id;
      _pendingPrompt = prompt;
    });
    await _reloadConversations();
  }

  Future<void> _renameConversation(String id, String currentTitle) async {
    final newTitle = await showDialog<String>(
      context: context,
      builder: (_) => _RenameConversationDialog(initialTitle: currentTitle),
    );

    if (newTitle != null && newTitle.isNotEmpty) {
      await LocalConversationStorage.instance.renameConversation(id, newTitle);
      _reloadConversations();
    }
  }

  Future<void> _deleteConversation(String id) async {
    await LocalConversationStorage.instance.deleteConversation(id);
    await _reloadConversations();
    if (!mounted) return;
    _showSnackBar(
      SnackBar(
        duration: const Duration(seconds: 3),
        persist: false,
        content: Row(
          children: [
            const Expanded(child: Text('Conversation mise à la corbeille')),
            TextButton(
              onPressed: () async {
                ScaffoldMessenger.maybeOf(context)?.hideCurrentSnackBar();
                await LocalConversationStorage.instance.restoreConversation(id);
                _reloadConversations();
              },
              style: TextButton.styleFrom(
                foregroundColor: const Color(0xFF93C5FD),
                padding: const EdgeInsets.symmetric(horizontal: 10),
                minimumSize: const Size(0, 32),
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              child: const Text('Restaurer'),
            ),
            IconButton(
              icon: const Icon(Icons.close_rounded, size: 18, color: Colors.white70),
              tooltip: 'Fermer',
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
              onPressed: () => ScaffoldMessenger.maybeOf(context)?.hideCurrentSnackBar(),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _toggleLibrary(String id) async {
    await LocalConversationStorage.instance.toggleLibrarySaved(id);
    await _reloadConversations();
    if (!mounted) return;
    _showSnackBar(
      const SnackBar(
        content: Text('Statut Library mis à jour'),
        duration: Duration(seconds: 2),
      ),
    );
  }

  String _getTitle(int index) {
    switch (index) {
      case 1:
        return 'Explore';
      case 2:
        return 'Library';
      case 3:
        return 'Prévisions';
      case 4:
        return 'Credit Passport';
      default:
        return 'FreeData.AI';
    }
  }

  @override
  Widget build(BuildContext context) {
    final isDesktop = MediaQuery.sizeOf(context).width >= 900;

    final pages = [
      ChatScreen(
        apiService: _apiService,
        conversationId: _activeConversationId,
        onConversationUpdated: _reloadConversations,
        initialPrompt: _pendingPrompt,
        onPromptHandled: () {
          if (!mounted || _pendingPrompt == null) return;
          setState(() => _pendingPrompt = null);
        },
      ),
      if (_visitedTabs.contains(1))
        ExploreScreen(
          apiService: _apiService,
          onSelectPrompt: _openPromptInChat,
        )
      else
        const SizedBox.shrink(),
      if (_visitedTabs.contains(2))
        LibraryScreen(
          apiService: _apiService,
          conversations: _conversations,
          onConversationsUpdated: _reloadConversations,
          onOpenConversation: (id) {
            setState(() {
              _selectedIndex = 0;
              _visitedTabs.add(0);
              _activeConversationId = id;
            });
          },
        )
      else
        const SizedBox.shrink(),
      if (_visitedTabs.contains(3))
        ForecastScreen(
          apiService: _apiService,
          onSelectPrompt: _openPromptInChat,
        )
      else
        const SizedBox.shrink(),
      if (_visitedTabs.contains(4))
        PassportScreen(
          apiService: _apiService,
          onSelectPrompt: _openPromptInChat,
        )
      else
        const SizedBox.shrink(),
    ];

    if (isDesktop) {
      return Scaffold(
        backgroundColor: Colors.white,
        body: Row(
          children: [
            SizedBox(
              width: 280,
              child: _SidebarContent(
                currentIndex: _selectedIndex,
                activeConversationId: _activeConversationId,
                conversations: _conversations,
                hasPremiumKey: _apiService.hasPremiumKey,
                onConfigurePremiumKey: _configurePremiumKey,
                onSelectNavigation: _selectTab,
                onSelectConversation: (id) {
                  setState(() {
                    _selectedIndex = 0;
                    _visitedTabs.add(0);
                    _activeConversationId = id;
                  });
                },
                onNewConversation: _createNewConversation,
                onRenameConversation: _renameConversation,
                onDeleteConversation: _deleteConversation,
                onToggleLibrary: _toggleLibrary,
                isDrawer: false,
              ),
            ),
            const VerticalDivider(width: 1, thickness: 1, color: FDTheme.line),
            Expanded(
              child: Column(
                children: [
                  Container(
                    height: 56,
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    decoration: const BoxDecoration(
                      color: FDTheme.surface,
                      border: Border(bottom: BorderSide(color: FDTheme.canvasSoft, width: 1)),
                    ),
                    child: Row(
                      children: [
                        Text(
                          _getTitle(_selectedIndex),
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: FDTheme.ink,
                          ),
                        ),
                        const Spacer(),
                        Semantics(
                          button: true,
                          label: _apiService.hasPremiumKey
                              ? 'Accès Partenaire actif'
                              : 'Tchad · Marchés et Prix',
                          child: InkWell(
                            onTap: _configurePremiumKey,
                            borderRadius: BorderRadius.circular(99),
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                              decoration: BoxDecoration(
                                color: _apiService.hasPremiumKey ? FDTheme.greenSoft : FDTheme.blueSoft,
                                borderRadius: BorderRadius.circular(99),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(
                                    _apiService.hasPremiumKey ? Icons.verified_rounded : Icons.circle,
                                    size: _apiService.hasPremiumKey ? 13 : 7,
                                    color: _apiService.hasPremiumKey ? FDTheme.green : FDTheme.blue,
                                  ),
                                  const SizedBox(width: 6),
                                  Text(
                                    _apiService.hasPremiumKey
                                        ? 'Tchad · Accès Partenaire'
                                        : 'Tchad · Marchés et Prix',
                                    style: TextStyle(
                                      fontSize: 11.5,
                                      color: _apiService.hasPremiumKey ? FDTheme.greenDark : FDTheme.blue,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  Expanded(
                    child: IndexedStack(
                      index: _selectedIndex,
                      children: pages,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }

    // Mobile layout
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.white,
        elevation: 0,
        shape: const Border(
          bottom: BorderSide(
            color: Color(0xFFF1F5F9),
            width: 1,
          ),
        ),
        leading: Builder(
          builder: (context) => IconButton(
            icon: const Icon(Icons.menu_rounded, color: Color(0xFF0F172A)),
            onPressed: () => Scaffold.of(context).openDrawer(),
          ),
        ),
        title: Row(
          children: [
            Semantics(
              label: 'Logo FreeData.AI',
              child: Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: FDTheme.blue,
                  borderRadius: BorderRadius.circular(8),
                ),
                alignment: Alignment.center,
                child: const Text(
                  'FD',
                  style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 10),
            Flexible(
              child: Text(
                _getTitle(_selectedIndex),
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: FDTheme.ink,
                  fontSize: 17.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            if (_apiService.hasPremiumKey) ...[
              const SizedBox(width: 8),
              Semantics(
                button: true,
                label: 'Accès Partenaire actif',
                child: InkWell(
                  onTap: _configurePremiumKey,
                  borderRadius: BorderRadius.circular(99),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                    decoration: BoxDecoration(
                      color: FDTheme.greenSoft,
                      borderRadius: BorderRadius.circular(99),
                      border: Border.all(color: FDTheme.green.withValues(alpha: 0.3)),
                    ),
                    child: const Text(
                      'PRO',
                      style: TextStyle(
                        fontSize: 10.5,
                        fontWeight: FontWeight.w700,
                        color: FDTheme.greenDark,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.support_agent_outlined, color: FDTheme.ink),
            tooltip: 'Assistance & Avis',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => SupportScreen(apiService: _apiService)),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.workspace_premium_outlined, color: FDTheme.ink),
            tooltip: 'Abonnement & Quotas',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => SubscriptionScreen(apiService: _apiService, onConfigureKey: _configurePremiumKey),
              ),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.tune_rounded, color: FDTheme.ink),
            tooltip: 'Préférences',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => SettingsScreen(apiService: _apiService)),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.analytics_outlined, color: FDTheme.ink),
            tooltip: 'Analytics & Intelligence',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => AnalyticsScreen(apiService: _apiService)),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.menu_book_outlined, color: FDTheme.ink),
            tooltip: 'Documentation & Méthodologie',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const DocsScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.folder_special_outlined, color: FDTheme.ink),
            tooltip: 'Espace Projets',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => ProjectsScreen(
                  apiService: _apiService,
                  onResumeProject: (proj) {
                    Navigator.pop(context);
                    _openPromptInChat('Reprendre le projet ${proj['name']}');
                  },
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Tooltip(
              message: 'Nouvelle conversation',
              child: InkWell(
                onTap: _createNewConversation,
                borderRadius: BorderRadius.circular(10),
                child: Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: FDTheme.canvas,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: FDTheme.line),
                  ),
                  alignment: Alignment.center,
                  child: const Icon(
                    Icons.edit_square,
                    size: 19,
                    color: FDTheme.ink,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
      drawer: Drawer(
        width: 290,
        backgroundColor: FDTheme.surface,
        child: SafeArea(
          child: _SidebarContent(
            currentIndex: _selectedIndex,
            activeConversationId: _activeConversationId,
            conversations: _conversations,
            hasPremiumKey: _apiService.hasPremiumKey,
            onConfigurePremiumKey: () {
              Navigator.of(context).pop();
              _configurePremiumKey();
            },
            onSelectNavigation: (index) {
              _selectTab(index);
              Navigator.of(context).pop();
            },
            onSelectConversation: (id) {
              setState(() {
                _selectedIndex = 0;
                _visitedTabs.add(0);
                _activeConversationId = id;
              });
              Navigator.of(context).pop();
            },
            onNewConversation: () {
              Navigator.of(context).pop();
              _createNewConversation();
            },
            onRenameConversation: _renameConversation,
            onDeleteConversation: _deleteConversation,
            onToggleLibrary: _toggleLibrary,
            isDrawer: true,
          ),
        ),
      ),
      body: IndexedStack(
        index: _selectedIndex,
        children: pages,
      ),
    );
  }
}

class _SidebarContent extends StatelessWidget {
  final int currentIndex;
  final String? activeConversationId;
  final List<ConversationThread> conversations;
  final bool hasPremiumKey;
  final VoidCallback onConfigurePremiumKey;
  final ValueChanged<int> onSelectNavigation;
  final ValueChanged<String> onSelectConversation;
  final VoidCallback onNewConversation;
  final void Function(String id, String currentTitle) onRenameConversation;
  final ValueChanged<String> onDeleteConversation;
  final ValueChanged<String> onToggleLibrary;
  final bool isDrawer;

  const _SidebarContent({
    required this.currentIndex,
    required this.activeConversationId,
    required this.conversations,
    required this.hasPremiumKey,
    required this.onConfigurePremiumKey,
    required this.onSelectNavigation,
    required this.onSelectConversation,
    required this.onNewConversation,
    required this.onRenameConversation,
    required this.onDeleteConversation,
    required this.onToggleLibrary,
    required this.isDrawer,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Bouton primaire Nouvelle conversation
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          child: FilledButton.icon(
            onPressed: onNewConversation,
            icon: const Icon(Icons.add_rounded, size: 20),
            label: const Text('Nouvelle conversation', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
            style: FilledButton.styleFrom(
              backgroundColor: FDTheme.blue,
              foregroundColor: Colors.white,
              minimumSize: const Size.fromHeight(46),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            ),
          ),
        ),
        // En-tête ESPACE DE TRAVAIL
        const Padding(
          padding: EdgeInsets.fromLTRB(20, 10, 20, 6),
          child: Text(
            'ESPACE DE TRAVAIL',
            style: TextStyle(
              fontSize: 12,
              color: FDTheme.subtle,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.8,
            ),
          ),
        ),
        _navItem(0, Icons.chat_bubble_outline_rounded, 'Assistant IA'),
        _navItem(1, Icons.explore_outlined, 'Explore'),
        _navItem(2, Icons.bookmark_outline_rounded, 'Library'),
        _navItem(3, Icons.show_chart_rounded, 'Prévisions'),
        _navItem(4, Icons.shield_outlined, 'Credit Passport'),
        const Divider(height: 18, thickness: 1, color: FDTheme.canvasSoft),
        // Historique des conversations récentes
        const Padding(
          padding: EdgeInsets.fromLTRB(20, 8, 20, 6),
          child: Text(
            'HISTORIQUE RÉCENT',
            style: TextStyle(
              fontSize: 12,
              color: FDTheme.subtle,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.8,
            ),
          ),
        ),
        Expanded(
          child: conversations.isEmpty
              ? const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                  child: Text(
                    'Aucune conversation enregistrée.',
                    style: TextStyle(fontSize: 14, color: FDTheme.muted),
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  itemCount: conversations.length,
                  itemBuilder: (context, index) {
                    final conv = conversations[index];
                    final isSelected = currentIndex == 0 && conv.id == activeConversationId;
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Material(
                        color: isSelected ? FDTheme.blueSoft : Colors.transparent,
                        borderRadius: BorderRadius.circular(8),
                        child: ListTile(
                          dense: false,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                          contentPadding: const EdgeInsets.only(left: 10, right: 4),
                          leading: Icon(
                            conv.isSavedInLibrary ? Icons.bookmark_rounded : Icons.chat_bubble_outline_rounded,
                            size: 18,
                            color: isSelected ? FDTheme.blue : FDTheme.subtle,
                          ),
                          title: Text(
                            conv.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 14.5,
                              fontWeight: isSelected ? FontWeight.w600 : FontWeight.w500,
                              color: isSelected ? FDTheme.blue : FDTheme.body,
                            ),
                          ),
                          trailing: PopupMenuButton<String>(
                            icon: const Icon(Icons.more_vert_rounded, size: 16, color: FDTheme.subtle),
                            padding: EdgeInsets.zero,
                            tooltip: 'Options',
                            onSelected: (val) {
                              if (val == 'rename') {
                                onRenameConversation(conv.id, conv.title);
                              } else if (val == 'library') {
                                onToggleLibrary(conv.id);
                              } else if (val == 'delete') {
                                onDeleteConversation(conv.id);
                              }
                            },
                            itemBuilder: (ctx) => [
                              const PopupMenuItem(
                                value: 'rename',
                                child: Row(
                                  children: [
                                    Icon(Icons.edit_outlined, size: 16),
                                    SizedBox(width: 8),
                                    Flexible(
                                      child: Text(
                                        'Renommer',
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              PopupMenuItem(
                                value: 'library',
                                child: Row(
                                  children: [
                                    Icon(conv.isSavedInLibrary ? Icons.bookmark_remove_outlined : Icons.bookmark_add_outlined, size: 16),
                                    const SizedBox(width: 8),
                                    Flexible(
                                      child: Text(
                                        conv.isSavedInLibrary ? 'Retirer de Library' : 'Sauvegarder dans Library',
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              const PopupMenuItem(
                                value: 'delete',
                                child: Row(
                                  children: [
                                    Icon(Icons.delete_outline_rounded, size: 16, color: Color(0xFFDC2626)),
                                    SizedBox(width: 8),
                                    Flexible(
                                      child: Text(
                                        'Supprimer',
                                        overflow: TextOverflow.ellipsis,
                                        style: TextStyle(color: Color(0xFFDC2626)),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                          onTap: () => onSelectConversation(conv.id),
                        ),
                      ),
                    );
                  },
                ),
        ),
        // Pied de Sidebar
        const Divider(height: 1, thickness: 1, color: FDTheme.line),
        Padding(
          padding: const EdgeInsets.all(10.0),
          child: Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: onConfigurePremiumKey,
              borderRadius: BorderRadius.circular(10),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                child: Row(
                  children: [
                    Semantics(
                      label: 'Logo FreeData.AI',
                      child: Container(
                        width: 34,
                        height: 34,
                        decoration: BoxDecoration(
                          color: FDTheme.blue,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        alignment: Alignment.center,
                        child: const Text(
                          'FD',
                          style: TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 14,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Text(
                            'FreeData.AI',
                            style: TextStyle(
                              fontSize: 15.5,
                              fontWeight: FontWeight.bold,
                              color: FDTheme.ink,
                            ),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            hasPremiumKey
                                ? 'Accès Partenaire actif · Tchad'
                                : 'Intelligence des Marchés · Tchad',
                            style: TextStyle(
                              fontSize: 12.0,
                              color: hasPremiumKey ? FDTheme.greenDark : FDTheme.subtle,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                      decoration: BoxDecoration(
                        color: hasPremiumKey ? FDTheme.greenSoft : FDTheme.canvas,
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(
                          color: hasPremiumKey
                              ? FDTheme.green.withValues(alpha: 0.3)
                              : FDTheme.line,
                        ),
                      ),
                      child: Text(
                        hasPremiumKey ? 'PRO' : 'Clé Pro',
                        style: TextStyle(
                          fontSize: 10.5,
                          fontWeight: FontWeight.w700,
                          color: hasPremiumKey ? FDTheme.greenDark : FDTheme.muted,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _navItem(int index, IconData icon, String label) {
    final isSelected = currentIndex == index;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      child: ListTile(
        dense: false,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        tileColor: isSelected ? FDTheme.blueSoft : Colors.transparent,
        leading: Icon(
          icon,
          color: isSelected ? FDTheme.blue : FDTheme.subtle,
          size: 22,
        ),
        title: Text(
          label,
          style: TextStyle(
            fontSize: 15.5,
            fontWeight: isSelected ? FontWeight.w600 : FontWeight.w500,
            color: isSelected ? FDTheme.blue : FDTheme.ink,
          ),
        ),
        onTap: () => onSelectNavigation(index),
      ),
    );
  }
}

class _PremiumKeyDialog extends StatefulWidget {
  final String initialKey;
  final bool hasActiveKey;

  const _PremiumKeyDialog({
    required this.initialKey,
    required this.hasActiveKey,
  });

  @override
  State<_PremiumKeyDialog> createState() => _PremiumKeyDialogState();
}

class _PremiumKeyDialogState extends State<_PremiumKeyDialog> {
  late final TextEditingController _controller = TextEditingController(text: widget.initialKey);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Accès Partenaire & Clé Pro'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Saisissez votre clé d’accès FreeData.AI pour activer l’assistant conversationnel avancé et les études de saisonnalité & stockage.',
            style: TextStyle(fontSize: 13, color: FDTheme.muted, height: 1.4),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _controller,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: 'Clé d’accès FreeData.AI',
              hintText: 'Ex. FD-PRO-...',
            ),
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annuler')),
        if (widget.hasActiveKey)
          TextButton(
            onPressed: () => Navigator.pop(context, ''),
            child: const Text('Désactiver la clé', style: TextStyle(color: FDTheme.danger)),
          ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _controller.text.trim()),
          child: const Text('Activer'),
        ),
      ],
    );
  }
}

class _RenameConversationDialog extends StatefulWidget {
  final String initialTitle;

  const _RenameConversationDialog({required this.initialTitle});

  @override
  State<_RenameConversationDialog> createState() => _RenameConversationDialogState();
}

class _RenameConversationDialogState extends State<_RenameConversationDialog> {
  late final TextEditingController _controller = TextEditingController(text: widget.initialTitle);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Renommer la conversation'),
      content: TextField(
        controller: _controller,
        autofocus: true,
        decoration: const InputDecoration(labelText: 'Titre de la conversation'),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Annuler')),
        FilledButton(
          onPressed: () => Navigator.pop(context, _controller.text.trim()),
          child: const Text('Enregistrer'),
        ),
      ],
    );
  }
}
