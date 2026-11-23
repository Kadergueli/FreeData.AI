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
  Future<void> renameConversation(String id, String newTitle) {
    final key = activeStorageKey;
    return _synchronized(() async {
      final all = await _loadInternal(
        includeDeleted: true,
        storageKeyOverride: key,
      );
      final index = all.indexWhere((c) => c.id == id);
      if (index >= 0) {
        all[index] =
            all[index].copyWith(title: newTitle, updatedAt: DateTime.now());
        await _saveAllInternal(all, storageKeyOverride: key);
        if (activeStorageKey == key) {
          _pushThreadInBackground(all[index]);
        }
      }
    });
  });
  Future<void> permanentlyDelete(String id) {
    final key = activeStorageKey;
    return _synchronized(() async {
      final all = await _loadInternal(
        includeDeleted: true,
        storageKeyOverride: key,
      );
      all.removeWhere((c) => c.id == id);
      await _saveAllInternal(all, storageKeyOverride: key);
      if (activeStorageKey == key) _deleteThreadInBackground(id);
    });
  }
