import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/core/models/chat_models.dart';
import 'package:freedata_ai/core/utils/formatters.dart';
import 'package:freedata_ai/main.dart';
import 'package:freedata_ai/screens/chat_screen.dart';
import 'package:freedata_ai/screens/explore_screen.dart';
import 'package:freedata_ai/screens/forecast_screen.dart';
import 'package:freedata_ai/screens/library_screen.dart';
import 'package:freedata_ai/screens/passport_screen.dart';
import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/conversation_storage.dart';
import 'package:freedata_ai/widgets/chat/assistant_message.dart';
import 'package:freedata_ai/widgets/chat/data_cards.dart';
import 'package:freedata_ai/widgets/chat/loading_indicator.dart';

class _PolishFakeApiService extends ApiService {
  @override
  Future<Map<String, dynamic>> getMetadata() async => {
        'provinces': ["N'Djamena", 'Salamat'],
        'products': ['Millet', 'Sorghum (red)'],
        'legacy_fields': {
          'commodities': ['Millet', 'Sorghum (red)'],
          'provinces': ["N'Djamena", 'Salamat'],
        },
      };

  @override
  Future<List<dynamic>> getForecasts(
          {String? province, String? commodity}) async =>
      [
        {
          'market_name': "N'Djamena - Dembé",
          'source': 'WFP',
          'last_observed_month': '2025-02',
          'forecast_month': '2025-03',
          'last_observed_price': 1250,
          'forecast_t1': 1320,
          'ci_low_80': 232.57,
          'ci_high_80': 310.59,
          'forecast_quality': 'standard',
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
          'policy_recommendation':
              'Éligible — Sous réserve de stockage warranté',
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

    const tableMd = '### Prévisions — Mil à Moundou\n\n'
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
    final emptyDraft =
        await LocalConversationStorage.instance.createConversation();
    await LocalConversationStorage.instance.saveConversation(emptyDraft);

    final loaded = await LocalConversationStorage.instance
        .loadConversations(includeDeleted: true);
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

    final filtered = await LocalConversationStorage.instance
        .loadConversations(includeDeleted: true);
    expect(filtered.length, 1);
    expect(filtered.first.id, 'non-empty');
  });

  testWidgets(
      'ChatScreen removes double border, redundant top bar, and boxes disclaimer',
      (tester) async {
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

  testWidgets(
      'LibraryScreen strips markdown and hides 0-message threads on mobile',
      (tester) async {
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
      LocalConversationStorage.storageKey:
          jsonEncode([emptyThread.toJson(), validThread.toJson()]),
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

  testWidgets(
      'ForecastScreen compacts top bar and formats XAF & CI bounds cleanly',
      (tester) async {
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
    expect(find.text('1 320 XAF/kg'), findsWidgets);
    expect(find.text('132 000 XAF'), findsWidgets);
    expect(find.text('Copier CSV'), findsOneWidget);
    await tester.tap(find.text('Détails'));
    await tester.pumpAndSettle();
    expect(find.text('Intervalle indicatif 80 % : 233 – 311 XAF/kg'),
        findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'PassportScreen compacts filters, formats LTV, renders badges and disclaimer',
      (tester) async {
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
    expect(find.text('650 000 XAF'), findsWidgets);
    expect(find.text('Copier CSV'), findsOneWidget);
    expect(find.text('CV : 21.7%'), findsOneWidget);
    expect(find.text('Baisse max : -33.1%'), findsOneWidget);
    expect(find.text('32 mois'), findsOneWidget);
    expect(find.textContaining('Indicateur informatif fondé sur la volatilité'),
        findsOneWidget);
    await tester.ensureVisible(find.text('Détails du calcul'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Détails du calcul'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Score marché : 65/100 calculé sur 32 mois'),
        findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'AssistantMessage renders structured Markdown tables and ChartCard cleanly on mobile and desktop',
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

  testWidgets(
      'ForecastScreen reads products, renders French commodity labels, and shows reduced confidence badge',
      (tester) async {
    final reducedApi = _ReducedForecastFakeApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ForecastScreen(apiService: reducedApi),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Mil (Millet)'), findsOneWidget);
    expect(find.text('Confiance réduite'), findsOneWidget);
    expect(reducedApi.requestedCommodity, 'Millet');
    expect(tester.takeException(), isNull);
  });

  test(
      'ApiService uses tier free by default, caches metadata, and retries only transient 5xx/network errors',
      () async {
    int metadataCalls = 0;
    int chat422Calls = 0;
    int chat400Calls = 0;
    int chat503Calls = 0;
    String? capturedTier;

    final mockClient = MockClient((request) async {
      if (request.url.path == '/api/v1/metadata') {
        metadataCalls++;
        return http.Response(
            jsonEncode({
              'products': ['Millet'],
              'provinces': ["N'Djamena"]
            }),
            200);
      }
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final msg = body['message'] as String;
      if (msg == 'free-check') {
        capturedTier = body['tier'] as String?;
        return http.Response(
            jsonEncode({'reply': 'OK', 'intent': 'forecast', 'sources': []}),
            200);
      }
      if (msg == 'err-422') {
        chat422Calls++;
        return http.Response('Unprocessable Entity', 422);
      }
      if (msg == 'err-400') {
        chat400Calls++;
        return http.Response('Bad Request', 400);
      }
      if (msg == 'err-503') {
        chat503Calls++;
        if (chat503Calls == 1) {
          return http.Response('Service Unavailable', 503);
        }
        return http.Response(
            jsonEncode(
                {'reply': 'Recovered', 'intent': 'forecast', 'sources': []}),
            200);
      }
      return http.Response('{}', 404);
    });

    final service = ApiService(client: mockClient);

    // 1. Default tier is 'free'
    final chatRes = await service.sendChatMessage('free-check');
    expect(capturedTier, 'free');
    expect(chatRes['reply'], 'OK');

    // 2. getMetadata() is cached across consecutive calls
    await service.getMetadata();
    await service.getMetadata();
    expect(metadataCalls, 1);

    // 3. No retry on 422 or 400
    await expectLater(
        service.sendChatMessage('err-422'), throwsA(isA<ApiHttpException>()));
    expect(chat422Calls, 1);
    await expectLater(
        service.sendChatMessage('err-400'), throwsA(isA<ApiHttpException>()));
    expect(chat400Calls, 1);

    // 4. Retries once on 503
    final recovered = await service.sendChatMessage('err-503');
    expect(chat503Calls, 2);
    expect(recovered['reply'], 'Recovered');
  });

  testWidgets(
      'Switching conversation during pending sendChatMessage does not overwrite active thread',
      (tester) async {
    final pendingResponse = Completer<Map<String, dynamic>>();
    final slowApi = _DelayedChatFakeApi(pendingResponse);

    final conv1 = ConversationThread(
      id: 'conv-1',
      title: 'Fil 1',
      createdAt: DateTime(2025, 1, 1),
      updatedAt: DateTime(2025, 1, 1),
      messages: [ChatMessage.user('Message initial 1')],
    );
    final conv2 = ConversationThread(
      id: 'conv-2',
      title: 'Fil 2',
      createdAt: DateTime(2025, 1, 2),
      updatedAt: DateTime(2025, 1, 2),
      messages: [ChatMessage.user('Message initial 2')],
    );
    await LocalConversationStorage.instance.saveAll([conv1, conv2]);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ChatScreen(
            apiService: slowApi,
            conversationId: 'conv-1',
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Envoyer un message dans conv-1 (la requête reste en attente)
    await tester.enterText(find.byType(TextField), 'Question lente sur le mil');
    await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
    await tester.pump();

    // Basculer sur conv-2 avant que la réponse n'arrive
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ChatScreen(
            apiService: slowApi,
            conversationId: 'conv-2',
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Message initial 2'), findsOneWidget);

    // Résoudre la réponse de conv-1
    pendingResponse.complete({
      'reply': 'Réponse tardive de conv-1',
      'intent': 'forecast',
      'sources': [],
    });
    await tester.pumpAndSettle();

    // conv-2 reste affichée sans être écrasée, et la réponse est bien persistée dans conv-1
    expect(find.text('Message initial 2'), findsOneWidget);
    expect(find.text('Réponse tardive de conv-1'), findsNothing);

    final savedConv1 =
        await LocalConversationStorage.instance.getConversation('conv-1');
    expect(savedConv1?.messages.last.text, 'Réponse tardive de conv-1');
  });

  test(
      'cleanMarkdownForClipboard preserves newlines and cleans Markdown tables and headers',
      () {
    const raw = '''
### Prévisions — Mil

| Marché | Prix |
| :--- | ---: |
| **Moundou** | `224 XAF` |

---
*Note finale*
''';
    final cleaned = cleanMarkdownForClipboard(raw);
    expect(cleaned, contains('Prévisions — Mil'));
    expect(cleaned, contains('Marché · Prix'));
    expect(cleaned, contains('Moundou · 224 XAF'));
    expect(cleaned, contains('\n'));
    expect(cleaned.contains('###'), isFalse);
    expect(cleaned.contains('**'), isFalse);
    expect(cleaned.contains('`'), isFalse);
    expect(cleaned.contains(':---'), isFalse);
    expect(cleaned.contains('---'), isFalse);
  });

  testWidgets(
      'Multi-message ChatScreen shows Sauvegarder dans Library only on the last assistant message',
      (tester) async {
    final conv = ConversationThread(
      id: 'conv-multi',
      title: 'Multi échanges',
      createdAt: DateTime(2025, 1, 1),
      updatedAt: DateTime(2025, 1, 1),
      messages: [
        ChatMessage.user('Question 1'),
        ChatMessage.assistant(text: 'Réponse 1'),
        ChatMessage.user('Question 2'),
        ChatMessage.assistant(text: 'Réponse 2'),
      ],
    );
    await LocalConversationStorage.instance.saveAll([conv]);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ChatScreen(
            apiService: _PolishFakeApiService(),
            conversationId: 'conv-multi',
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Réponse 1'), findsOneWidget);
    expect(find.text('Réponse 2'), findsOneWidget);
    expect(find.text('Sauvegarder dans Library'), findsOneWidget);
  });

  testWidgets(
      'ForecastScreen Alertes (>15%) chip loads and renders active alerts',
      (tester) async {
    final alertsApi = _ReducedForecastFakeApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ForecastScreen(apiService: alertsApi),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Alertes (>15%)'));
    await tester.pumpAndSettle();

    expect(find.text('1 alerte(s) active(s)'), findsOneWidget);
    expect(find.text('+28.4%'), findsOneWidget);
    expect(find.text('Am Timan (Salamat)'), findsOneWidget);
    expect(find.text('385 XAF/kg'), findsOneWidget);
    expect(find.text('300 XAF/kg'), findsOneWidget);
  });

  test(
      'ApiService.getSeasonalityStudy sends X-Premium-Key and handles 200 and 403',
      () async {
    String? sentHeader;
    int statusToReturn = 200;

    final mockClient = MockClient((request) async {
      sentHeader = request.headers['X-Premium-Key'];
      expect(request.url.path, '/api/v1/studies/seasonality');
      expect(request.url.queryParameters['commodity'], 'Millet');
      if (statusToReturn == 403) {
        return http.Response('Forbidden', 403);
      }
      return http.Response(
        jsonEncode({
          'status': 'ok',
          'commodity': 'Millet',
          'calendar': {
            'buy_months': [10, 11],
            'sell_months': [7, 8],
            'amplitude_pct': 34.0,
          },
        }),
        200,
      );
    });

    final service = ApiService(client: mockClient);
    service.setRuntimePremiumKey('secret-premium-key');

    final study = await service.getSeasonalityStudy(
        commodity: 'Millet', province: 'Salamat');
    expect(sentHeader, 'secret-premium-key');
    expect(study['status'], 'ok');
    expect(study['calendar']['amplitude_pct'], 34.0);

    statusToReturn = 403;
    await expectLater(
      service.getSeasonalityStudy(commodity: 'Millet'),
      throwsA(isA<ApiHttpException>()
          .having((e) => e.statusCode, 'statusCode', 403)),
    );
    expect(service.hasPremiumKey, isFalse);
  });

  test('ApiService.verifyPremiumKey validates via studies/seasonality cleanly',
      () async {
    const serverKey = 'FD-RENDER-SECRET-2026';

    final mockClient = MockClient((request) async {
      expect(request.url.path, '/api/v1/studies/seasonality');
      expect(request.url.queryParameters['commodity'], 'Millet');
      if (request.headers['X-Premium-Key'] == serverKey) {
        return http.Response(jsonEncode({'status': 'ok'}), 200);
      }
      return http.Response(
          jsonEncode({'detail': 'Clé premium invalide.'}), 403);
    });

    final service = ApiService(client: mockClient);
    expect(await service.verifyPremiumKey(''), isFalse);
    expect(await service.verifyPremiumKey('fausse-cle-123'), isFalse);
    expect(await service.verifyPremiumKey(serverKey), isTrue);
  });

  testWidgets(
      'MainShell rejects forged ?key= or forged localStorage and activates only server-verified key',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    // Tentative avec une clé inventée dans l'URL : refusée par le serveur
    final forgedUrlApi = _ReducedForecastFakeApi();
    await tester.pumpWidget(
      MaterialApp(
        home: MainShell(
          apiService: forgedUrlApi,
          initialUri:
              Uri.parse('https://freedata-ai.web.app/?key=fausse-cle-123'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Tchad · Marchés et Prix'), findsOneWidget);
    expect(find.text('FreeData PRO · Tchad'), findsNothing);
    expect(forgedUrlApi.hasPremiumKey, isFalse);
    final prefsAfterForged = await SharedPreferences.getInstance();
    expect(prefsAfterForged.getString('fd_ai_premium_key_v1'), isNull);

    // Tentative de falsification directe dans SharedPreferences / localStorage : nettoyée au démarrage
    await prefsAfterForged.setString(
        'fd_ai_premium_key_v1', 'fausse-cle-pirate');
    await tester.pumpWidget(const MaterialApp(home: SizedBox.shrink()));
    await tester.pumpAndSettle();
    final forgedStorageApi = _ReducedForecastFakeApi();
    await tester.pumpWidget(
      MaterialApp(home: MainShell(apiService: forgedStorageApi)),
    );
    await tester.pumpAndSettle();
    expect(find.text('Tchad · Marchés et Prix'), findsOneWidget);
    expect(forgedStorageApi.hasPremiumKey, isFalse);
    expect(prefsAfterForged.getString('fd_ai_premium_key_v1'), isNull);

    // Ouverture via lien avec la vraie clé définie sur Render
    await tester.pumpWidget(const MaterialApp(home: SizedBox.shrink()));
    await tester.pumpAndSettle();
    final validUrlApi = _ReducedForecastFakeApi();
    await tester.pumpWidget(
      MaterialApp(
        home: MainShell(
          apiService: validUrlApi,
          initialUri: Uri.parse(
              'https://freedata-ai.web.app/?key=FD-RENDER-SECRET-2026'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('FreeData PRO · Tchad'), findsOneWidget);
    expect(find.text('Abonnement PRO actif · Tchad'), findsOneWidget);
    expect(find.text('PRO'), findsOneWidget);
    expect(prefsAfterForged.getString('fd_ai_premium_key_v1'),
        'FD-RENDER-SECRET-2026');

    // Réouverture ultérieure sans ?key= dans l'URL : la clé vérifiée reste active définitivement
    await tester.pumpWidget(const MaterialApp(home: SizedBox.shrink()));
    await tester.pumpAndSettle();
    final persistedApi = _ReducedForecastFakeApi();
    await tester
        .pumpWidget(MaterialApp(home: MainShell(apiService: persistedApi)));
    await tester.pumpAndSettle();

    expect(find.text('FreeData PRO · Tchad'), findsOneWidget);
    expect(find.text('Abonnement PRO actif · Tchad'), findsOneWidget);
    expect(persistedApi.hasPremiumKey, isTrue);
  });

  testWidgets(
      'MainShell plan badge opens SubscriptionScreen cleanly without legacy Clé Pro popup',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    final shellApi = _ReducedForecastFakeApi();
    // Sans compte, le bouton 'Clé Pro' n'est plus affiché dans le pied de sidebar invité
    await tester.pumpWidget(MaterialApp(home: MainShell(apiService: shellApi)));
    await tester.pumpAndSettle();
    expect(find.text('Clé Pro'), findsNothing);

    // Une fois connecté, le badge ouvre directement l'écran unifié Abonnement & Activation PRO
    shellApi.setAuthSession(
      token: 'jwt-test-session',
      user: {
        'user_id': ApiService.generateUserId(),
        'email': 'partenaire@freedata.td',
        'display_name': 'Partenaire Tchad',
      },
      isPro: false,
    );
    await tester.pumpWidget(
      MaterialApp(
        home: MainShell(
          key: const ValueKey('authed-shell'),
          apiService: shellApi,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Tchad · Marchés et Prix'));
    await tester.pumpAndSettle();
    expect(find.text('Accès Partenaire & Clé Pro'), findsNothing);
    expect(find.textContaining('Abonnement'), findsWidgets);

    // ForecastScreen sans accès PRO : l'onglet Saisonnalité & Stockage est masqué
    final forecastApi = _ReducedForecastFakeApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: ForecastScreen(apiService: forecastApi)),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Saisonnalité & Stockage'), findsNothing);

    // La clé serveur est activée avant la création de l'écran : le rendu PRO
    // est ainsi testé indépendamment du cycle de vie de l'écran précédent.
    final unlockedForecastApi = _ReducedForecastFakeApi()
      ..setRuntimePremiumKey('FD-RENDER-SECRET-2026');
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ForecastScreen(
            key: const ValueKey('pro-forecast'),
            apiService: unlockedForecastApi,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Saisonnalité & Stockage'), findsOneWidget);

    await tester.tap(find.text('Saisonnalité & Stockage'));
    await tester.pumpAndSettle();
    expect(find.text('Sans frais (0%)'), findsOneWidget);
    expect(find.text('Stockage 1,5%/mois'), findsOneWidget);

    await tester.tap(find.text('Stockage 1,5%/mois'));
    await tester.pumpAndSettle();
    expect(unlockedForecastApi.requestedStorageCostPctMonth, 1.5);
    expect(
        find.textContaining(
            'Rendement net après frais de stockage (1.5 %/mois)'),
        findsOneWidget);
  });

  testWidgets(
      'ExploreScreen retries after failure and falls back to forecasts when metadata fails',
      (tester) async {
    final fallbackApi = _ExploreRetryFallbackApi();

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: ExploreScreen(apiService: fallbackApi)),
      ),
    );
    await tester.pumpAndSettle();

    // Premier essai : metadata + forecasts échouent -> message d'erreur + bouton Réessayer visible
    expect(find.text('Les métadonnées ne sont pas accessibles pour le moment.'),
        findsOneWidget);
    expect(find.text('Réessayer'), findsOneWidget);

    // Second essai via Réessayer : metadata échoue encore, mais getForecasts() réussit en repli
    fallbackApi.allowForecastsFallback = true;
    await tester.tap(find.text('Réessayer'));
    await tester.pumpAndSettle();

    expect(find.text('Les métadonnées ne sont pas accessibles pour le moment.'),
        findsNothing);
    expect(find.text('Mil (Millet)'), findsWidgets);
    expect(find.text('Am Timan'), findsOneWidget);
  });

  testWidgets(
      'ChartCard handles negative and zero values cleanly and ChatScreen enforces 4000 chars',
      (tester) async {
    expect(ApiService.baseUrl, 'https://freedata-ai.onrender.com');

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: ChartCard(
            data: {'Hausse': 12.0, 'Baisse': -8.5, 'Stable': 0.0},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('Aperçu comparatif'), findsOneWidget);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ChatScreen(apiService: _PolishFakeApiService()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final overLimit = 'a' * 4100;
    await tester.enterText(find.byType(TextField), overLimit);
    await tester.pump();
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller!.text.length, 4000);
  });

  testWidgets(
      'Delete conversation SnackBar auto-dismisses even with accessibleNavigation enabled',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    final conv = ConversationThread(
      id: 'conv-del-1',
      title: 'Mil Salamat',
      createdAt: DateTime(2025, 1, 1),
      updatedAt: DateTime(2025, 1, 2),
      messages: [ChatMessage.user('Bonjour')],
    );
    await LocalConversationStorage.instance.saveAll([conv]);

    await tester.pumpWidget(
      MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(accessibleNavigation: true),
          child: child!,
        ),
        home: MainShell(apiService: _ReducedForecastFakeApi()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Options'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Supprimer'));
    await tester.pumpAndSettle();

    expect(find.text('Conversation mise à la corbeille'), findsOneWidget);
    expect(find.byType(SnackBarAction), findsNothing);

    await tester.pump(const Duration(seconds: 3, milliseconds: 100));
    await tester.pumpAndSettle();
    expect(find.text('Conversation mise à la corbeille'), findsNothing);
  });

  test(
      'ApiService.verifyPremiumKey surfaces 503 PREMIUM_API_KEYS diagnostic without retry delay',
      () async {
    int calls = 0;
    final mockClient = MockClient((request) async {
      calls++;
      return http.Response(
        jsonEncode({
          'detail':
              'Études avancées désactivées : PREMIUM_API_KEYS non configuré.'
        }),
        503,
      );
    });

    final service = ApiService(client: mockClient);
    await expectLater(
      service.verifyPremiumKey('ma-cle'),
      throwsA(
        isA<ApiHttpException>()
            .having((e) => e.statusCode, 'statusCode', 503)
            .having((e) => e.message, 'message', contains('PREMIUM_API_KEYS')),
      ),
    );
    expect(calls, 1);
  });

  testWidgets(
      'First message keeps LoadingIndicator active while MainShell updates conversationId',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    final pending = Completer<Map<String, dynamic>>();
    final delayedApi = _DelayedChatFakeApi(pending);

    await tester.pumpWidget(MaterialApp(
        home: MainShell(apiService: delayedApi, requireAuthOnChat: false)));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'Premier message test');
    await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    // Même après que MainShell ait attribué un ID au nouveau fil, le spinner reste affiché
    expect(find.byType(LoadingIndicator), findsOneWidget);

    pending.complete(
        {'reply': 'Réponse du serveur', 'intent': 'forecast', 'sources': []});
    await tester.pumpAndSettle();

    expect(find.byType(LoadingIndicator), findsNothing);
    expect(find.text('Réponse du serveur'), findsOneWidget);
  });

  testWidgets(
      'Deleting active conversation from Library resets Assistant IA welcome state',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    final conv = ConversationThread(
      id: 'conv-lib-del',
      title: 'Fil Library',
      createdAt: DateTime(2025, 1, 1),
      updatedAt: DateTime(2025, 1, 2),
      messages: [
        ChatMessage.user('Question unique'),
        ChatMessage.assistant(text: 'Réponse associée'),
      ],
    );
    await LocalConversationStorage.instance.saveAll([conv]);

    await tester.pumpWidget(
        MaterialApp(home: MainShell(apiService: _ReducedForecastFakeApi())));
    await tester.pumpAndSettle();
    expect(find.text('Question unique'), findsOneWidget);

    // Aller dans Library et supprimer la conversation active
    await tester.tap(find.text('Bibliothèque'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Mettre à la corbeille'));
    await tester.pumpAndSettle();

    // Revenir dans Assistant IA : la conversation supprimée n'est plus affichée
    await tester.tap(find.text('Assistant IA'));
    await tester.pumpAndSettle();
    expect(find.text('Question unique'), findsNothing);
    expect(find.text('Que souhaitez-vous analyser ?'), findsOneWidget);
  });

  testWidgets(
      'ExploreScreen translates all Render products, shows forecast horizon, and expands/collapses markets',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    final fullMetaApi = _FullCatalogFakeApi();
    String? capturedPrompt;

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ExploreScreen(
            apiService: fullMetaApi,
            onSelectPrompt: (p) => capturedPrompt = p,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Produits traduits (les 5 manquants précédemment)
    expect(find.text('Manioc (cossettes)'), findsOneWidget);
    expect(find.text('Niébé rouge'), findsOneWidget);
    expect(find.text('Niébé blanc'), findsOneWidget);
    expect(find.text('Oignon'), findsOneWidget);
    expect(find.text('Pâtes alimentaires (mélange)'), findsOneWidget);
    expect(find.text('Cassava Chips'), findsNothing);

    // Horizon prévisionnel déduit automatiquement de 2026-10 -> 2026-11
    expect(find.text('Horizon prévisionnel : 2026-11'), findsOneWidget);

    // Par défaut, seuls les 10 premiers marchés sont affichés (pas de mur de pilules)
    expect(find.text('Abeche'), findsOneWidget);
    expect(find.text('Sarh'), findsNothing);
    final expandMarkets = find.text('+14 autres · Voir tout');
    expect(expandMarkets, findsOneWidget);

    // Déplier les 24 marchés, cliquer sur Sarh, puis replier
    await tester.ensureVisible(expandMarkets);
    await tester.tap(expandMarkets);
    await tester.pumpAndSettle();

    expect(find.text('Moundou'), findsOneWidget);
    expect(find.text("N'Djamena, Dembe"), findsOneWidget);
    expect(find.text('Sarh'), findsOneWidget);

    await tester.ensureVisible(find.text('Sarh'));
    await tester.tap(find.text('Sarh'));
    await tester.pump();
    expect(
      capturedPrompt,
      'Quelle est la situation des prix et la prévision sur le marché de Sarh ?',
    );

    final collapse = find.text('Réduire');
    expect(collapse, findsWidgets);
    await tester.ensureVisible(collapse.last);
    await tester.tap(collapse.last);
    await tester.pumpAndSettle();
    expect(find.text('Sarh'), findsNothing);
  });

  testWidgets(
      'New conversation buttons in sidebar and mobile AppBar start a fresh chat even when history exists',
      (tester) async {
    final existing = ConversationThread(
      id: 'conv-existing',
      title: 'Analyse Mil Moundou',
      createdAt: DateTime(2025, 1, 1),
      updatedAt: DateTime(2025, 1, 2),
      messages: [
        ChatMessage.user('Prix du mil à Moundou ?'),
        ChatMessage.assistant(text: 'Réponse historique Moundou.'),
      ],
    );
    await LocalConversationStorage.instance.saveAll([existing]);

    // 1. Desktop : bouton "Nouvelle conversation" dans la barre latérale
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    await tester.pumpWidget(
        MaterialApp(home: MainShell(apiService: _ReducedForecastFakeApi())));
    await tester.pumpAndSettle();

    expect(find.text('Prix du mil à Moundou ?'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'Brouillon en cours');

    await tester.tap(find.text('Nouvelle conversation').first);
    await tester.pumpAndSettle();

    expect(find.text('Prix du mil à Moundou ?'), findsNothing);
    expect(find.text('Que souhaitez-vous analyser ?'), findsOneWidget);
    expect(find.text('Analyse Mil Moundou'), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField)).controller?.text,
        isEmpty);

    // 2. Mobile : bouton icône en haut à droite (AppBar actions)
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;

    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    await tester.pumpWidget(
        MaterialApp(home: MainShell(apiService: _ReducedForecastFakeApi())));
    await tester.pumpAndSettle();

    expect(find.text('Prix du mil à Moundou ?'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.edit_square));
    await tester.pumpAndSettle();

    expect(find.text('Prix du mil à Moundou ?'), findsNothing);
    expect(find.text('Que souhaitez-vous analyser ?'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'PassportScreen prioritizes passport_products from metadata when provided',
      (tester) async {
    final fullPassportApi = _FullCatalogFakeApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PassportScreen(apiService: fullPassportApi),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Ouvre le menu déroulant Produit pour vérifier la présence d'un produit exclusif Credit Passport
    await tester.tap(find.text('Mil (Millet)'));
    await tester.pumpAndSettle();

    expect(find.text('Dattes'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'Premium B2B features: TrackRecord banner, Anomalies & Qualité tab, and Chat Pro quick actions',
      (tester) async {
    final proApi = _ReducedForecastFakeApi();

    // 1. En mode standard, les actions rapides Pro ne sont pas affichées
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: ChatScreen(apiService: proApi))));
    await tester.pumpAndSettle();
    expect(find.text('Saisonnalité & Stockage · Mil'), findsNothing);

    // 2. En mode Partenaire / Pro, l'action rapide B2B « Saisonnalité & Stockage » apparaît
    proApi.setRuntimePremiumKey(_ReducedForecastFakeApi._expectedRenderKey);
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: ChatScreen(apiService: proApi))));
    await tester.pumpAndSettle();
    expect(find.text('Saisonnalité & Stockage · Mil'), findsOneWidget);
    // L'action « Radar Anomalies & Qualité » a été retirée du chat (disponible dans l'onglet Prévisions).
    expect(find.text('Radar Anomalies & Qualité'), findsNothing);

    // 3. ForecastScreen en mode Pro : bandeau Track Record + onglet Anomalies & Qualité
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: ForecastScreen(apiService: proApi))));
    await tester.pumpAndSettle();

    expect(
        find.textContaining(
            'Fiabilité vérifiée (12 mois · Mil (Millet)) : +18 %'),
        findsOneWidget);
    expect(find.text('Anomalies & Qualité'), findsOneWidget);

    await tester.ensureVisible(find.text('Anomalies & Qualité'));
    await tester.tap(find.text('Anomalies & Qualité'));
    await tester.pumpAndSettle();

    expect(find.text('Écart inter-marchés'), findsOneWidget);
    expect(find.text('Collecte arrêtée'), findsOneWidget);
    expect(find.textContaining('piste potentielle d’approvisionnement B2B'),
        findsOneWidget);

    // Filtre Qualité relevés
    await tester
        .ensureVisible(find.widgetWithText(ChoiceChip, 'Qualité relevés'));
    await tester.tap(find.widgetWithText(ChoiceChip, 'Qualité relevés'));
    await tester.pumpAndSettle();
    expect(find.text('Collecte arrêtée'), findsOneWidget);
    expect(find.text('Écart inter-marchés'), findsNothing);

    // Onglet Saisonnalité & Stockage complet (fiabilité, durée typique, p10/p90, profil 12 mois, provinces)
    await tester.ensureVisible(find.text('Saisonnalité & Stockage'));
    await tester.tap(find.text('Saisonnalité & Stockage'));
    await tester.pumpAndSettle();

    expect(find.text('FIABLE'), findsOneWidget);
    expect(find.text('~9 mois'), findsOneWidget);
    expect(find.textContaining('10 % pires cas (+2 %)'), findsOneWidget);
    expect(find.text('Profil saisonnier sur 12 mois'), findsOneWidget);
    expect(find.text('Comparaison des provinces'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'Clicking a product in Explore opens and displays the prompt and reply in a new active chat',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    final existing = ConversationThread(
      id: 'conv-prev',
      title: 'Ancienne discussion',
      createdAt: DateTime(2025, 1, 1),
      updatedAt: DateTime(2025, 1, 2),
      messages: [
        ChatMessage.user('Question précédente'),
        ChatMessage.assistant(text: 'Réponse précédente'),
      ],
    );
    await LocalConversationStorage.instance.saveAll([existing]);

    final mockClient = MockClient((request) async {
      if (request.url.path == '/api/v1/metadata') {
        return http.Response(
          jsonEncode({
            'products': ['Millet'],
            'cereals': ['Millet'],
            'markets': ['Abeche'],
            'provinces': ['Salamat'],
            'sources': ['FEWS NET'],
            'periods_covered': {'start': '2026-07', 'end': '2026-10'},
          }),
          200,
        );
      }
      if (request.url.path == '/api/v1/chat') {
        return http.Response.bytes(
          utf8.encode(jsonEncode({
            'reply': 'Analyse Mil générée depuis Explore.',
            'intent': 'forecast',
            'sources': [],
          })),
          200,
        );
      }
      return http.Response('{}', 404);
    });

    await tester.pumpWidget(MaterialApp(
        home: MainShell(
            apiService: ApiService(client: mockClient),
            requireAuthOnChat: false)));
    await tester.pumpAndSettle();
    expect(find.text('Question précédente'), findsOneWidget);

    await tester.tap(find.text('Explorer'));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.text('Mil (Millet)').first);
    await tester.tap(find.text('Mil (Millet)').first);
    await tester.pumpAndSettle();

    // L'utilisateur voit directement la question et la réponse sur l'écran actif (pas un écran vide)
    expect(find.text('Que souhaitez-vous analyser ?'), findsNothing);
    expect(
      find.text(
          'Quelle est la prévision du prix et la tendance pour le produit Mil (Millet) au Tchad ?'),
      findsOneWidget,
    );
    expect(find.text('Analyse Mil générée depuis Explore.'), findsOneWidget);
    // L'ancienne discussion reste intacte dans l'historique
    expect(find.text('Ancienne discussion'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

class _FullCatalogFakeApi extends ApiService {
  @override
  Future<List<dynamic>> getCreditPassports({
    String? province,
    String? commodity,
    int loanAmount = 1000000,
  }) async =>
      const [];

  @override
  Future<Map<String, dynamic>> getMetadata() async => {
        'passport_products': [
          'Cassava Chips',
          'Dates',
          'Millet',
          'Rice (local)',
        ],
        'products': [
          'Cassava Chips',
          'Cowpeas (Red)',
          'Cowpeas (White)',
          'Groundnut Oil (Refined)',
          'Groundnuts (shelled)',
          'Maize (white)',
          'Millet',
          'Onions',
          'Pasta (Mixed)',
          'Refined sugar',
          'Rice (Milled)',
          'Rice (imported)',
          'Sesame (White)',
          'Sorghum (red)',
          'Sweet potatoes',
          'Wheat flour',
        ],
        'cereals': [
          'Maize (white)',
          'Millet',
          'Rice (Milled)',
          'Rice (imported)',
          'Sorghum (red)',
          'Wheat flour',
        ],
        'markets': [
          'Abeche',
          'Adre',
          'Amtiman',
          'Ati',
          'Bagasola',
          'Biltine',
          'Bodo',
          'Bol',
          'Bongor',
          'Bousso',
          'Faya',
          'Gozbeida',
          'Kelo',
          'Mao',
          'Massakory',
          'Mongo',
          'Moundou',
          'Moussoro',
          "N'Djamena, Atrone",
          "N'Djamena, Dembe",
          "N'Djamena, Mil",
          'Pala',
          'Peni',
          'Sarh',
        ],
        'provinces': ["N'Djamena", 'Salamat'],
        'sources': ['FEWS NET'],
        'periods_covered': {'start': '2026-07', 'end': '2026-10'},
        'last_updated': '2026-10',
      };
}

class _ExploreRetryFallbackApi extends ApiService {
  bool allowForecastsFallback = false;

  @override
  Future<Map<String, dynamic>> getMetadata() async {
    throw const ApiHttpException(503, 'Indisponible');
  }

  @override
  Future<List<dynamic>> getForecasts(
      {String? province, String? commodity}) async {
    if (!allowForecastsFallback) {
      throw const ApiHttpException(503, 'Indisponible');
    }
    return [
      {
        'commodity_std': 'Millet',
        'market_name': 'Am Timan',
        'province': 'Salamat',
        'source': 'WFP',
        'last_observed_month': '2025-02',
        'forecast_month': '2025-03',
      },
    ];
  }
}

class _ReducedForecastFakeApi extends ApiService {
  static const String _expectedRenderKey = 'FD-RENDER-SECRET-2026';
  String? requestedCommodity;
  double? requestedStorageCostPctMonth;

  @override
  Future<bool> verifyPremiumKey(String candidateKey) async =>
      candidateKey.trim() == _expectedRenderKey;

  @override
  Future<Map<String, dynamic>> getMetadata() async => {
        'provinces': ['Salamat'],
        'products': ['Millet', 'Sorghum (red)'],
        'track_records': {
          'Millet': {
            'commodity': 'Millet',
            'verdict': 'better',
            'vs_naive_pct': 18.4,
            'months': 12,
          },
        },
      };

  @override
  Future<List<dynamic>> getAnomalies({
    String? province,
    String? commodity,
    String? kind,
    String? severity,
    int limit = 100,
  }) async =>
      [
        {
          'source': 'WFP',
          'province': 'Salamat',
          'market_name': 'Am Timan',
          'commodity_std': 'Millet',
          'kind': 'divergence',
          'severity': 'forte',
          'month': '2026-10',
          'value': 210,
          'reference': 275,
          'change_pct': -23.6,
          'score': -4.2,
        },
        {
          'source': 'WFP',
          'province': 'Salamat',
          'market_name': 'Haraze',
          'commodity_std': 'Millet',
          'kind': 'stopped',
          'severity': 'modérée',
          'month': '2026-06',
          'value': 240,
          'reference': 240,
          'change_pct': 0.0,
          'score': 4.0,
        },
      ];

  @override
  Future<List<dynamic>> getForecasts(
      {String? province, String? commodity}) async {
    requestedCommodity = commodity;
    return [
      {
        'market_name': 'Am Timan',
        'source': 'WFP',
        'last_observed_month': '2025-02',
        'forecast_month': '2025-03',
        'last_observed_price': 300,
        'forecast_t1': 330,
        'forecast_quality': 'reduced',
      },
    ];
  }

  @override
  Future<List<dynamic>> getAlerts({
    double thresholdPct = 15.0,
    String? province,
    String? commodity,
  }) async =>
      [
        {
          'month': '2025-02',
          'source': 'WFP',
          'province': 'Salamat',
          'market_name': 'Am Timan',
          'commodity_std': 'Millet',
          'value': 385,
          'predicted_price': 300,
          'deviation_pct': 28.4,
        },
      ];

  @override
  Future<Map<String, dynamic>> getSeasonalityStudy({
    required String commodity,
    String? province,
    double? storageCostPctMonth,
  }) async {
    requestedStorageCostPctMonth = storageCostPctMonth;
    return {
      'status': 'ok',
      'commodity': commodity,
      'scope_province': province ?? 'Toutes provinces suivies',
      'calendar': {
        'buy_months': [10, 11],
        'sell_months': [7, 8],
        'amplitude_pct': 34.0,
        'buy_discount_pct': -14.0,
        'sell_premium_pct': 18.0,
        'reliable': true,
        'min_years_observed': 4,
      },
      'profile': [
        {
          'month': 10,
          'label': 'Octobre',
          'index': 0.86,
          'pct_vs_avg': -14.0,
          'consistency': 0.85,
          'n': 12
        },
        {
          'month': 7,
          'label': 'Juillet',
          'index': 1.18,
          'pct_vs_avg': 18.0,
          'consistency': 0.90,
          'n': 12
        },
      ],
      'provinces': [
        {
          'province': 'Salamat',
          'buy_months': [10, 11],
          'sell_months': [7, 8],
          'buy_discount_pct': -14.0,
          'sell_premium_pct': 18.0,
          'amplitude_pct': 34.0,
          'reliable': true,
        },
      ],
      'storage_strategy': {
        'status': 'ok',
        'hit_rate_pct': 83.0,
        'median_return_pct': 26.5,
        'p10_return_pct': 2.0,
        'p90_return_pct': 45.0,
        'typical_gap_months': 9,
        'n_years': 4,
        'n_cycles': 6,
        if (storageCostPctMonth != null) ...{
          'storage_cost_pct_month': storageCostPctMonth,
          'net_hit_rate_pct': 83.0,
          'net_median_return_pct': 14.5,
        },
      },
      'caveats': [
        'Données historiques multi-marchés.',
      ],
    };
  }
}

class _DelayedChatFakeApi extends ApiService {
  final Completer<Map<String, dynamic>> completer;

  _DelayedChatFakeApi(this.completer);

  @override
  Future<Map<String, dynamic>> getMetadata() async => {};

  @override
  Future<Map<String, dynamic>> sendChatMessage(
    String message, {
    List<Map<String, String>> history = const [],
    String tier = 'free',
    Map<String, dynamic>? studyContext,
    String? projectId,
  }) =>
      completer.future;

  @override
  Stream<Map<String, dynamic>> streamChatMessage(
    String message, {
    List<Map<String, String>> history = const [],
    String tier = 'free',
    Map<String, dynamic>? studyContext,
    String? projectId,
  }) async* {
    yield {'event': 'done', 'data': await completer.future};
  }
}
