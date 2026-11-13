import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import '../core/models/chat_models.dart';
import '../core/utils/formatters.dart';

export '../core/utils/formatters.dart' show stripMarkdown;

class ConversationThread {
  final String id;
  final String title;
  final DateTime createdAt;
  final DateTime updatedAt;
  final bool isSavedInLibrary;
  final bool isDeleted;
  final List<ChatMessage> messages;

  const ConversationThread({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    this.isSavedInLibrary = false,
    this.isDeleted = false,
    this.messages = const [],
  });

  ConversationThread copyWith({
    String? id,
    String? title,
    DateTime? createdAt,
    DateTime? updatedAt,
    bool? isSavedInLibrary,
    bool? isDeleted,
    List<ChatMessage>? messages,
  }) {
    return ConversationThread(
      id: id ?? this.id,
      title: title ?? this.title,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      isSavedInLibrary: isSavedInLibrary ?? this.isSavedInLibrary,
      isDeleted: isDeleted ?? this.isDeleted,
      messages: messages ?? this.messages,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'createdAt': createdAt.toIso8601String(),
        'updatedAt': updatedAt.toIso8601String(),
        'isSavedInLibrary': isSavedInLibrary,
        'isDeleted': isDeleted,
        'messages': messages.map((m) => m.toJson()).toList(),
      };

  factory ConversationThread.fromJson(Map<String, dynamic> json) {
    final list = (json['messages'] as List? ?? const [])
        .map((e) => ChatMessage.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();

    return ConversationThread(
      id: json['id']?.toString() ?? DateTime.now().microsecondsSinceEpoch.toString(),
      title: json['title']?.toString() ?? 'Nouvelle conversation',
      createdAt: DateTime.tryParse(json['createdAt']?.toString() ?? '') ?? DateTime.now(),
      updatedAt: DateTime.tryParse(json['updatedAt']?.toString() ?? '') ?? DateTime.now(),
      isSavedInLibrary: json['isSavedInLibrary'] == true,
      isDeleted: json['isDeleted'] == true,
      messages: list,
    );
  }

  String get previewText {
    if (messages.isEmpty) return '';
    return stripMarkdown(messages.last.text);
  }
}

abstract class ConversationRepository {
  Future<List<ConversationThread>> loadConversations({bool includeDeleted = false});
  Future<ConversationThread?> getConversation(String id);
  Future<void> saveConversation(ConversationThread thread);
  Future<void> saveAll(List<ConversationThread> threads);
  Future<ConversationThread> createConversation({String? title});
  Future<void> renameConversation(String id, String newTitle);
  Future<void> deleteConversation(String id);
  Future<void> restoreConversation(String id);
  Future<void> toggleLibrarySaved(String id, {bool? saved});
  Future<void> permanentlyDelete(String id);
}

class LocalConversationStorage implements ConversationRepository {
  static const String storageKey = 'fd_ai_conversations_v1';
  static final LocalConversationStorage instance = LocalConversationStorage();

  @override
  Future<List<ConversationThread>> loadConversations({bool includeDeleted = false}) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(storageKey);
    if (raw == null || raw.isEmpty) return [];

    try {
      final decoded = jsonDecode(raw) as List;
      final all = decoded
          .map((item) => ConversationThread.fromJson(Map<String, dynamic>.from(item as Map)))
          .where((c) => c.messages.isNotEmpty)
          .toList();
      if (includeDeleted) return all;
      return all.where((c) => !c.isDeleted).toList();
    } catch (_) {
      return [];
    }
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
  Future<void> saveConversation(ConversationThread thread) async {
    if (thread.messages.isEmpty) return;
    final all = await loadConversations(includeDeleted: true);
    final index = all.indexWhere((c) => c.id == thread.id);
    if (index >= 0) {
      all[index] = thread;
    } else {
      all.insert(0, thread);
    }
    await saveAll(all);
  }

  @override
  Future<void> saveAll(List<ConversationThread> threads) async {
    final prefs = await SharedPreferences.getInstance();
    final payload = threads
        .where((c) => c.messages.isNotEmpty)
        .map((c) => c.toJson())
        .toList();
    await prefs.setString(storageKey, jsonEncode(payload));
  }

  @override
  Future<ConversationThread> createConversation({String? title}) async {
    final now = DateTime.now();
    return ConversationThread(
      id: const Uuid().v4(),
      title: title ?? 'Nouvelle conversation',
      createdAt: now,
      updatedAt: now,
      isSavedInLibrary: false,
      isDeleted: false,
      messages: const [],
    );
  }

  @override
  Future<void> renameConversation(String id, String newTitle) async {
    final all = await loadConversations(includeDeleted: true);
    final index = all.indexWhere((c) => c.id == id);
    if (index >= 0) {
      all[index] = all[index].copyWith(title: newTitle, updatedAt: DateTime.now());
      await saveAll(all);
    }
  }

  @override
  Future<void> deleteConversation(String id) async {
    final all = await loadConversations(includeDeleted: true);
    final index = all.indexWhere((c) => c.id == id);
    if (index >= 0) {
      all[index] = all[index].copyWith(isDeleted: true, updatedAt: DateTime.now());
      await saveAll(all);
    }
  }

  @override
  Future<void> restoreConversation(String id) async {
    final all = await loadConversations(includeDeleted: true);
    final index = all.indexWhere((c) => c.id == id);
    if (index >= 0) {
      all[index] = all[index].copyWith(isDeleted: false, updatedAt: DateTime.now());
      await saveAll(all);
    }
  }

  @override
  Future<void> toggleLibrarySaved(String id, {bool? saved}) async {
    final all = await loadConversations(includeDeleted: true);
    final index = all.indexWhere((c) => c.id == id);
    if (index >= 0) {
      final current = all[index];
      final nextSaved = saved ?? !current.isSavedInLibrary;
      all[index] = current.copyWith(isSavedInLibrary: nextSaved, updatedAt: DateTime.now());
      await saveAll(all);
    }
  }

  @override
  Future<void> permanentlyDelete(String id) async {
    final all = await loadConversations(includeDeleted: true);
    all.removeWhere((c) => c.id == id);
    await saveAll(all);
  }
}

