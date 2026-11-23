import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:freedata_ai/core/models/chat_models.dart';
import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/conversation_storage.dart';

class _FakeApiService extends ApiService {
  @override
  Future<void> upsertCloudConversation(Map<String, dynamic> conversation) async {}

  @override
  Future<void> deleteCloudConversation(String conversationId) async {}
}

ConversationThread _thread(String id, String message) {
  final now = DateTime(2026, 11, 24);
  return ConversationThread(
    id: id,
    title: id,
    createdAt: now,
    updatedAt: now,
    messages: [ChatMessage.user(message)],
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late LocalConversationStorage storage;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    storage = LocalConversationStorage.instance;
    storage.attachCloudApi(null);
    await storage.saveAll(const []);
  });

  tearDown(() {
    storage.attachCloudApi(null);
  });

  test('authenticated accounts read and write separate conversation stores', () async {
    final accountA = _FakeApiService()
      ..setAuthSession(token: 'token-a', user: {'id': 'account-a', 'email': 'a@example.com'});
    final accountB = _FakeApiService()
      ..setAuthSession(token: 'token-b', user: {'id': 'account-b', 'email': 'b@example.com'});

    storage.attachCloudApi(accountA);
    await storage.saveConversation(_thread('thread-a', 'private message A'));

    storage.attachCloudApi(accountB);
    expect(await storage.loadConversations(includeDeleted: true), isEmpty);
    await storage.saveConversation(_thread('thread-b', 'private message B'));

    storage.attachCloudApi(accountA);
    final aThreads = await storage.loadConversations(includeDeleted: true);
    expect(aThreads.map((thread) => thread.id), ['thread-a']);

    storage.attachCloudApi(accountB);
    final bThreads = await storage.loadConversations(includeDeleted: true);
    expect(bThreads.map((thread) => thread.id), ['thread-b']);
  });

  test('anonymous workspace and authenticated account use separate stores', () async {
    final anonymous = _FakeApiService()
      ..setUserId('u11111111111111111111111111111111');
    storage.attachCloudApi(anonymous);
    await storage.saveConversation(_thread('anonymous-thread', 'anonymous data'));

    final account = _FakeApiService()
      ..setAuthSession(token: 'token-a', user: {'id': 'account-a'});
    storage.attachCloudApi(account);
    expect(await storage.loadConversations(includeDeleted: true), isEmpty);

    storage.attachCloudApi(anonymous);
    expect(
      (await storage.loadConversations(includeDeleted: true)).map((t) => t.id),
      ['anonymous-thread'],
    );
  });

  test('legacy shared conversation key is not imported into an account store', () async {
    final legacy = _thread('legacy-thread', 'possibly another account data');
    SharedPreferences.setMockInitialValues({
      LocalConversationStorage.storageKey: jsonEncode([legacy.toJson()]),
    });

    final account = _FakeApiService()
      ..setAuthSession(token: 'token-a', user: {'id': 'account-a'});
    storage.attachCloudApi(account);

    expect(await storage.loadConversations(includeDeleted: true), isEmpty);
  });
}
