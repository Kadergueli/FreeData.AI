import 'dart:async';
import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import '../core/models/chat_models.dart';
import 'api_service.dart';

export '../core/models/chat_models.dart' show ConversationThread;
export '../core/utils/formatters.dart' show stripMarkdown;

abstract class ConversationRepository {
  Future<List<ConversationThread>> loadConversations(
      {bool includeDeleted = false});
  Future<ConversationThread?> getConversation(String id);
  Future<void> saveConversation(ConversationThread thread);
  Future<void> saveAll(List<ConversationThread> threads);
  Future<ConversationThread> createConversation({
    String? title,
    String? projectId,
    String? projectName,
  });
  Future<void> renameConversation(String id, String newTitle);
  Future<void> deleteConversation(String id);
  Future<void> restoreConversation(String id);
  Future<void> toggleLibrarySaved(String id, {bool? saved});
  Future<void> permanentlyDelete(String id);
}

class LocalConversationStorage implements ConversationRepository {
  static const String storageKey = 'fd_ai_conversations_v1';
  static const int maxStoredConversations = 100;
  static final LocalConversationStorage instance = LocalConversationStorage();

  Future<void>? _writeLock;
  ApiService? _cloudApi;

  void attachCloudApi(ApiService? api) {
    _cloudApi = api;
  }

  void _pushThreadInBackground(ConversationThread thread) {
    final api = _cloudApi;
    if (api == null || !api.isAuthenticated || thread.messages.isEmpty) return;
    unawaited(api.upsertCloudConversation(thread.toJson()).catchError((_) {}));
  }

  void _deleteThreadInBackground(String id) {
    final api = _cloudApi;
    if (api == null || !api.isAuthenticated) return;
    unawaited(api.deleteCloudConversation(id).catchError((_) {}));
  }

  Future<List<ConversationThread>> syncWithCloud(ApiService api) async {
    if (!api.isAuthenticated) return loadConversations();
    final localAll = await _loadInternal(includeDeleted: true);
    final mergedRaw = await api
        .syncCloudConversations(localAll.map((c) => c.toJson()).toList());
    final mergedThreads = <ConversationThread>[];
    for (final raw in mergedRaw) {
      try {
        final t = ConversationThread.fromJson(raw);
        if (t.messages.isNotEmpty) mergedThreads.add(t);
      } catch (_) {}
    }
    await saveAll(mergedThreads);
    return loadConversations();
  }

  Future<T> _synchronized<T>(Future<T> Function() action) {
    final prev = _writeLock ?? Future<void>.value();
    final completer = Completer<T>();
    late final Future<void> next;
    next = prev.catchError((_) {}).then((_) async {
      try {
        final result = await action();
        completer.complete(result);
      } catch (e, st) {
        completer.completeError(e, st);
      } finally {
        if (identical(_writeLock, next)) {
          _writeLock = null;
        }
      }
    });
    _writeLock = next;
    return completer.future;
  }

  Future<List<ConversationThread>> _loadInternal(
      {bool includeDeleted = false}) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(storageKey);
    if (raw == null || raw.isEmpty) return [];

    try {
      final decoded = jsonDecode(raw) as List;
      final all = decoded
          .map((item) => ConversationThread.fromJson(
              Map<String, dynamic>.from(item as Map)))
          .where((c) => c.messages.isNotEmpty)
          .toList();
      if (includeDeleted) return all;
      return all.where((c) => !c.isDeleted).toList();
    } catch (_) {
      await prefs.setString('${storageKey}_corrupted_backup', raw);
      return [];
    }
  }

  Future<void> _saveAllInternal(List<ConversationThread> threads) async {
    final prefs = await SharedPreferences.getInstance();
    final nonEmpty = threads.where((c) => c.messages.isNotEmpty).toList()
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    // Préserver les conversations enregistrées en Library lors du plafonnement à maxStoredConversations.
    final pinned =
        nonEmpty.where((c) => c.isSavedInLibrary && !c.isDeleted).toList();
    final others =
        nonEmpty.where((c) => !(c.isSavedInLibrary && !c.isDeleted)).toList();
    final remainingSlots = (maxStoredConversations - pinned.length)
        .clamp(0, maxStoredConversations);
    final kept = <ConversationThread>[
      ...pinned,
      ...others.take(remainingSlots),
    ]..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    final payload = kept.map((c) => c.toJson()).toList();
    await prefs.setString(storageKey, jsonEncode(payload));
  }

  @override
  Future<List<ConversationThread>> loadConversations(
      {bool includeDeleted = false}) {
    return _loadInternal(includeDeleted: includeDeleted);
  }

  @override
  Future<ConversationThread?> getConversation(String id) async {
    final all = await loadConversations(includeDeleted: true);
    for (final thread in all) {
      if (thread.id == id) return thread;
    }
    return null;
  }

  @override
  Future<void> saveConversation(ConversationThread thread) {
    if (thread.messages.isEmpty) return Future.value();
    return _synchronized(() async {
      final all = await _loadInternal(includeDeleted: true);
      final index = all.indexWhere((c) => c.id == thread.id);
      if (index >= 0) {
        all[index] = thread;
      } else {
        all.insert(0, thread);
      }
      await _saveAllInternal(all);
      _pushThreadInBackground(thread);
    });
  }

  @override
  Future<void> saveAll(List<ConversationThread> threads) {
    return _synchronized(() => _saveAllInternal(threads));
  }

  @override
  Future<ConversationThread> createConversation({
    String? title,
    String? projectId,
    String? projectName,
  }) async {
    final now = DateTime.now();
    return ConversationThread(
      id: const Uuid().v4(),
      title: title ?? 'Nouvelle conversation',
      createdAt: now,
      updatedAt: now,
      isSavedInLibrary: false,
      isDeleted: false,
      projectId: projectId,
      projectName: projectName,
      messages: const [],
    );
  }

  Future<List<ConversationThread>> listProjectConversations(
      String projectId) async {
    final all = await loadConversations(includeDeleted: false);
    return all.where((c) => c.projectId == projectId).toList();
  }

  @override
  Future<void> renameConversation(String id, String newTitle) {
    return _synchronized(() async {
      final all = await _loadInternal(includeDeleted: true);
      final index = all.indexWhere((c) => c.id == id);
      if (index >= 0) {
        all[index] =
            all[index].copyWith(title: newTitle, updatedAt: DateTime.now());
        await _saveAllInternal(all);
        _pushThreadInBackground(all[index]);
      }
    });
  }

  @override
  Future<void> deleteConversation(String id) {
    return _synchronized(() async {
      final all = await _loadInternal(includeDeleted: true);
      final index = all.indexWhere((c) => c.id == id);
      if (index >= 0) {
        all[index] =
            all[index].copyWith(isDeleted: true, updatedAt: DateTime.now());
        await _saveAllInternal(all);
        _pushThreadInBackground(all[index]);
      }
    });
  }

  @override
  Future<void> restoreConversation(String id) {
    return _synchronized(() async {
      final all = await _loadInternal(includeDeleted: true);
      final index = all.indexWhere((c) => c.id == id);
      if (index >= 0) {
        all[index] =
            all[index].copyWith(isDeleted: false, updatedAt: DateTime.now());
        await _saveAllInternal(all);
        _pushThreadInBackground(all[index]);
      }
    });
  }

  @override
  Future<void> toggleLibrarySaved(String id, {bool? saved}) {
    return _synchronized(() async {
      final all = await _loadInternal(includeDeleted: true);
      final index = all.indexWhere((c) => c.id == id);
      if (index >= 0) {
        final current = all[index];
        final nextSaved = saved ?? !current.isSavedInLibrary;
        all[index] = current.copyWith(
            isSavedInLibrary: nextSaved, updatedAt: DateTime.now());
        await _saveAllInternal(all);
        _pushThreadInBackground(all[index]);
      }
    });
  }

  @override
  Future<void> permanentlyDelete(String id) {
    return _synchronized(() async {
      final all = await _loadInternal(includeDeleted: true);
      all.removeWhere((c) => c.id == id);
      await _saveAllInternal(all);
      _deleteThreadInBackground(id);
    });
  }
}
