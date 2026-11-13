import 'package:flutter/material.dart';
import 'core/fd_theme.dart';
import 'services/api_service.dart';
import 'services/conversation_storage.dart';
import 'screens/chat_screen.dart';
import 'screens/explore_screen.dart';
import 'screens/library_screen.dart';
import 'screens/forecast_screen.dart';
import 'screens/passport_screen.dart';

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
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _selectedIndex = 0;
  final ApiService _apiService = ApiService();
  String? _activeConversationId;
  String? _pendingPrompt;
  List<ConversationThread> _conversations = const [];

  @override
  void initState() {
    super.initState();
    _reloadConversations();
  }

  Future<void> _reloadConversations() async {
    final list = await LocalConversationStorage.instance.loadConversations();
    if (!mounted) return;
    setState(() {
      _conversations = list;
      if (_activeConversationId == null && list.isNotEmpty) {
        _activeConversationId = list.first.id;
      }
    });
  }

  Future<void> _createNewConversation() async {
    final newThread = await LocalConversationStorage.instance.createConversation();
    if (!mounted) return;
    setState(() {
      _selectedIndex = 0;
      _activeConversationId = newThread.id;
      _pendingPrompt = null;
    });
    await _reloadConversations();
  }

  void _openPromptInChat(String prompt) {
    setState(() {
      _selectedIndex = 0;
      _pendingPrompt = prompt;
    });
  }

  Future<void> _renameConversation(String id, String currentTitle) async {
    final controller = TextEditingController(text: currentTitle);
    final newTitle = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Renommer la conversation'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Titre de la conversation'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Annuler')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, controller.text.trim()),
            child: const Text('Enregistrer'),
          ),
        ],
      ),
    );

    if (newTitle != null && newTitle.isNotEmpty) {
      await LocalConversationStorage.instance.renameConversation(id, newTitle);
      _reloadConversations();
    }
  }

  Future<void> _deleteConversation(String id) async {
    await LocalConversationStorage.instance.deleteConversation(id);
    if (_activeConversationId == id) {
      _activeConversationId = null;
    }
    await _reloadConversations();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: const Text('Conversation mise à la corbeille'),
        action: SnackBarAction(
          label: 'Restaurer',
          onPressed: () async {
            await LocalConversationStorage.instance.restoreConversation(id);
            _reloadConversations();
          },
        ),
      ),
    );
  }

  Future<void> _toggleLibrary(String id) async {
    await LocalConversationStorage.instance.toggleLibrarySaved(id);
    await _reloadConversations();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
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
      ),
      ExploreScreen(
        apiService: _apiService,
        onSelectPrompt: _openPromptInChat,
      ),
      LibraryScreen(
        apiService: _apiService,
        conversations: _conversations,
        onConversationsUpdated: _reloadConversations,
        onOpenConversation: (id) {
          setState(() {
            _selectedIndex = 0;
            _activeConversationId = id;
          });
        },
      ),
      ForecastScreen(apiService: _apiService),
      PassportScreen(apiService: _apiService),
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
                onSelectNavigation: (index) => setState(() => _selectedIndex = index),
                onSelectConversation: (id) {
                  setState(() {
                    _selectedIndex = 0;
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
            const VerticalDivider(width: 1, thickness: 1, color: Color(0xFFE2E8F0)),
            Expanded(
              child: Column(
                children: [
                  Container(
                    height: 56,
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    decoration: const BoxDecoration(
                      color: Colors.white,
                      border: Border(bottom: BorderSide(color: Color(0xFFF1F5F9), width: 1)),
                    ),
                    child: Row(
                      children: [
                        Text(
                          _getTitle(_selectedIndex),
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: Color(0xFF0F172A),
                          ),
                        ),
                        const Spacer(),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                          decoration: BoxDecoration(
                            color: const Color(0xFFEFF6FF),
                            borderRadius: BorderRadius.circular(99),
                          ),
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.circle, size: 7, color: Color(0xFF1D4ED8)),
                              SizedBox(width: 6),
                              Text(
                                'Tchad · Marchés et Prix',
                                style: TextStyle(
                                  fontSize: 11,
                                  color: Color(0xFF1D4ED8),
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
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
            Container(
              width: 28,
              height: 28,
              decoration: BoxDecoration(
                color: const Color(0xFF1D4ED8),
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
            const SizedBox(width: 10),
            Text(
              _getTitle(_selectedIndex),
              style: const TextStyle(
                color: Color(0xFF0F172A),
                fontSize: 17.5,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.add_comment_outlined, size: 22, color: Color(0xFF1D4ED8)),
            tooltip: 'Nouvelle conversation',
            onPressed: _createNewConversation,
          ),
        ],
      ),
      drawer: Drawer(
        width: 290,
        backgroundColor: Colors.white,
        child: SafeArea(
          child: _SidebarContent(
            currentIndex: _selectedIndex,
            activeConversationId: _activeConversationId,
            conversations: _conversations,
            onSelectNavigation: (index) {
              setState(() => _selectedIndex = index);
              Navigator.of(context).pop();
            },
            onSelectConversation: (id) {
              setState(() {
                _selectedIndex = 0;
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
        // Bouton primaire + Nouvelle conversation
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          child: FilledButton.icon(
            onPressed: onNewConversation,
            icon: const Icon(Icons.add_rounded, size: 20),
            label: const Text('+ Nouvelle conversation', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFF1D4ED8),
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
              color: Color(0xFF64748B),
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
        const Divider(height: 18, thickness: 1, color: Color(0xFFF1F5F9)),
        // Historique des conversations récentes
        const Padding(
          padding: EdgeInsets.fromLTRB(20, 8, 20, 6),
          child: Text(
            'HISTORIQUE RÉCENT',
            style: TextStyle(
              fontSize: 12,
              color: Color(0xFF64748B),
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
                    style: TextStyle(fontSize: 14, color: Color(0xFF94A3B8)),
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
                        color: isSelected ? const Color(0xFFEFF6FF) : Colors.transparent,
                        borderRadius: BorderRadius.circular(8),
                        child: ListTile(
                          dense: false,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                          contentPadding: const EdgeInsets.only(left: 10, right: 4),
                          leading: Icon(
                            conv.isSavedInLibrary ? Icons.bookmark_rounded : Icons.chat_bubble_outline_rounded,
                            size: 18,
                            color: isSelected ? const Color(0xFF1D4ED8) : const Color(0xFF64748B),
                          ),
                          title: Text(
                            conv.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 14.5,
                              fontWeight: isSelected ? FontWeight.w600 : FontWeight.w500,
                              color: isSelected ? const Color(0xFF1D4ED8) : const Color(0xFF334155),
                            ),
                          ),
                          trailing: PopupMenuButton<String>(
                            icon: const Icon(Icons.more_vert_rounded, size: 16, color: Color(0xFF94A3B8)),
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
                                    Text('Renommer'),
                                  ],
                                ),
                              ),
                              PopupMenuItem(
                                value: 'library',
                                child: Row(
                                  children: [
                                    Icon(conv.isSavedInLibrary ? Icons.bookmark_remove_outlined : Icons.bookmark_add_outlined, size: 16),
                                    SizedBox(width: 8),
                                    Text(conv.isSavedInLibrary ? 'Retirer de Library' : 'Sauvegarder dans Library'),
                                  ],
                                ),
                              ),
                              const PopupMenuItem(
                                value: 'delete',
                                child: Row(
                                  children: [
                                    Icon(Icons.delete_outline_rounded, size: 16, color: Color(0xFFDC2626)),
                                    SizedBox(width: 8),
                                    Text('Supprimer', style: TextStyle(color: Color(0xFFDC2626))),
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
        const Divider(height: 1, thickness: 1, color: Color(0xFFE2E8F0)),
        Padding(
          padding: const EdgeInsets.all(16.0),
          child: Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: const Color(0xFF1D4ED8),
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
              const SizedBox(width: 10),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      'FreeData.AI',
                      style: TextStyle(
                        fontSize: 15.5,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF0F172A),
                      ),
                    ),
                    SizedBox(height: 2),
                    Text(
                      'Intelligence des Marchés · Tchad',
                      style: TextStyle(
                        fontSize: 12.5,
                        color: Color(0xFF64748B),
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
            ],
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
        tileColor: isSelected ? const Color(0xFFEFF6FF) : Colors.transparent,
        leading: Icon(
          icon,
          color: isSelected ? const Color(0xFF1D4ED8) : const Color(0xFF64748B),
          size: 22,
        ),
        title: Text(
          label,
          style: TextStyle(
            fontSize: 15.5,
            fontWeight: isSelected ? FontWeight.w600 : FontWeight.w500,
            color: isSelected ? const Color(0xFF1D4ED8) : const Color(0xFF0F172A),
          ),
        ),
        onTap: () => onSelectNavigation(index),
      ),
    );
  }
}
