import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/fd_theme.dart';
import '../services/api_service.dart';
import '../services/conversation_storage.dart';

export '../core/utils/formatters.dart' show stripMarkdown;

class LibraryScreen extends StatefulWidget {
  final ApiService apiService;
  final List<ConversationThread>? conversations;
  final VoidCallback? onConversationsUpdated;
  final void Function(String conversationId)? onOpenConversation;

  const LibraryScreen({
    super.key,
    required this.apiService,
    this.conversations,
    this.onConversationsUpdated,
    this.onOpenConversation,
  });

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  final TextEditingController _searchController = TextEditingController();
  List<ConversationThread> _allConversations = const [];
  bool _loading = true;
  String _searchQuery = '';
  bool _showTrash = false;
  bool _filterSavedOnly = false;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    if (widget.conversations != null && widget.conversations!.isNotEmpty) {
      _allConversations = widget.conversations!;
      _loading = false;
    }
    _load();
  }

  @override
  void didUpdateWidget(covariant LibraryScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    final incoming = widget.conversations;
    if (incoming != null && incoming != oldWidget.conversations) {
      // Recharger le stockage complet (y compris corbeille) pour capter les suppressions faites depuis la barre latérale.
      _load();
    }
  }

  Future<void> _load() async {
    final conversations = await LocalConversationStorage.instance
        .loadConversations(includeDeleted: true);
    if (!mounted) return;
    setState(() {
      _allConversations = conversations;
      _loading = false;
    });
  }

  Future<void> _toggleBookmark(String id) async {
    await LocalConversationStorage.instance.toggleLibrarySaved(id);
    await _load();
    widget.onConversationsUpdated?.call();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Statut de sauvegarde mis à jour dans la Bibliothèque'),
        duration: Duration(seconds: 2),
      ),
    );
  }

  Future<void> _delete(String id) async {
    await LocalConversationStorage.instance.deleteConversation(id);
    await _load();
    widget.onConversationsUpdated?.call();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Conversation déplacée vers la Corbeille'),
        duration: Duration(seconds: 2),
      ),
    );
  }

  Future<void> _restore(String id) async {
    await LocalConversationStorage.instance.restoreConversation(id);
    await _load();
    widget.onConversationsUpdated?.call();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Conversation restaurée avec succès'),
        duration: Duration(seconds: 2),
      ),
    );
  }

  Future<void> _permanentlyDelete(String id) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Supprimer définitivement ?'),
        content: const Text(
          'Cette conversation sera définitivement effacée du stockage local et ne pourra plus être restaurée.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFDC2626)),
            child: const Text('Supprimer'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    await LocalConversationStorage.instance.permanentlyDelete(id);
    await _load();
    widget.onConversationsUpdated?.call();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Conversation définitivement supprimée'),
        duration: Duration(seconds: 2),
      ),
    );
  }

  void _exportMarkdown(ConversationThread conv) {
    final buffer = StringBuffer();
    buffer.writeln('# ${conv.title}');
    buffer.writeln('Date : ${conv.updatedAt.toIso8601String()}');
    buffer.writeln('');
    for (final msg in conv.messages) {
      if (msg.role == 'user') {
        buffer.writeln('### Utilisateur');
        buffer.writeln(msg.text);
        buffer.writeln('');
      } else {
        buffer.writeln('### Assistant FreeData.AI');
        buffer.writeln(msg.text);
        buffer.writeln('');
      }
    }

    Clipboard.setData(ClipboardData(text: buffer.toString()));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
            'Export Markdown copié dans le presse-papiers pour "${conv.title}" (.md)'),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 720;

    final nonEmptyConversations =
        _allConversations.where((c) => c.messages.isNotEmpty).toList();
    final activeConversations =
        nonEmptyConversations.where((c) => !c.isDeleted).toList();
    final savedConversations =
        activeConversations.where((c) => c.isSavedInLibrary).toList();
    final deletedConversations =
        nonEmptyConversations.where((c) => c.isDeleted).toList();

    List<ConversationThread> baseList;
    if (_showTrash) {
      baseList = deletedConversations;
    } else if (_filterSavedOnly) {
      baseList = savedConversations;
    } else {
      baseList = activeConversations;
    }

    final displayedList = baseList.where((c) {
      if (_searchQuery.isEmpty) return true;
      final q = _searchQuery.toLowerCase();
      final inTitle = c.title.toLowerCase().contains(q);
      final inMessages =
          c.messages.any((m) => m.text.toLowerCase().contains(q));
      return inTitle || inMessages;
    }).toList();

    return Material(
      color: Colors.white,
      child: RefreshIndicator(
        onRefresh: () async {
          await _load();
          widget.onConversationsUpdated?.call();
        },
        child: SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding:
              EdgeInsets.fromLTRB(compact ? 18 : 32, 24, compact ? 18 : 32, 36),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1100),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'Bibliothèque',
                          style: TextStyle(
                            fontSize: 26,
                            fontWeight: FontWeight.w800,
                            color: FDTheme.ink,
                          ),
                        ),
                      ),
                      Visibility(
                        visible: !compact,
                        child: IconButton(
                          icon: const Icon(
                            Icons.refresh_rounded,
                            size: 22,
                            color: Color(0xFF64748B),
                          ),
                          tooltip: 'Rafraîchir',
                          onPressed: () {
                            _load();
                            widget.onConversationsUpdated?.call();
                          },
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Retrouvez vos conversations, vos favoris et les éléments placés dans la corbeille.',
                    style: TextStyle(
                      color: FDTheme.muted,
                      fontSize: 15,
                      height: 1.5,
                    ),
                  ),
                  const SizedBox(height: 18),
                  // Barre de recherche
                  TextField(
                    controller: _searchController,
                    onChanged: (v) => setState(() => _searchQuery = v.trim()),
                    style: const TextStyle(
                        fontSize: 15.5, color: Color(0xFF0F172A)),
                    decoration: InputDecoration(
                      hintText:
                          'Rechercher dans les conversations et analyses…',
                      hintStyle: const TextStyle(
                          fontSize: 15, color: Color(0xFF94A3B8)),
                      prefixIcon: const Icon(Icons.search_rounded,
                          size: 22, color: Color(0xFF64748B)),
                      suffixIcon: _searchQuery.isEmpty
                          ? null
                          : IconButton(
                              icon: const Icon(Icons.close_rounded,
                                  size: 20, color: Color(0xFF64748B)),
                              tooltip: 'Effacer la recherche',
                              onPressed: () {
                                _searchController.clear();
                                setState(() => _searchQuery = '');
                              },
                            ),
                      filled: true,
                      fillColor: const Color(0xFFF8FAFC),
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 14),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(14),
                        borderSide: const BorderSide(color: Color(0xFFE2E8F0)),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(14),
                        borderSide: const BorderSide(color: Color(0xFFE2E8F0)),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  // Sélecteur de filtres sur une seule ligne
                  SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(
                      children: [
                        ChoiceChip(
                          avatar: Icon(
                            Icons.chat_bubble_outline_rounded,
                            size: 16,
                            color: (!_showTrash && !_filterSavedOnly)
                                ? const Color(0xFF1D4ED8)
                                : const Color(0xFF64748B),
                          ),
                          label: Text('Toutes (${activeConversations.length})'),
                          selected: !_showTrash && !_filterSavedOnly,
                          selectedColor: const Color(0xFFEFF6FF),
                          labelStyle: TextStyle(
                            color: (!_showTrash && !_filterSavedOnly)
                                ? const Color(0xFF1D4ED8)
                                : const Color(0xFF334155),
                            fontWeight: FontWeight.w600,
                            fontSize: 14,
                          ),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 4, vertical: 6),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10)),
                          onSelected: (val) => setState(() {
                            _showTrash = false;
                            _filterSavedOnly = false;
                          }),
                        ),
                        const SizedBox(width: 8),
                        ChoiceChip(
                          avatar: Icon(
                            Icons.bookmark_rounded,
                            size: 16,
                            color: (!_showTrash && _filterSavedOnly)
                                ? const Color(0xFF1D4ED8)
                                : const Color(0xFF64748B),
                          ),
                          label: Text('Favoris (${savedConversations.length})'),
                          selected: !_showTrash && _filterSavedOnly,
                          selectedColor: const Color(0xFFEFF6FF),
                          labelStyle: TextStyle(
                            color: (!_showTrash && _filterSavedOnly)
                                ? const Color(0xFF1D4ED8)
                                : const Color(0xFF334155),
                            fontWeight: FontWeight.w600,
                            fontSize: 14,
                          ),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 4, vertical: 6),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10)),
                          onSelected: (val) => setState(() {
                            _showTrash = false;
                            _filterSavedOnly = true;
                          }),
                        ),
                        const SizedBox(width: 8),
                        ChoiceChip(
                          avatar: Icon(
                            Icons.delete_outline_rounded,
                            size: 16,
                            color: _showTrash
                                ? const Color(0xFFDC2626)
                                : const Color(0xFF64748B),
                          ),
                          label: Text(
                              'Corbeille (${deletedConversations.length})'),
                          selected: _showTrash,
                          selectedColor: const Color(0xFFFEF2F2),
                          labelStyle: TextStyle(
                            color: _showTrash
                                ? const Color(0xFFDC2626)
                                : const Color(0xFF64748B),
                            fontWeight: FontWeight.w600,
                            fontSize: 14,
                          ),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 4, vertical: 6),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10)),
                          onSelected: (val) => setState(() {
                            _showTrash = true;
                            _filterSavedOnly = false;
                          }),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  if (_loading)
                    const FDLoadingState(
                        message: 'Chargement de la bibliothèque…')
                  else if (displayedList.isEmpty)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 24),
                      child: FDEmptyState(
                        title: _showTrash
                            ? 'Corbeille vide'
                            : 'Aucune conversation pour le moment',
                        subtitle: _showTrash
                            ? 'Les conversations mises à la corbeille peuvent être restaurées ici.'
                            : 'Vos échanges apparaîtront ici après votre première conversation avec l’IA.',
                        icon: _showTrash
                            ? Icons.delete_outline_rounded
                            : Icons.history_rounded,
                      ),
                    )
                  else
                    Column(
                      children: displayedList.map((conv) {
                        final isDeleted = _showTrash;
                        return Card(
                          margin: const EdgeInsets.only(bottom: 12),
                          elevation: 0,
                          color: isDeleted
                              ? const Color(0xFFFFF7F7)
                              : Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14),
                            side: BorderSide(
                              color: isDeleted
                                  ? const Color(0xFFFECACA)
                                  : const Color(0xFFE2E8F0),
                              width: 1.2,
                            ),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    IconButton(
                                      icon: Icon(
                                        isDeleted
                                            ? Icons.delete_outline_rounded
                                            : (conv.isSavedInLibrary
                                                ? Icons.bookmark_rounded
                                                : Icons
                                                    .bookmark_border_rounded),
                                        size: 20,
                                        color: isDeleted
                                            ? FDTheme.danger
                                            : (conv.isSavedInLibrary
                                                ? FDTheme.blue
                                                : FDTheme.subtle),
                                      ),
                                      tooltip: conv.isSavedInLibrary
                                          ? 'Retirer des favoris'
                                          : 'Enregistrer dans la Bibliothèque',
                                      padding: const EdgeInsets.all(10),
                                      constraints: const BoxConstraints(
                                          minWidth: 44, minHeight: 44),
                                      onPressed: isDeleted
                                          ? null
                                          : () => _toggleBookmark(conv.id),
                                    ),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: Text(
                                        conv.title,
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w700,
                                          fontSize: 16.5,
                                          color: FDTheme.ink,
                                        ),
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                    if (!isDeleted) ...[
                                      IconButton(
                                        icon: const Icon(Icons.download_rounded,
                                            size: 20, color: FDTheme.subtle),
                                        tooltip: 'Exporter (.md)',
                                        padding: const EdgeInsets.all(10),
                                        constraints: const BoxConstraints(
                                            minWidth: 44, minHeight: 44),
                                        onPressed: () => _exportMarkdown(conv),
                                      ),
                                      IconButton(
                                        icon: const Icon(
                                            Icons.delete_outline_rounded,
                                            size: 20,
                                            color: FDTheme.danger),
                                        tooltip: 'Mettre à la corbeille',
                                        padding: const EdgeInsets.all(10),
                                        constraints: const BoxConstraints(
                                            minWidth: 44, minHeight: 44),
                                        onPressed: () => _delete(conv.id),
                                      ),
                                    ] else ...[
                                      TextButton.icon(
                                        onPressed: () => _restore(conv.id),
                                        icon: const Icon(Icons.restore_rounded,
                                            size: 18, color: FDTheme.green),
                                        label: const Text('Restaurer',
                                            style: TextStyle(
                                                color: FDTheme.green,
                                                fontSize: 13,
                                                fontWeight: FontWeight.w600)),
                                      ),
                                      IconButton(
                                        icon: const Icon(
                                            Icons.delete_forever_rounded,
                                            size: 20,
                                            color: FDTheme.danger),
                                        tooltip: 'Supprimer définitivement',
                                        padding: const EdgeInsets.all(10),
                                        constraints: const BoxConstraints(
                                            minWidth: 44, minHeight: 44),
                                        onPressed: () =>
                                            _permanentlyDelete(conv.id),
                                      ),
                                    ],
                                  ],
                                ),
                                const SizedBox(height: 8),
                                Text(
                                  stripMarkdown(conv.previewText),
                                  style: const TextStyle(
                                    fontSize: 14.5,
                                    color: FDTheme.muted,
                                    height: 1.5,
                                  ),
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                ),
                                const SizedBox(height: 12),
                                Row(
                                  children: [
                                    Expanded(
                                      child: Text(
                                        '${conv.messages.length} message(s) · Modifié le ${conv.updatedAt.day.toString().padLeft(2, '0')}/${conv.updatedAt.month.toString().padLeft(2, '0')}/${conv.updatedAt.year}',
                                        style: const TextStyle(
                                            fontSize: 13,
                                            color: Color(0xFF94A3B8)),
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                    if (!isDeleted &&
                                        widget.onOpenConversation != null)
                                      TextButton.icon(
                                        onPressed: () =>
                                            widget.onOpenConversation!(conv.id),
                                        icon: const Icon(
                                            Icons.arrow_forward_rounded,
                                            size: 16),
                                        label: const Text('Ouvrir l’échange',
                                            style: TextStyle(
                                                fontSize: 13.5,
                                                fontWeight: FontWeight.w600)),
                                        style: TextButton.styleFrom(
                                          padding: const EdgeInsets.symmetric(
                                              horizontal: 10, vertical: 6),
                                          minimumSize: const Size(0, 36),
                                          tapTargetSize:
                                              MaterialTapTargetSize.shrinkWrap,
                                        ),
                                      ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        );
                      }).toList(),
                    ),
                  const SizedBox(height: 24),
                  // Cartes d'aide et statut
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final itemWidth = constraints.maxWidth < 700
                          ? constraints.maxWidth
                          : (constraints.maxWidth - 16) / 2;
                      return Wrap(
                        spacing: 16,
                        runSpacing: 16,
                        children: [
                          SizedBox(
                            width: itemWidth,
                            child: FDCard(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  const Row(
                                    children: [
                                      Icon(Icons.insights_rounded,
                                          color: FDTheme.blue, size: 22),
                                      SizedBox(width: 8),
                                      Expanded(
                                        child: Text(
                                          'Analyses',
                                          style: TextStyle(
                                              fontWeight: FontWeight.w700,
                                              color: FDTheme.ink,
                                              fontSize: 17),
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 8),
                                  const Text(
                                    'Synthèses et comparaisons de prix extraites de vos échanges.',
                                    style: TextStyle(
                                        fontSize: 14,
                                        color: FDTheme.muted,
                                        height: 1.5),
                                  ),
                                  const SizedBox(height: 12),
                                  FDBadge(
                                    label: 'DISPONIBLE EN LOCAL',
                                    color: FDTheme.green,
                                    backgroundColor:
                                        FDTheme.green.withValues(alpha: 0.10),
                                  ),
                                ],
                              ),
                            ),
                          ),
                          SizedBox(
                            width: itemWidth,
                            child: FDCard(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      Icon(
                                          widget.apiService.isAuthenticated
                                              ? Icons.cloud_done_outlined
                                              : Icons.storage_rounded,
                                          color:
                                              widget.apiService.isAuthenticated
                                                  ? FDTheme.green
                                                  : FDTheme.blue,
                                          size: 22),
                                      const SizedBox(width: 8),
                                      Expanded(
                                        child: Text(
                                          widget.apiService.isAuthenticated
                                              ? 'Stockage & Synchro Cloud'
                                              : 'Stockage local',
                                          style: const TextStyle(
                                              fontWeight: FontWeight.w700,
                                              color: FDTheme.ink,
                                              fontSize: 17),
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 8),
                                  Text(
                                    widget.apiService.isAuthenticated
                                        ? 'Vos conversations sont sauvegardées sur cet appareil et synchronisées automatiquement avec votre compte FreeData.AI.'
                                        : 'Vos conversations sont enregistrées uniquement sur cet appareil. Connectez-vous pour activer la synchronisation cloud multi-appareils.',
                                    style: const TextStyle(
                                        fontSize: 14,
                                        color: FDTheme.muted,
                                        height: 1.5),
                                  ),
                                  const SizedBox(height: 12),
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 6,
                                    children: [
                                      FDBadge(
                                        label: 'STOCKÉ LOCALEMENT',
                                        color: FDTheme.blue,
                                        backgroundColor: FDTheme.blue
                                            .withValues(alpha: 0.10),
                                      ),
                                      FDBadge(
                                        label: widget.apiService.isAuthenticated
                                            ? 'SYNCHRONISATION CLOUD ACTIVE'
                                            : 'SYNCHRONISATION INDISPONIBLE',
                                        color: widget.apiService.isAuthenticated
                                            ? FDTheme.greenDark
                                            : FDTheme.muted,
                                        backgroundColor:
                                            widget.apiService.isAuthenticated
                                                ? FDTheme.greenSoft
                                                : FDTheme.canvasSoft,
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ],
                      );
                    },
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
