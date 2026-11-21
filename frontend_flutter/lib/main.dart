import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'core/fd_theme.dart';
import 'services/api_service.dart';
import 'services/conversation_storage.dart';
import 'screens/chat_screen.dart';
import 'screens/explore_screen.dart';
import 'screens/library_screen.dart';
import 'screens/account_screen.dart';
import 'screens/admin_screen.dart';
import 'screens/agro_pro_screen.dart';
import 'screens/docs_screen.dart';
import 'screens/markets_hub_screen.dart';
import 'screens/projects_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/subscription_screen.dart';
import 'screens/support_screen.dart';
import 'widgets/auth_dialog.dart';

void main() => runApp(const FreeDataAIApp());

class FreeDataAIApp extends StatelessWidget {
  const FreeDataAIApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'FreeData.AI',
      debugShowCheckedModeBanner: false,
      theme: FDTheme.light(),
      onGenerateRoute: (settings) {
        if (settings.name == '/admin') {
          return MaterialPageRoute(
            settings: settings,
            builder: (_) => AdminScreen(apiService: ApiService()),
          );
        }
        return MaterialPageRoute(
          settings: settings,
          builder: (_) => const MainShell(),
        );
      },
    );
  }
}

class MainShell extends StatefulWidget {
  final Uri? initialUri;
  final ApiService? apiService;
  final bool requireAuthOnChat;
  const MainShell({
    super.key,
    this.initialUri,
    this.apiService,
    this.requireAuthOnChat = true,
  });

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
  Map<String, dynamic>? _activeProject;
  int _projectsRefreshToken = 0;
  List<ConversationThread> _conversations = const [];

  @override
  void initState() {
    super.initState();
    LocalConversationStorage.instance.attachCloudApi(_apiService);
    // Clé refusée par le serveur (403) : on la retire aussi du stockage et on redessine l'interface (onglets PRO).
    _apiService.onPremiumKeyRejected = () async {
      try {
        final prefs = await SharedPreferences.getInstance();
        await prefs.remove(_premiumKeyStorageKey);
      } catch (_) {}
      if (!mounted) return;
      setState(() {});
      _showSnackBar(const SnackBar(
          content: Text(
              'Clé PRO refusée par le serveur : accès PRO désactivé. Saisissez une clé valide.')));
    };
    _apiService.onAuthSessionExpired = () async {
      try {
        final prefs = await SharedPreferences.getInstance();
        await prefs.remove(kAuthTokenStorageKey);
      } catch (_) {}
      if (!mounted) return;
      setState(() {});
      _showSnackBar(const SnackBar(
          content: Text(
              'Votre session a expiré ou été révoquée. Veuillez vous reconnecter.')));
    };
    _loadPremiumKey();
    _reloadConversations();
  }

  Future<void> _syncCloudConversations() async {
    if (!_apiService.isAuthenticated) return;
    try {
      await LocalConversationStorage.instance.syncWithCloud(_apiService);
      if (mounted) await _reloadConversations();
    } catch (_) {}
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
    final urlKey =
        (uri.queryParameters['key'] ?? uri.queryParameters['premium_key'])
            ?.trim();
    final prefs = await SharedPreferences.getInstance();
    var uid = prefs.getString('fd_pref_user_id');
    if (uid == null || !ApiService.isStrongUserId(uid)) {
      uid = ApiService.generateUserId();
      await prefs.setString('fd_pref_user_id', uid);
    }
    _apiService.setUserId(uid);
    final savedAuthToken = prefs.getString(kAuthTokenStorageKey);
    if (savedAuthToken != null && savedAuthToken.trim().isNotEmpty) {
      _apiService.setAuthSession(token: savedAuthToken);
      try {
        await _apiService.getAuthMe();
        if (mounted) setState(() {});
        await _syncCloudConversations();
      } on ApiHttpException catch (e) {
        if (e.statusCode == 401) {
          await prefs.remove(kAuthTokenStorageKey);
          _apiService.clearAuthSession();
          if (mounted) setState(() {});
        }
      } catch (_) {}
    }
    _apiService.prefetchBillingCatalog();
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
      if (index == 6) {
        _projectsRefreshToken++;
      }
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
        final draft =
            await LocalConversationStorage.instance.createConversation();
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
    final newThread =
        await LocalConversationStorage.instance.createConversation();
    if (!mounted) return;
    setState(() {
      _selectedIndex = 0;
      _visitedTabs.add(0);
      _activeConversationId = newThread.id;
      _activeProject = null;
      _pendingPrompt = null;
    });
    await _reloadConversations();
  }

  Future<void> _openPromptInChat(String prompt) async {
    final newThread =
        await LocalConversationStorage.instance.createConversation();
    if (!mounted) return;
    setState(() {
      _selectedIndex = 0;
      _visitedTabs.add(0);
      _activeConversationId = newThread.id;
      _activeProject = null;
      _pendingPrompt = prompt;
    });
    await _reloadConversations();
  }

  Future<void> _openProjectInChat(
    Map<String, dynamic> proj, {
    String? conversationId,
    String? initialPrompt,
    bool forceNewConversation = false,
  }) async {
    final pid = proj['project_id']?.toString().trim() ?? '';
    final pname = proj['name']?.toString().trim() ?? 'Projet PRO';

    // 1. Si l'utilisateur rouvre une discussion existante du projet : ZÉRO réinitialisation !
    if (!forceNewConversation &&
        conversationId != null &&
        conversationId.trim().isNotEmpty) {
      setState(() {
        _selectedIndex = 0;
        _visitedTabs.add(0);
        _activeProject = proj;
        _activeConversationId = conversationId;
        _pendingPrompt = initialPrompt;
      });
      return;
    }

    // 2. Si on clique sur "Reprendre" sans forcer une nouvelle discussion et qu'une discussion existe déjà : la rouvrir directement.
    if (!forceNewConversation && pid.isNotEmpty) {
      final existing =
          await LocalConversationStorage.instance.listProjectConversations(pid);
      if (!mounted) return;
      if (existing.isNotEmpty) {
        setState(() {
          _selectedIndex = 0;
          _visitedTabs.add(0);
          _activeProject = proj;
          _activeConversationId = existing.first.id;
          _pendingPrompt = initialPrompt;
        });
        return;
      }
    }

    // 3. Sinon, ouvrir une nouvelle discussion proprement rattachée à ce projet (avec son StudyContext).
    final newThread =
        await LocalConversationStorage.instance.createConversation(
      title: 'Nouvelle conversation',
      projectId: pid.isEmpty ? null : pid,
      projectName: pname,
    );
    if (!mounted) return;
    setState(() {
      _selectedIndex = 0;
      _visitedTabs.add(0);
      _activeProject = proj;
      _activeConversationId = newThread.id;
      _pendingPrompt = initialPrompt;
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
              icon: const Icon(Icons.close_rounded,
                  size: 18, color: Colors.white70),
              tooltip: 'Fermer',
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
              onPressed: () =>
                  ScaffoldMessenger.maybeOf(context)?.hideCurrentSnackBar(),
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
        content: Text('Statut Bibliothèque mis à jour'),
        duration: Duration(seconds: 2),
      ),
    );
  }

  String _getTitle(int index) {
    switch (index) {
      case 1:
        return 'Explorer';
      case 2:
        return 'Bibliothèque';
      case 3:
        return 'Projets PRO';
      case 4:
        return 'Marchés & Crédit';
      case 5:
        return _apiService.hasPremiumKey
            ? 'Agriculture · Agro PRO'
            : 'Agriculture';
      default:
        return 'FreeData.AI';
    }
  }

  Future<bool> _openAuthDialog(
      {bool register = false, String? reasonBanner}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AuthDialog(
        apiService: _apiService,
        initialRegisterMode: register,
        reasonBanner: reasonBanner,
      ),
    );
    if (ok == true && mounted) {
      setState(() {});
      _apiService.prefetchBillingCatalog();
      await _syncCloudConversations();
      final email = _apiService.authUser?['email']?.toString() ?? '';
      _showSnackBar(
        SnackBar(
          content:
              Text(email.isNotEmpty ? 'Connecté : $email' : 'Session activée.'),
          duration: const Duration(seconds: 3),
        ),
      );
      return true;
    }
    return false;
  }

  Future<bool> _ensureAuthenticated() async {
    if (_apiService.isAuthenticated || _apiService.hasExplicitPremiumKey)
      return true;
    return _openAuthDialog(
      reasonBanner:
          'Connectez-vous ou créez un compte gratuit pour envoyer votre message et retrouver vos conversations sur tous vos appareils.',
    );
  }

  void _openAccountScreen() {
    Navigator.of(context)
        .push(
      MaterialPageRoute(
        builder: (_) => AccountScreen(
          apiService: _apiService,
          onConfigureKey: _configurePremiumKey,
          onSessionChanged: () {
            if (mounted) {
              setState(() {
                if (!_apiService.isAuthenticated) {
                  _activeConversationId = null;
                  _selectedIndex = 0;
                }
              });
              _reloadConversations();
            }
          },
        ),
      ),
    )
        .then((_) {
      if (mounted) {
        setState(() {
          if (!_apiService.isAuthenticated) {
            _activeConversationId = null;
            _selectedIndex = 0;
          }
        });
        _reloadConversations();
      }
    });
  }

  void _openSubscriptionScreen() {
    Navigator.of(context)
        .push(
      MaterialPageRoute(
        builder: (_) => SubscriptionScreen(
          apiService: _apiService,
          onConfigureKey: _configurePremiumKey,
          onSessionChanged: () {
            if (mounted) setState(() {});
          },
        ),
      ),
    )
        .then((_) {
      if (mounted) setState(() {});
    });
  }

  void _openSupportScreen() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => SupportScreen(apiService: _apiService)),
    );
  }

  void _openDocsScreen() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const DocsScreen()),
    );
  }

  void _openSettingsScreen() {
    Navigator.of(context)
        .push(MaterialPageRoute(
            builder: (_) => SettingsScreen(
                  apiService: _apiService,
                  onConfigureKey: _configurePremiumKey,
                  onSessionChanged: () {
                    if (!mounted) return;
                    setState(() {
                      if (!_apiService.isAuthenticated) {
                        _activeConversationId = null;
                        _selectedIndex = 0;
                      }
                    });
                    _reloadConversations();
                  },
                  onPreferencesSaved: () {
                    if (mounted) setState(() {});
                  },
                )))
        .then((_) {
      if (mounted) {
        setState(() {
          if (!_apiService.isAuthenticated) {
            _activeConversationId = null;
            _selectedIndex = 0;
          }
        });
        _reloadConversations();
      }
    });
  }

  Future<void> _handleLogout() async {
    await _apiService.logoutAccount();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(kAuthTokenStorageKey);
    // Effacer le cache local des conversations du compte déconnecté (elles restent en sécurité dans le cloud).
    await LocalConversationStorage.instance.saveAll(const []);
    if (!mounted) return;
    setState(() {
      _activeConversationId = null;
      _selectedIndex = 0;
    });
    await _reloadConversations();
    if (!mounted) return;
    _showSnackBar(
      const SnackBar(
          content: Text('Déconnexion effectuée.'),
          duration: Duration(seconds: 2)),
    );
  }

  static String _userInitials(Map<String, dynamic>? user) {
    final name = user?['display_name']?.toString().trim() ?? '';
    final email = user?['email']?.toString().trim() ?? '';
    final src = name.isNotEmpty ? name : email;
    if (src.isEmpty) return 'FD';
    final parts =
        src.split(RegExp(r'[\s@._-]+')).where((p) => p.isNotEmpty).toList();
    if (parts.length >= 2) return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
    return src.substring(0, src.length >= 2 ? 2 : 1).toUpperCase();
  }

  static PopupMenuItem<String> _buildMenuOption({
    required String value,
    required IconData icon,
    required String label,
    Color? color,
    bool highlight = false,
  }) {
    final fg = color ?? (highlight ? FDTheme.blue : FDTheme.ink);
    final iconColor = color ?? (highlight ? FDTheme.blue : FDTheme.subtle);
    return PopupMenuItem<String>(
      value: value,
      height: 38,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      child: Row(
        children: [
          Icon(icon, size: 17, color: iconColor),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 13.5,
                fontWeight: (highlight || color != null)
                    ? FontWeight.w600
                    : FontWeight.w500,
                color: fg,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildUtilityMenu({
    bool includeSubscription = false,
    bool includeAccount = true,
  }) {
    return PopupMenuButton<String>(
      icon: const Icon(Icons.more_vert_rounded, color: FDTheme.ink),
      tooltip: 'Plus d\'options',
      color: FDTheme.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 10,
      shadowColor: FDTheme.shadow,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: FDTheme.line),
      ),
      onSelected: (value) {
        if (value == 'account') {
          if (_apiService.isAuthenticated) {
            _openAccountScreen();
          } else {
            _openAuthDialog();
          }
        } else if (value == 'support') {
          _openSupportScreen();
        } else if (value == 'subscription') {
          _openSubscriptionScreen();
        } else if (value == 'settings') {
          _openSettingsScreen();
        } else if (value == 'docs') {
          _openDocsScreen();
        } else if (value == 'logout') {
          _handleLogout();
        }
      },
      itemBuilder: (context) => [
        if (includeAccount)
          _buildMenuOption(
            value: 'account',
            icon: _apiService.isAuthenticated
                ? Icons.person_outline_rounded
                : Icons.login_rounded,
            label: _apiService.isAuthenticated
                ? 'Mon compte'
                : 'Connexion / Compte',
          ),
        if (includeSubscription || !_apiService.hasPremiumKey)
          _buildMenuOption(
            value: 'subscription',
            icon: Icons.workspace_premium_outlined,
            label: _apiService.hasPremiumKey
                ? 'Abonnement & Quotas'
                : 'Passer à PRO',
            highlight: !_apiService.hasPremiumKey,
          ),
        _buildMenuOption(
          value: 'settings',
          icon: Icons.tune_rounded,
          label: 'Préférences',
        ),
        _buildMenuOption(
          value: 'support',
          icon: Icons.support_agent_outlined,
          label: 'Assistance & Avis',
        ),
        _buildMenuOption(
          value: 'docs',
          icon: Icons.menu_book_outlined,
          label: 'Documentation',
        ),
        if (includeAccount && _apiService.isAuthenticated) ...[
          const PopupMenuDivider(height: 8),
          _buildMenuOption(
            value: 'logout',
            icon: Icons.logout_rounded,
            label: 'Se déconnecter',
            color: FDTheme.danger,
          ),
        ],
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final isDesktop = MediaQuery.sizeOf(context).width >= 900;

    final pages = [
      ChatScreen(
        apiService: _apiService,
        conversationId: _activeConversationId,
        activeProject: _activeProject,
        onOpenProjects: _apiService.hasPremiumKey ? () => _selectTab(3) : null,
        onConversationUpdated: _reloadConversations,
        initialPrompt: _pendingPrompt,
        onRequireAuth: widget.requireAuthOnChat ? _ensureAuthenticated : null,
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
      if (_apiService.hasPremiumKey && _visitedTabs.contains(3))
        ProjectsScreen(
          apiService: _apiService,
          refreshToken: _projectsRefreshToken,
          conversations: _conversations,
          onOpenProjectChat: _openProjectInChat,
          onResumeProject: (proj) => _openProjectInChat(proj),
        )
      else
        const SizedBox.shrink(),
      if (_visitedTabs.contains(4))
        MarketsHubScreen(
          apiService: _apiService,
          onSelectPrompt: _openPromptInChat,
          onRequestPro: _openSubscriptionScreen,
        )
      else
        const SizedBox.shrink(),
      if (_visitedTabs.contains(5))
        AgroProScreen(
          apiService: _apiService,
          onAskAssistant: _openPromptInChat,
          onRequestPro: _openSubscriptionScreen,
        )
      else
        const SizedBox.shrink(),
    ];

    final effectiveIndex = (!_apiService.hasPremiumKey && _selectedIndex == 3)
        ? 0
        : _selectedIndex;

    if (isDesktop) {
      return Scaffold(
        backgroundColor: Colors.white,
        body: Row(
          children: [
            SizedBox(
              width: 280,
              child: _SidebarContent(
                currentIndex: effectiveIndex,
                activeConversationId: _activeConversationId,
                conversations: _conversations,
                hasPremiumKey: _apiService.hasPremiumKey,
                isAuthenticated: _apiService.isAuthenticated,
                authUser: _apiService.authUser,
                onConfigurePremiumKey: _configurePremiumKey,
                onLogin: () => _openAuthDialog(register: false),
                onRegister: () => _openAuthDialog(register: true),
                onOpenAccount: _openAccountScreen,
                onOpenSubscription: _openSubscriptionScreen,
                onOpenSupport: _openSupportScreen,
                onOpenDocs: _openDocsScreen,
                onOpenSettings: _openSettingsScreen,
                onLogout: _handleLogout,
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
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    decoration: const BoxDecoration(
                      color: FDTheme.surface,
                      border: Border(
                          bottom:
                              BorderSide(color: FDTheme.canvasSoft, width: 1)),
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            _getTitle(effectiveIndex),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: FDTheme.ink,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Semantics(
                          button: _apiService.isAuthenticated ||
                              _apiService.hasPremiumKey,
                          label: _apiService.hasPremiumKey
                              ? 'Accès Partenaire actif'
                              : 'Tchad · Marchés et Prix',
                          child: InkWell(
                            onTap: (_apiService.isAuthenticated ||
                                    _apiService.hasPremiumKey)
                                ? _configurePremiumKey
                                : null,
                            borderRadius: BorderRadius.circular(99),
                            child: Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 10, vertical: 6),
                              decoration: BoxDecoration(
                                color: _apiService.hasPremiumKey
                                    ? FDTheme.greenSoft
                                    : FDTheme.blueSoft,
                                borderRadius: BorderRadius.circular(99),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(
                                    _apiService.hasPremiumKey
                                        ? Icons.verified_rounded
                                        : Icons.circle,
                                    size: _apiService.hasPremiumKey ? 13 : 7,
                                    color: _apiService.hasPremiumKey
                                        ? FDTheme.green
                                        : FDTheme.blue,
                                  ),
                                  const SizedBox(width: 6),
                                  Text(
                                    _apiService.hasPremiumKey
                                        ? 'Tchad · Accès Partenaire'
                                        : 'Tchad · Marchés et Prix',
                                    style: TextStyle(
                                      fontSize: 11.5,
                                      color: _apiService.hasPremiumKey
                                          ? FDTheme.greenDark
                                          : FDTheme.blue,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        if (_apiService.isAuthenticated)
                          InkWell(
                            onTap: _openAccountScreen,
                            borderRadius: BorderRadius.circular(99),
                            child: Container(
                              padding: const EdgeInsets.fromLTRB(4, 4, 10, 4),
                              decoration: BoxDecoration(
                                color: FDTheme.canvas,
                                borderRadius: BorderRadius.circular(99),
                                border: Border.all(color: FDTheme.line),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  CircleAvatar(
                                    radius: 13,
                                    backgroundColor: FDTheme.blue,
                                    child: Text(
                                      _userInitials(_apiService.authUser),
                                      style: const TextStyle(
                                        color: Colors.white,
                                        fontSize: 10.5,
                                        fontWeight: FontWeight.w800,
                                      ),
                                    ),
                                  ),
                                  const SizedBox(width: 7),
                                  ConstrainedBox(
                                    constraints:
                                        const BoxConstraints(maxWidth: 140),
                                    child: Text(
                                      (_apiService.authUser?['display_name']
                                                  ?.toString()
                                                  .trim()
                                                  .isNotEmpty ??
                                              false)
                                          ? _apiService
                                              .authUser!['display_name']
                                              .toString()
                                          : (_apiService.authUser?['email']
                                                  ?.toString() ??
                                              'Mon compte'),
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                        fontSize: 12.5,
                                        fontWeight: FontWeight.w600,
                                        color: FDTheme.ink,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          )
                        else ...[
                          OutlinedButton(
                            onPressed: () => _openAuthDialog(register: false),
                            style: OutlinedButton.styleFrom(
                              foregroundColor: FDTheme.ink,
                              side: const BorderSide(color: FDTheme.line),
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 10, vertical: 6),
                              minimumSize: const Size(0, 32),
                              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(99)),
                            ),
                            child: const Text('Se connecter',
                                style: TextStyle(
                                    fontSize: 12, fontWeight: FontWeight.w600)),
                          ),
                          const SizedBox(width: 6),
                          FilledButton(
                            onPressed: () => _openAuthDialog(register: true),
                            style: FilledButton.styleFrom(
                              backgroundColor: FDTheme.ink,
                              foregroundColor: Colors.white,
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 10, vertical: 6),
                              minimumSize: const Size(0, 32),
                              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(99)),
                            ),
                            child: const Text('S’inscrire',
                                style: TextStyle(
                                    fontSize: 12, fontWeight: FontWeight.w600)),
                          ),
                          _buildUtilityMenu(includeAccount: false),
                        ],
                      ],
                    ),
                  ),
                  Expanded(
                    child: IndexedStack(
                      index: effectiveIndex,
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
                _getTitle(effectiveIndex),
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
                    padding:
                        const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                    decoration: BoxDecoration(
                      color: FDTheme.greenSoft,
                      borderRadius: BorderRadius.circular(99),
                      border: Border.all(
                          color: FDTheme.green.withValues(alpha: 0.3)),
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
          _buildUtilityMenu(includeSubscription: true),
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
            currentIndex: effectiveIndex,
            activeConversationId: _activeConversationId,
            conversations: _conversations,
            hasPremiumKey: _apiService.hasPremiumKey,
            isAuthenticated: _apiService.isAuthenticated,
            authUser: _apiService.authUser,
            onConfigurePremiumKey: () {
              Navigator.of(context).pop();
              _configurePremiumKey();
            },
            onLogin: () {
              Navigator.of(context).pop();
              _openAuthDialog(register: false);
            },
            onRegister: () {
              Navigator.of(context).pop();
              _openAuthDialog(register: true);
            },
            onOpenAccount: () {
              Navigator.of(context).pop();
              _openAccountScreen();
            },
            onOpenSubscription: () {
              Navigator.of(context).pop();
              _openSubscriptionScreen();
            },
            onOpenSupport: () {
              Navigator.of(context).pop();
              _openSupportScreen();
            },
            onOpenDocs: () {
              Navigator.of(context).pop();
              _openDocsScreen();
            },
            onOpenSettings: () {
              Navigator.of(context).pop();
              _openSettingsScreen();
            },
            onLogout: () {
              Navigator.of(context).pop();
              _handleLogout();
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
        index: effectiveIndex,
        children: pages,
      ),
    );
  }
}

class _SidebarContent extends StatefulWidget {
  final int currentIndex;
  final String? activeConversationId;
  final List<ConversationThread> conversations;
  final bool hasPremiumKey;
  final bool isAuthenticated;
  final Map<String, dynamic>? authUser;
  final VoidCallback onConfigurePremiumKey;
  final VoidCallback onLogin;
  final VoidCallback onRegister;
  final VoidCallback onOpenAccount;
  final VoidCallback onOpenSubscription;
  final VoidCallback onOpenSupport;
  final VoidCallback onOpenDocs;
  final VoidCallback onOpenSettings;
  final VoidCallback onLogout;
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
    required this.isAuthenticated,
    required this.authUser,
    required this.onConfigurePremiumKey,
    required this.onLogin,
    required this.onRegister,
    required this.onOpenAccount,
    required this.onOpenSubscription,
    required this.onOpenSupport,
    required this.onOpenDocs,
    required this.onOpenSettings,
    required this.onLogout,
    required this.onSelectNavigation,
    required this.onSelectConversation,
    required this.onNewConversation,
    required this.onRenameConversation,
    required this.onDeleteConversation,
    required this.onToggleLibrary,
    required this.isDrawer,
  });

  @override
  State<_SidebarContent> createState() => _SidebarContentState();
}

class _SidebarContentState extends State<_SidebarContent> {
  bool _searching = false;
  String _searchQuery = '';
  final _searchCtrl = TextEditingController();

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  static String _initials(Map<String, dynamic>? user) {
    final name = user?['display_name']?.toString().trim() ?? '';
    final email = user?['email']?.toString().trim() ?? '';
    final src = name.isNotEmpty ? name : email;
    if (src.isEmpty) return 'FD';
    final parts =
        src.split(RegExp(r'[\s@._-]+')).where((p) => p.isNotEmpty).toList();
    if (parts.length >= 2) return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
    return src.substring(0, src.length >= 2 ? 2 : 1).toUpperCase();
  }

  List<Widget> _buildGroupedConversations(List<ConversationThread> list) {
    final now = DateTime.now();
    final startOfToday = DateTime(now.year, now.month, now.day);
    final sevenDaysAgo = startOfToday.subtract(const Duration(days: 7));

    final today = <ConversationThread>[];
    final last7 = <ConversationThread>[];
    final older = <ConversationThread>[];

    for (final c in list) {
      if (!c.updatedAt.isBefore(startOfToday)) {
        today.add(c);
      } else if (!c.updatedAt.isBefore(sevenDaysAgo)) {
        last7.add(c);
      } else {
        older.add(c);
      }
    }

    final widgets = <Widget>[];
    void addSection(String title, List<ConversationThread> items) {
      if (items.isEmpty) return;
      widgets.add(
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 4),
          child: Text(
            title,
            style: const TextStyle(
              fontSize: 11,
              color: FDTheme.subtle,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      );
      for (final conv in items) {
        widgets.add(_buildConversationTile(conv));
      }
    }

    addSection('Aujourd’hui', today);
    addSection('7 derniers jours', last7);
    addSection('Plus ancien', older);
    return widgets;
  }

  Widget _buildConversationTile(ConversationThread conv) {
    final isSelected =
        widget.currentIndex == 0 && conv.id == widget.activeConversationId;
    return Padding(
      padding: const EdgeInsets.fromLTRB(10, 0, 10, 2),
      child: Material(
        color: isSelected ? FDTheme.blueSoft : Colors.transparent,
        borderRadius: BorderRadius.circular(8),
        child: ListTile(
          dense: false,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          contentPadding: const EdgeInsets.only(left: 10, right: 4),
          leading: Icon(
            conv.isSavedInLibrary
                ? Icons.bookmark_rounded
                : (conv.projectId != null
                    ? Icons.folder_special_outlined
                    : Icons.chat_bubble_outline_rounded),
            size: 18,
            color: isSelected
                ? FDTheme.blue
                : (conv.projectId != null ? FDTheme.blue : FDTheme.subtle),
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
          subtitle: (conv.projectName != null && conv.projectName!.isNotEmpty)
              ? Text(
                  conv.projectName!,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 11,
                    color: FDTheme.blue,
                    fontWeight: FontWeight.w500,
                  ),
                )
              : null,
          trailing: PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert_rounded,
                size: 16, color: FDTheme.subtle),
            padding: EdgeInsets.zero,
            tooltip: 'Options',
            onSelected: (val) {
              if (val == 'rename') {
                widget.onRenameConversation(conv.id, conv.title);
              } else if (val == 'library') {
                widget.onToggleLibrary(conv.id);
              } else if (val == 'delete') {
                widget.onDeleteConversation(conv.id);
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
                    Icon(
                        conv.isSavedInLibrary
                            ? Icons.bookmark_remove_outlined
                            : Icons.bookmark_add_outlined,
                        size: 16),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text(
                        conv.isSavedInLibrary
                            ? 'Retirer de Library'
                            : 'Sauvegarder dans Library',
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
                    Icon(Icons.delete_outline_rounded,
                        size: 16, color: Color(0xFFDC2626)),
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
          onTap: () => widget.onSelectConversation(conv.id),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final q = _searchQuery.trim().toLowerCase();
    final visibleConvs = q.isEmpty
        ? widget.conversations
        : widget.conversations.where((c) {
            if (c.title.toLowerCase().contains(q)) return true;
            return c.messages.any((m) => m.text.toLowerCase().contains(q));
          }).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Bouton primaire Nouvelle conversation
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          child: FilledButton.icon(
            onPressed: widget.onNewConversation,
            icon: const Icon(Icons.add_rounded, size: 20),
            label: const Text('Nouvelle conversation',
                style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
            style: FilledButton.styleFrom(
              backgroundColor: FDTheme.blue,
              foregroundColor: Colors.white,
              minimumSize: const Size.fromHeight(46),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12)),
            ),
          ),
        ),
        // Zone défilante : Espace de travail + Espace PRO + Historique récent
        Expanded(
          child: ListView(
            padding: EdgeInsets.zero,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(20, 10, 20, 6),
                child: Text(
                  'IA & SAVOIR',
                  style: TextStyle(
                    fontSize: 11.5,
                    color: FDTheme.subtle,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.8,
                  ),
                ),
              ),
              _navItem(0, Icons.chat_bubble_outline_rounded, 'Assistant IA'),
              _navItem(1, Icons.explore_outlined, 'Explorer'),
              _navItem(2, Icons.bookmark_outline_rounded, 'Bibliothèque'),
              if (widget.hasPremiumKey)
                _navItem(3, Icons.folder_special_outlined, 'Projets PRO'),
              const Padding(
                padding: EdgeInsets.fromLTRB(20, 14, 20, 6),
                child: Text(
                  'INTELLIGENCE SECTORIELLE',
                  style: TextStyle(
                    fontSize: 11.5,
                    color: FDTheme.subtle,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.8,
                  ),
                ),
              ),
              _navItem(4, Icons.show_chart_rounded, 'Marchés & Crédit'),
              _navItem(
                5,
                Icons.eco_outlined,
                widget.hasPremiumKey
                    ? 'Agriculture · Agro PRO'
                    : 'Agriculture',
              ),
              const Divider(
                  height: 18, thickness: 1, color: FDTheme.canvasSoft),
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 4, 10, 4),
                child: Row(
                  children: [
                    const Expanded(
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
                    IconButton(
                      icon: Icon(
                        _searching ? Icons.close_rounded : Icons.search_rounded,
                        size: 17,
                        color: FDTheme.subtle,
                      ),
                      tooltip: _searching
                          ? 'Fermer la recherche'
                          : 'Rechercher dans l’historique',
                      padding: EdgeInsets.zero,
                      constraints:
                          const BoxConstraints(minWidth: 28, minHeight: 28),
                      onPressed: () {
                        setState(() {
                          _searching = !_searching;
                          if (!_searching) {
                            _searchQuery = '';
                            _searchCtrl.clear();
                          }
                        });
                      },
                    ),
                  ],
                ),
              ),
              if (_searching)
                Padding(
                  padding: const EdgeInsets.fromLTRB(14, 2, 14, 8),
                  child: TextField(
                    controller: _searchCtrl,
                    autofocus: true,
                    onChanged: (v) => setState(() => _searchQuery = v),
                    decoration: const InputDecoration(
                      hintText: 'Filtrer les discussions…',
                      isDense: true,
                      prefixIcon: Icon(Icons.search_rounded, size: 17),
                      contentPadding:
                          EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    ),
                  ),
                ),
              if (visibleConvs.isEmpty)
                Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                  child: Text(
                    q.isNotEmpty
                        ? 'Aucune conversation ne correspond.'
                        : 'Aucune conversation enregistrée.',
                    style: const TextStyle(fontSize: 14, color: FDTheme.muted),
                  ),
                )
              else
                ..._buildGroupedConversations(visibleConvs),
            ],
          ),
        ),
        // Pied de Sidebar façon ChatGPT (Profil / Compte + Accès PRO)
        const Divider(height: 1, thickness: 1, color: FDTheme.line),
        if (widget.isAuthenticated)
          _buildAuthenticatedFooter()
        else
          _buildGuestFooter(),
      ],
    );
  }

  Widget _buildAuthenticatedFooter() {
    final user = widget.authUser;
    final name = user?['display_name']?.toString().trim() ?? '';
    final email = user?['email']?.toString().trim() ?? '';
    final displayTitle =
        name.isNotEmpty ? name : (email.isNotEmpty ? email : 'Mon compte');
    final displaySubtitle = widget.hasPremiumKey
        ? 'Partenaire PRO · Cloud sync'
        : (name.isNotEmpty && email.isNotEmpty
            ? email
            : 'Plan Gratuit · Cloud sync');

    return Padding(
      padding: const EdgeInsets.all(10),
      child: PopupMenuButton<String>(
        tooltip: 'Menu du compte',
        offset: const Offset(0, -268),
        color: FDTheme.surface,
        surfaceTintColor: Colors.transparent,
        elevation: 10,
        shadowColor: FDTheme.shadow,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: const BorderSide(color: FDTheme.line),
        ),
        constraints: const BoxConstraints(minWidth: 252, maxWidth: 260),
        onSelected: (val) {
          if (val == 'account') {
            widget.onOpenAccount();
          } else if (val == 'subscription') {
            widget.onOpenSubscription();
          } else if (val == 'settings') {
            widget.onOpenSettings();
          } else if (val == 'support') {
            widget.onOpenSupport();
          } else if (val == 'docs') {
            widget.onOpenDocs();
          } else if (val == 'logout') {
            widget.onLogout();
          }
        },
        itemBuilder: (_) => [
          PopupMenuItem<String>(
            enabled: false,
            height: 44,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  displayTitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: FDTheme.ink,
                  ),
                ),
                if (email.isNotEmpty && email != displayTitle)
                  Text(
                    email,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 11.5,
                      color: FDTheme.subtle,
                    ),
                  ),
              ],
            ),
          ),
          const PopupMenuDivider(height: 8),
          _MainShellState._buildMenuOption(
            value: 'account',
            icon: Icons.person_outline_rounded,
            label: 'Mon compte & Profil',
          ),
          _MainShellState._buildMenuOption(
            value: 'subscription',
            icon: Icons.workspace_premium_outlined,
            label:
                widget.hasPremiumKey ? 'Abonnement & Quotas' : 'Passer à PRO',
            highlight: !widget.hasPremiumKey,
          ),
          _MainShellState._buildMenuOption(
            value: 'settings',
            icon: Icons.tune_rounded,
            label: 'Préférences',
          ),
          _MainShellState._buildMenuOption(
            value: 'support',
            icon: Icons.support_agent_outlined,
            label: 'Assistance & Avis',
          ),
          _MainShellState._buildMenuOption(
            value: 'docs',
            icon: Icons.menu_book_outlined,
            label: 'Documentation',
          ),
          const PopupMenuDivider(height: 8),
          _MainShellState._buildMenuOption(
            value: 'logout',
            icon: Icons.logout_rounded,
            label: 'Se déconnecter',
            color: FDTheme.danger,
          ),
        ],
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            color: FDTheme.canvas,
            border: Border.all(color: FDTheme.line),
          ),
          child: Row(
            children: [
              CircleAvatar(
                radius: 17,
                backgroundColor: FDTheme.blue,
                child: Text(
                  _initials(user),
                  style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w800,
                      fontSize: 12),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      displayTitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w700,
                          color: FDTheme.ink),
                    ),
                    Text(
                      displaySubtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 11.5,
                        color: widget.hasPremiumKey
                            ? FDTheme.greenDark
                            : FDTheme.subtle,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                decoration: BoxDecoration(
                  color: widget.hasPremiumKey
                      ? FDTheme.greenSoft
                      : FDTheme.surface,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                    color: widget.hasPremiumKey
                        ? FDTheme.green.withValues(alpha: 0.3)
                        : FDTheme.line,
                  ),
                ),
                child: Text(
                  widget.hasPremiumKey ? 'PRO' : 'Gratuit',
                  style: TextStyle(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w700,
                    color: widget.hasPremiumKey
                        ? FDTheme.greenDark
                        : FDTheme.muted,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildGuestFooter() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        // Sur Desktop, Se connecter / S'inscrire sont déjà en haut à droite (pas de doublon dans la sidebar).
        if (widget.isDrawer && !widget.hasPremiumKey)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 2),
            child: Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: widget.onLogin,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: FDTheme.ink,
                      side: const BorderSide(color: FDTheme.line),
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      minimumSize: const Size(0, 34),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8)),
                    ),
                    child: const Text('Connexion',
                        style: TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton(
                    onPressed: widget.onRegister,
                    style: FilledButton.styleFrom(
                      backgroundColor: FDTheme.ink,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      minimumSize: const Size(0, 34),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8)),
                    ),
                    child: const Text('Créer compte',
                        style: TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                ),
              ],
            ),
          ),
        Padding(
          padding: const EdgeInsets.all(10.0),
          child: Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: widget.hasPremiumKey ? widget.onConfigurePremiumKey : null,
              borderRadius: BorderRadius.circular(10),
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
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
                            widget.hasPremiumKey
                                ? 'Accès Partenaire actif · Tchad'
                                : 'Intelligence des Marchés · Tchad',
                            style: TextStyle(
                              fontSize: 12.0,
                              color: widget.hasPremiumKey
                                  ? FDTheme.greenDark
                                  : FDTheme.subtle,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                    if (widget.hasPremiumKey) ...[
                      const SizedBox(width: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 7, vertical: 3),
                        decoration: BoxDecoration(
                          color: FDTheme.greenSoft,
                          borderRadius: BorderRadius.circular(6),
                          border: Border.all(
                            color: FDTheme.green.withValues(alpha: 0.3),
                          ),
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
                    ],
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
    final isSelected = widget.currentIndex == index;
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
        onTap: () => widget.onSelectNavigation(index),
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
  late final TextEditingController _controller =
      TextEditingController(text: widget.initialKey);

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
        TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Annuler')),
        if (widget.hasActiveKey)
          TextButton(
            onPressed: () => Navigator.pop(context, ''),
            child: const Text('Désactiver la clé',
                style: TextStyle(color: FDTheme.danger)),
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
  State<_RenameConversationDialog> createState() =>
      _RenameConversationDialogState();
}

class _RenameConversationDialogState extends State<_RenameConversationDialog> {
  late final TextEditingController _controller =
      TextEditingController(text: widget.initialTitle);

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
        decoration:
            const InputDecoration(labelText: 'Titre de la conversation'),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Annuler')),
        FilledButton(
          onPressed: () => Navigator.pop(context, _controller.text.trim()),
          child: const Text('Enregistrer'),
        ),
      ],
    );
  }
}
