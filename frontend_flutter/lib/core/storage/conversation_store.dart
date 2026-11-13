import 'package:uuid/uuid.dart';
import '../../services/conversation_storage.dart';

class ConversationStore {
  static Future<List<ConversationThread>> load({bool includeDeleted = false}) =>
      LocalConversationStorage.instance.loadConversations(includeDeleted: includeDeleted);

  static Future<void> save(List<ConversationThread> conversations) =>
      LocalConversationStorage.instance.saveAll(conversations);

  static ConversationThread createConversation({String? title}) {
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
}
