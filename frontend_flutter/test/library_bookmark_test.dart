import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:freedata_ai/screens/library_screen.dart';
import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/conversation_storage.dart';
import 'package:freedata_ai/core/models/chat_models.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('LibraryScreen displays saved conversations and handles dynamic updates', (tester) async {
    final conv1 = ConversationThread(
      id: 'conv-saved',
      title: 'Analyse Mil N\'Djamena',
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      isSavedInLibrary: true,
      messages: [
        ChatMessage.user('Prix du mil ?'),
        ChatMessage.assistant(text: 'Le prix du mil est en hausse de 12%.'),
      ],
    );

    final conv2 = ConversationThread(
      id: 'conv-normal',
      title: 'Question Sorgho',
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      isSavedInLibrary: false,
      messages: [
        ChatMessage.user('Question standard'),
      ],
    );

    SharedPreferences.setMockInitialValues({
      LocalConversationStorage.storageKey: jsonEncode([conv1.toJson(), conv2.toJson()]),
    });

    await tester.pumpWidget(
      MaterialApp(
        home: LibraryScreen(
          apiService: ApiService(),
          conversations: [conv1, conv2],
        ),
      ),
    );

    await tester.pumpAndSettle();

    // Verify both titles exist in default view
    expect(find.text('Analyse Mil N\'Djamena'), findsOneWidget);
    expect(find.text('Question Sorgho'), findsOneWidget);

    // Filter to Favoris only
    await tester.tap(find.text('Favoris (1)'));
    await tester.pumpAndSettle();

    expect(find.text('Analyse Mil N\'Djamena'), findsOneWidget);
    expect(find.text('Question Sorgho'), findsNothing);
  });
}

