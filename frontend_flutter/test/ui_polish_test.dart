import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/core/models/chat_models.dart';
import 'package:freedata_ai/core/utils/formatters.dart';
import 'package:freedata_ai/screens/chat_screen.dart';
import 'package:freedata_ai/screens/forecast_screen.dart';
import 'package:freedata_ai/screens/library_screen.dart';
import 'package:freedata_ai/screens/passport_screen.dart';
import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/conversation_storage.dart';
import 'package:freedata_ai/widgets/chat/assistant_message.dart';

class _PolishFakeApiService extends ApiService {
  @override
  Future<Map<String, dynamic>> getMetadata() async => {
        'provinces': ["N'Djamena", 'Salamat'],
        'commodities': ['Millet', 'Sorghum (red)'],
      };

  @override
  Future<List<dynamic>> getForecasts({String? province, String? commodity}) async => [
        {
          'market_name': "N'Djamena - Dembé",
          'source': 'WFP',
          'last_observed_month': '2025-02',
          'forecast_month': '2025-03',
          'last_observed_price': 1250,
          'forecast_t1': 1320,
          'ci_low_80': 232.57,
          'ci_high_80': 310.59,
        },
      ];

  @override
  Future<List<dynamic>> getCreditPassports({
    String? province,
    String? commodity,
    int loanAmount = 1000000,
  }) async =>
      [
        {
          'province': 'Salamat',
          'grade': 'B (Risque Modéré)',
          'credit_score': 64.5,
          'policy_recommendation': 'Éligible — Sous réserve de stockage warranté',
          'recommended_max_loan_xaf': 650000,
          'cv_pct': 21.7,
          'max_drawdown_pct': 33.1,
          'obs_months': 32,
        },
      ];
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('formatXaf and stripMarkdown format cleanly', () {
    expect(formatXaf(229), '229');
    expect(formatXaf(650000), '650 000');
    expect(formatXaf(1000000), '1 000 000');
    expect(formatXaf(232.57), '233');
    expect(formatXaf(310.59), '311');

    const raw =
        'ℹ️ Produit non précisé ou non reconnu : résultats affichés pour le **Millet** par défaut. Produits reconnus : Millet.\n\n'
        '### 🔮 Synthèse Nationale — Millet\n'
        '- **Provinces** : `229 XAF/kg`\n\n'
        '_Indicateur informatif_';
    final cleaned = stripMarkdown(raw);
    expect(cleaned.contains('ℹ️'), isFalse);
    expect(cleaned.contains('###'), isFalse);
    expect(cleaned.contains('**'), isFalse);
    expect(cleaned.contains('`'), isFalse);
    expect(cleaned.contains('_'), isFalse);
    expect(cleaned, contains('Synthèse Nationale — Millet'));
    expect(cleaned, contains('229 XAF/kg'));

    const tableMd =
        '### Prévisions — Mil à Moundou\n\n'
        '| Marché | Actuel → Prévu | Sac 100 kg |\n'
        '| :--- | :---: | ---: |\n'
        '| **Moundou** | 204 → **224** (+10.3%) | 22 445 XAF |\n\n'
        '---\n'
        '*Analyse de référence*';
    final cleanedTable = stripMarkdown(tableMd);
    expect(cleanedTable.contains('|'), isFalse);
    expect(cleanedTable.contains(':---'), isFalse);
    expect(cleanedTable.contains('---'), isFalse);
    expect(cleanedTable, contains('Moundou 204 → 224 (+10.3%) 22 445 XAF'));
  });

  test('LocalConversationStorage refuses empty conversations', () async {
    final emptyDraft = await LocalConversationStorage.instance.createConversation();
    await LocalConversationStorage.instance.saveConversation(emptyDraft);

    final loaded = await LocalConversationStorage.instance.loadConversations(includeDeleted: true);
    expect(loaded, isEmpty);

    // Legacy 0-message items already persisted in storage are filtered out too.
    SharedPreferences.setMockInitialValues({
      LocalConversationStorage.storageKey: jsonEncode([
        emptyDraft.toJson(),
        ConversationThread(
          id: 'non-empty',
          title: 'Mil N\'Djamena',
          createdAt: DateTime(2025, 1, 1),
          updatedAt: DateTime(2025, 1, 2),
          messages: [ChatMessage.user('Bonjour')],
        ).toJson(),
      ]),
    });

    final filtered = await LocalConversationStorage.instance.loadConversations(includeDeleted: true);
    expect(filtered.length, 1);
    expect(filtered.first.id, 'non-empty');
  });

  testWidgets('ChatScreen removes double border, redundant top bar, and boxes disclaimer', (tester) async {
    tester.view.physicalSize = const Size(375, 812);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ChatScreen(apiService: _PolishFakeApiService()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Sauvegarder'), findsNothing);
    expect(find.text('Nouvelle analyse'), findsNothing);

    final textField = tester.widget<TextField>(find.byType(TextField));
    final deco = textField.decoration!;
    expect(deco.filled, isFalse);
    expect(deco.border, InputBorder.none);
    expect(deco.enabledBorder, InputBorder.none);
    expect(deco.focusedBorder, InputBorder.none);
    expect(deco.disabledBorder, InputBorder.none);
    expect(tester.takeException(), isNull);

    // Verify full-width AssistantMessage with compact header and discreet disclaimer box
    const disclaimer =
        "Indicateur informatif fondé sur la volatilité des prix de marché. Il n'a pas été calibré sur des historiques de défaut de paiement et ne constitue ni une décision de crédit ni un conseil financier.";
    final msg = ChatMessage.assistant(
      text: '### Résultat\n\nPlafond : `650 000 XAF`\n\n_${disclaimer}_',
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: AssistantMessage(message: msg),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('FreeData.AI'), findsOneWidget);
    expect(find.text(disclaimer), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('LibraryScreen strips markdown and hides 0-message threads on mobile', (tester) async {
    tester.view.physicalSize = const Size(375, 812);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    final emptyThread = ConversationThread(
      id: 'empty-1',
      title: 'Conversation Vide',
      createdAt: DateTime(2025, 1, 1),
      updatedAt: DateTime(2025, 1, 1),
      messages: const [],
    );
    final validThread = ConversationThread(
      id: 'valid-1',
      title: 'Mil Salamat',
      createdAt: DateTime(2025, 1, 2),
      updatedAt: DateTime(2025, 1, 2),
      messages: [
        ChatMessage.user('Risque Mil Salamat ?'),
        ChatMessage.assistant(
          text:
              'ℹ️ Produit non précisé ou non reconnu : résultats affichés pour le **Millet** par défaut.\n\n### Synthèse\nPrix : `229 XAF/kg`',
        ),
      ],
    );

    SharedPreferences.setMockInitialValues({
      LocalConversationStorage.storageKey: jsonEncode([emptyThread.toJson(), validThread.toJson()]),
    });

    await tester.pumpWidget(
      MaterialApp(
        home: LibraryScreen(
          apiService: _PolishFakeApiService(),
          conversations: [emptyThread, validThread],
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Conversation Vide'), findsNothing);
    expect(find.text('Mil Salamat'), findsOneWidget);
    expect(find.text('Synthèse Prix : 229 XAF/kg'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('ForecastScreen compacts top bar and formats XAF & CI bounds cleanly', (tester) async {
    tester.view.physicalSize = const Size(375, 812);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ForecastScreen(apiService: _PolishFakeApiService()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Prévisions de marché'), findsNothing);
    expect(find.text('1 250 XAF/kg'), findsOneWidget);
    expect(find.text('1 320 XAF/kg'), findsOneWidget);
    expect(find.text('Intervalle indicatif 80 % : 233 – 311 XAF/kg'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('PassportScreen compacts filters, formats LTV, renders badges and disclaimer', (tester) async {
    tester.view.physicalSize = const Size(375, 812);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PassportScreen(apiService: _PolishFakeApiService()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Credit Passport'), findsNothing);
    expect(find.text('650 000 XAF'), findsOneWidget);
    expect(find.text('CV : 21.7%'), findsOneWidget);
    expect(find.text('Baisse max : -33.1%'), findsOneWidget);
    expect(find.text('32 mois'), findsOneWidget);
    expect(find.textContaining('Indicateur informatif fondé sur la volatilité'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('AssistantMessage renders structured Markdown tables and ChartCard cleanly on mobile and desktop',
      (tester) async {
    const structuredReply = '''
### Prévisions — Mil à Moundou (Logone Occidental)

**En bref :**
- **Moundou :** **204 XAF/kg** (2026-06) → **224 XAF/kg** prévus en 2026-07 (**+10.3%**, soit **22 445 XAF** / sac de 100 kg)

| Marché | Actuel → Prévu | Sac 100 kg |
| :--- | :---: | ---: |
| **Moundou** | 204 → **224** (+10.3%) | 22 445 XAF |
| Benoye | 190 → **214** (+12.7%) | 21 373 XAF |
| Krim Krim | 189 → **202** (+7.0%) | 20 219 XAF |
| Mbainamar | 165 → **182** (+10.8%) | 18 238 XAF |

**Repères statistiques (WFP) :**
- Fourchette probable à 80 % (Moundou) : **178 – 271 XAF/kg** *(IC 80%)*
- Erreur moyenne historique (MAE) : **36.0 XAF/kg** · Volatilité (CV) : **29.1%**
''';
    final msg = ChatMessage.assistant(
      text: structuredReply,
      metadata: {
        'chart': {
          'Moundou': 224,
          'Benoye': 214,
          'Krim Krim': 202,
          'Mbainamar': 182,
        },
      },
    );

    for (final size in [const Size(375, 812), const Size(1440, 900)]) {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.physicalSize = const Size(800, 600);
        tester.view.devicePixelRatio = 1.0;
      });

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: AssistantMessage(message: msg),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Aperçu comparatif'), findsOneWidget);
      expect(find.text('224'), findsOneWidget);
      expect(tester.takeException(), isNull);
    }
  });
}

