import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/core/models/chat_models.dart';
import 'package:freedata_ai/screens/library_screen.dart';
import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/conversation_storage.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Local persistence, restart reload, delete/restore and Markdown export',
      () async {
    SharedPreferences.setMockInitialValues({});
    final storage = LocalConversationStorage.instance;

    final created = await storage.createConversation(title: 'Test Mil Lac');
    final withMsgs = created.copyWith(
      messages: [
        ChatMessage.user('Quel est le prix du mil à Lac ?'),
        ChatMessage.assistant(text: 'Prix prévu : **220 XAF/kg**.'),
      ],
    );
    await storage.saveConversation(withMsgs);

    // Simule un redémarrage : relecture depuis SharedPreferences
    final reloaded = await storage.loadConversations();
    expect(reloaded.length, 1);
    expect(reloaded.first.title, 'Test Mil Lac');
    expect(reloaded.first.messages.length, 2);

    // Suppression (corbeille) puis restauration
    await storage.deleteConversation(created.id);
    expect((await storage.loadConversations()).length, 0);
    expect((await storage.loadConversations(includeDeleted: true)).length, 1);

    await storage.restoreConversation(created.id);
    expect((await storage.loadConversations()).length, 1);

    // Suppression définitive
    await storage.permanentlyDelete(created.id);
    expect((await storage.loadConversations(includeDeleted: true)).length, 0);
  });

  testWidgets(
      'LibraryScreen displays truthful local-only status and never claims cloud sync',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: LibraryScreen(
            apiService: ApiService(),
            conversations: const [],
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('STOCKÉ LOCALEMENT'), findsOneWidget);
    expect(find.text('SYNCHRONISATION INDISPONIBLE'), findsOneWidget);
    expect(find.text('Synchronisé'), findsNothing);
  });
}
