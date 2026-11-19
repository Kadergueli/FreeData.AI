import '../utils/formatters.dart';

typedef ChatConversation = ConversationThread;

class ConversationThread {
  final String id;
  final String title;
  final DateTime createdAt;
  final DateTime updatedAt;
  final bool isSavedInLibrary;
  final bool isDeleted;
  final String? projectId;
  final String? projectName;
  final List<ChatMessage> messages;

  const ConversationThread({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    this.isSavedInLibrary = false,
    this.isDeleted = false,
    this.projectId,
    this.projectName,
    this.messages = const [],
  });

  ConversationThread copyWith({
    String? id,
    String? title,
    DateTime? createdAt,
    DateTime? updatedAt,
    bool? isSavedInLibrary,
    bool? isDeleted,
    String? projectId,
    String? projectName,
    List<ChatMessage>? messages,
  }) {
    return ConversationThread(
      id: id ?? this.id,
      title: title ?? this.title,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      isSavedInLibrary: isSavedInLibrary ?? this.isSavedInLibrary,
      isDeleted: isDeleted ?? this.isDeleted,
      projectId: projectId ?? this.projectId,
      projectName: projectName ?? this.projectName,
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
        if (projectId != null && projectId!.isNotEmpty) 'projectId': projectId,
        if (projectName != null && projectName!.isNotEmpty)
          'projectName': projectName,
        'messages': messages.map((m) => m.toJson()).toList(),
      };

  factory ConversationThread.fromJson(Map<String, dynamic> json) {
    final list = (json['messages'] as List? ?? const [])
        .map((e) => ChatMessage.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();

    final rawProjId = json['projectId'] ?? json['project_id'];
    final rawProjName = json['projectName'] ?? json['project_name'];

    return ConversationThread(
      id: json['id']?.toString() ??
          DateTime.now().microsecondsSinceEpoch.toString(),
      title: json['title']?.toString() ?? 'Nouvelle conversation',
      createdAt: DateTime.tryParse(json['createdAt']?.toString() ?? '') ??
          DateTime.now(),
      updatedAt: DateTime.tryParse(json['updatedAt']?.toString() ?? '') ??
          DateTime.now(),
      isSavedInLibrary: json['isSavedInLibrary'] == true,
      isDeleted: json['isDeleted'] == true,
      projectId: rawProjId?.toString().trim().isNotEmpty == true
          ? rawProjId.toString().trim()
          : null,
      projectName: rawProjName?.toString().trim().isNotEmpty == true
          ? rawProjName.toString().trim()
          : null,
      messages: list,
    );
  }

  String get previewText {
    if (messages.isEmpty) return '';
    return stripMarkdown(messages.last.text);
  }
}

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
  }) =>
      ChatMessage(
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
      id: json['id']?.toString() ??
          DateTime.now().microsecondsSinceEpoch.toString(),
      role: json['role']?.toString() ?? 'assistant',
      text: json['text']?.toString() ?? '',
      sources: listSources,
      metadata: json['metadata'] is Map
          ? Map<String, dynamic>.from(json['metadata'] as Map)
          : const {},
      createdAt: DateTime.tryParse(json['createdAt']?.toString() ?? '') ??
          DateTime.now(),
    );
  }
}
