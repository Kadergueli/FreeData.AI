import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/core/models/chat_models.dart';
import 'package:freedata_ai/screens/explore_screen.dart';
import 'package:freedata_ai/screens/library_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

class FakeApiService extends ApiService {
  final Map<String, dynamic> metadata;

  FakeApiService({this.metadata = const {}});

  @override
  Future<Map<String, dynamic>> getMetadata() async => metadata;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('ExploreScreen exposes the real market metadata catalog', (tester) async {
    final metadata = {
      'active_domain': {
        'slug': 'markets_and_prices',
        'label': 'Marchés et prix des produits',
        'description': 'Catalogue exploitable des marchés et produits.',
      },
      'domains': [
        {'slug': 'markets_and_prices', 'label': 'Marchés et prix des produits', 'description': 'Opérationnel'},
        {'slug': 'agriculture', 'label': 'Agriculture', 'description': 'En préparation'},
      ],
      'products': ['Millet', 'Maïs'],
      'cereals': ['Millet'],
      'markets': ["N'Djamena", 'Moundou'],
      'provinces': ["N'Djamena", 'Logone Oriental'],
      'sources': ['Supabase'],
      'periods_covered': {'start': '2023-01', 'end': '2024-12'},
      'last_updated': '2024-12',
    };

    for (final size in [
      const Size(375, 812),
      const Size(430, 932),
      const Size(768, 1024),
      const Size(1024, 768),
      const Size(1440, 900),
      const Size(1920, 1080),
    ]) {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.physicalSize = const Size(800, 600);
        tester.view.devicePixelRatio = 1.0;
      });

      await tester.pumpWidget(
        MaterialApp(
          home: ExploreScreen(apiService: FakeApiService(metadata: metadata)),
        ),
      );

      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    }

    expect(find.text('Explorer les données'), findsOneWidget);
    expect(find.text('Marchés et prix des produits'), findsWidgets);
    expect(find.text('Millet'), findsNWidgets(2));
    expect(find.text("N'Djamena"), findsWidgets);
    expect(find.text('Supabase'), findsOneWidget);
    expect(find.text('Dates de mise à jour'), findsOneWidget);
  });

  testWidgets('LibraryScreen shows the empty state and future feature cards', (tester) async {
    for (final size in [
      const Size(375, 812),
      const Size(430, 932),
      const Size(768, 1024),
      const Size(1024, 768),
      const Size(1440, 900),
      const Size(1920, 1080),
    ]) {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.physicalSize = const Size(800, 600);
        tester.view.devicePixelRatio = 1.0;
      });

      await tester.pumpWidget(
        MaterialApp(
          home: LibraryScreen(apiService: ApiService()),
        ),
      );

      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    }

    expect(find.text('Bibliothèque'), findsOneWidget);
    expect(find.text('Aucune conversation enregistrée'), findsOneWidget);
    expect(find.text('Analyses'), findsOneWidget);
    expect(find.text('Synchronisation'), findsOneWidget);
  });

  testWidgets('LibraryScreen reads saved conversations from local storage', (tester) async {
    final conversation = ChatConversation(
      id: 'conv-1',
      title: 'Test conversation',
      createdAt: DateTime(2024, 1, 2),
      updatedAt: DateTime(2024, 1, 3),
      messages: [
        ChatMessage.user('Bonjour à tous'),
      ],
    );

    SharedPreferences.setMockInitialValues({
      'fd_ai_conversations_v1': jsonEncode([conversation.toJson()]),
    });

    await tester.pumpWidget(
      MaterialApp(
        home: LibraryScreen(apiService: ApiService()),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('Test conversation'), findsOneWidget);
    expect(find.text('Bonjour à tous'), findsOneWidget);
  });
}
