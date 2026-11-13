import 'dart:convert';
import '../../services/conversation_storage.dart';

export '../../services/conversation_storage.dart' show ConversationThread;

typedef ChatConversation = ConversationThread;

class ChatMessage {
  final String id;
  final String role;
  final String text;
  final List<Map<String, dynamic>> sources;
  final Map<String, dynamic> metadata;
  final DateTime createdAt;

  const ChatMessage({
    required this.id,
    required this.role,
    required this.text,
    required this.sources,
    required this.metadata,
    required this.createdAt,
  });

  factory ChatMessage.user(String text) => ChatMessage(
        id: DateTime.now().microsecondsSinceEpoch.toString(),
        role: 'user',
        text: text,
        sources: const [],
        metadata: const {},
        createdAt: DateTime.now(),
      );

  factory ChatMessage.assistant({
    required String text,
    List<Map<String, dynamic>> sources = const [],
    Map<String, dynamic> metadata = const {},
  }) => ChatMessage(
        id: DateTime.now().microsecondsSinceEpoch.toString(),
        role: 'assistant',
        text: text,
        sources: sources,
        metadata: metadata,
        createdAt: DateTime.now(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'role': role,
        'text': text,
        'sources': sources,
        'metadata': metadata,
        'createdAt': createdAt.toIso8601String(),
      };

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final rawSources = json['sources'];
    final listSources = rawSources is List
        ? rawSources.map((e) => Map<String, dynamic>.from(e as Map)).toList()
        : <Map<String, dynamic>>[];

    return ChatMessage(
      id: json['id']?.toString() ?? DateTime.now().microsecondsSinceEpoch.toString(),
      role: json['role']?.toString() ?? 'assistant',
      text: json['text']?.toString() ?? '',
      sources: listSources,
      metadata: json['metadata'] is Map ? Map<String, dynamic>.from(json['metadata'] as Map) : const {},
      createdAt: DateTime.tryParse(json['createdAt']?.toString() ?? '') ?? DateTime.now(),
    );
  }
}

class ConversationSummary {
  final String title;
  final DateTime updatedAt;
  final String preview;

  const ConversationSummary({
    required this.title,
    required this.updatedAt,
    required this.preview,
  });
}

String safeJsonEncode(Object? data) => jsonEncode(data);
