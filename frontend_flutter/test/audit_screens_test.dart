import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/core/design_system/fd_design_system.dart';
import 'package:freedata_ai/core/models/chat_models.dart';
import 'package:freedata_ai/core/utils/file_picker.dart';
import 'package:freedata_ai/main.dart';
import 'package:freedata_ai/screens/account_screen.dart';
import 'package:freedata_ai/screens/admin_screen.dart';
import 'package:freedata_ai/screens/chat_screen.dart';
import 'package:freedata_ai/screens/projects_screen.dart';
import 'package:freedata_ai/screens/settings_screen.dart';
import 'package:freedata_ai/screens/subscription_screen.dart';
import 'package:freedata_ai/screens/support_screen.dart';
import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/auth_token_storage.dart';
import 'package:freedata_ai/services/conversation_storage.dart';
import 'helpers/memory_auth_token_storage.dart';

class _AuditFakeApiService extends ApiService {
  String adminRole = 'read_only_analyst';
  List<String> adminPerms = const ['read_overview'];
  String? lastReviewedRequestId;
  String? lastReviewedDecision;
  Map<String, dynamic>? lastCreatedPayment;
  Map<String, dynamic>? lastCreatedTicket;

  @override
  Future<Map<String, dynamic>> getMetadata() async => {
        'products': [
          'Millet',
          'Sorghum (red)',
          'Sesame',
          'Groundnuts (shelled)'
        ],
        'provinces': ["N'Djamena", 'Lac', 'Salamat'],
      };

  @override
  Future<Map<String, dynamic>> getAdminMe(String adminToken) async => {
        'actor': adminRole == 'super_admin' ? 'omar' : 'amina',
        'role': adminRole,
        'permissions': adminPerms,
      };

  @override
  Future<Map<String, dynamic>> getAdminOverview(String adminToken,
          {bool liveProbe = false}) async =>
      {
        'api_health': {'status': 'ok', 'version': '1.2.0'},
        'api_metrics': {
          'total_requests': 42,
          'error_5xx': 0,
          'avg_latency_ms': 18
        },
        'users_summary': {'total_known_users': 3},
        'datasets': const [],
        'recent_audit_logs': const [],
        'model_flags': {'fast_free': true},
      };

  @override
  Future<List<Map<String, dynamic>>> getAdminUsers(String adminToken,
          {String search = ''}) async =>
      [
        {
          'user_id': 'user:u1',
          'plan_id': 'free',
          'status': 'active',
          'role': 'user'
        },
      ];

  @override
  Future<List<Map<String, dynamic>>> getAdminSupportTickets(
          String adminToken) async =>
      [
        {
          'ticket_id': 'TKT-1',
          'owner_id': 'user:u1',
          'category': 'technical_bug',
          'subject': 'Test ticket',
          'description': 'Description test',
          'status': 'open',
          'priority': 'normal',
        },
      ];

  @override
  Future<List<Map<String, dynamic>>> getAdminPaymentRequests(String adminToken,
          {String? status}) async =>
      [
        {
          'request_id': 'PAY-001',
          'user_id': 'user:u1',
          'plan_id': 'premium',
          'provider': 'airtel_money',
          'amount_xaf': 15000,
          'phone_or_ref': '+23566001122',
          'transaction_ref': 'AM-9988',
          'status': lastReviewedDecision ?? 'pending',
          'note': '',
        },
      ];

  @override
  Future<Map<String, dynamic>> reviewAdminPaymentRequest(
    String adminToken,
    String requestId, {
    required String decision,
    int periodDays = 30,
    String note = '',
  }) async {
    lastReviewedRequestId = requestId;
    lastReviewedDecision = decision;
    return {
      'request': {'request_id': requestId, 'status': decision}
    };
  }

  @override
  Future<Map<String, dynamic>> getMyBilling() async => {
        'subscription': {'effective_plan_id': 'free', 'status': 'active'},
        'quotas': {
          'daily_chat': {'used': 4, 'limit': 30},
          'monthly_pdf': {'used': 0, 'limit': 0},
        },
        'is_pro': false,
      };

  @override
  Future<Map<String, dynamic>> getBillingPlans() async => {
        'plans': [
          {
            'plan_id': 'free',
            'label': 'Gratuit',
            'daily_chat_limit': 30,
            'monthly_pdf_limit': 0,
            'daily_ml_limit': 5,
            'max_projects': 5,
          },
          {
            'plan_id': 'premium',
            'label': 'FreeData PRO',
            'price_xaf_month': 15000,
            'daily_chat_limit': 500,
            'monthly_pdf_limit': 50,
            'daily_ml_limit': 200,
            'max_projects': 100,
          },
        ],
      };

  @override
  Future<Map<String, dynamic>> getPaymentMethods() async => {
        'currency': 'XAF',
        'premium_price_xaf_month': 15000,
        'methods': [
          {
            'provider': 'airtel_money',
            'label': 'Airtel Money (Tchad)',
            'configured': true,
            'instructions':
                'Envoyez 15 000 XAF au +23566000000 puis renseignez la référence.',
          },
        ],
      };

  @override
  Future<List<Map<String, dynamic>>> listMyPaymentRequests() async => [
        {
          'request_id': 'PAY-OLD',
          'provider': 'airtel_money',
          'transaction_ref': 'AM-001',
          'amount_xaf': 15000,
          'status': 'pending',
          'created_at': '2026-11-19',
        },
      ];

  @override
  Future<Map<String, dynamic>> createPaymentRequest({
    required String provider,
    required String phoneOrRef,
    required String transactionRef,
    String planId = 'premium',
    int amountXaf = 0,
    String note = '',
  }) async {
    lastCreatedPayment = {
      'provider': provider,
      'phone_or_ref': phoneOrRef,
      'transaction_ref': transactionRef,
      'amount_xaf': amountXaf,
    };
    return {'request_id': 'PAY-NEW', 'status': 'pending'};
  }

  @override
  Future<List<Map<String, dynamic>>> listMyTickets() async => const [];

  @override
  Future<Map<String, dynamic>> createSupportTicket({
    required String category,
    required String subject,
    required String description,
    String priority = 'normal',
  }) async {
    lastCreatedTicket = {
      'category': category,
      'subject': subject,
      'description': description
    };
    return {'ticket_id': 'TKT-NEW', 'status': 'open'};
  }

  @override
  Future<List<Map<String, dynamic>>> listProjects(
          {bool includeArchived = false}) async =>
      [
        {
          'project_id': 'PRJ-1',
          'name': 'Négoce Sésame',
          'status': 'active',
          'studies_count': 0,
          'updated_at': '2026-11-19',
        },
      ];

  String? lastUpdatedDisplayName;
  String? lastSentChatMessage;
  final List<Map<String, dynamic>> uploadedDocs = [];

  @override
  Future<List<Map<String, dynamic>>> listUserDocuments(
          {String? projectId}) async =>
      List<Map<String, dynamic>>.from(uploadedDocs);

  @override
  Future<Map<String, dynamic>> uploadUserDocument({
    required String filename,
    required Uint8List bytes,
    String? mimeType,
    String? projectId,
    int chunkOffset = 0,
  }) async {
    final doc = {
      'doc_id': 'doc-${uploadedDocs.length + 1}',
      'project_id': projectId,
      'filename': filename,
      'mime_type': mimeType ?? 'application/octet-stream',
      'size_bytes': bytes.length,
      'chunks_count': 3,
      'embedding_provider': 'jina-embeddings-v3',
    };
    uploadedDocs.add(doc);
    return doc;
  }

  @override
  Future<void> deleteUserDocument(String docId) async {
    uploadedDocs.removeWhere((d) => d['doc_id'] == docId);
  }

  @override
  Future<Map<String, dynamic>> loginAccount({
    required String email,
    required String password,
  }) async {
    final user = {
      'user_id': ApiService.generateUserId(),
      'email': email,
      'display_name': 'Amina Tchad',
    };
    setAuthSession(token: 'jwt-test-token', user: user, isPro: false);
    return {'token': 'jwt-test-token', 'user': user};
  }

  @override
  Future<Map<String, dynamic>> updateProfile(
      {String? displayName, String? persona}) async {
    if (displayName != null) lastUpdatedDisplayName = displayName;
    final updated = {
      ...(authUser ?? const {}),
      if (displayName != null) 'display_name': displayName,
      if (persona != null) 'persona': persona,
    };
    setAuthSession(token: authToken, user: updated);
    return {'user': updated};
  }

  @override
  Future<List<Map<String, dynamic>>> syncCloudConversations(
    List<Map<String, dynamic>> conversations,
  ) async =>
      conversations;

  @override
  Future<void> upsertCloudConversation(
      Map<String, dynamic> conversation) async {}

  @override
  Future<Map<String, dynamic>> sendChatMessage(
    String message, {
    List<Map<String, String>> history = const [],
    String tier = 'free',
    Map<String, dynamic>? studyContext,
    String? projectId,
  }) async {
    lastSentChatMessage = message;
    return {
      'reply': 'Analyse mil à N’Djamena : 245 XAF/kg.',
      'intent': 'forecast',
      'sources': const []
    };
  }

  @override
  Stream<Map<String, dynamic>> streamChatMessage(
    String message, {
    List<Map<String, String>> history = const [],
    String tier = 'free',
    Map<String, dynamic>? studyContext,
    String? projectId,
  }) async* {
    lastSentChatMessage = message;
    yield {
      'event': 'done',
      'data': {
        'reply': 'Analyse mil à N’Djamena : 245 XAF/kg.',
        'intent': 'forecast',
        'sources': const [],
      },
    };
  }

  @override
  Future<Map<String, dynamic>> getProject(String projectId) async => {
        'project_id': projectId,
        'name': 'Négoce Sésame',
        'studies': const [],
      };
}

class _DelayedProjectsApiService extends _AuditFakeApiService {
  final firstProjectsResponse = Completer<List<Map<String, dynamic>>>();
  int projectRequests = 0;

  @override
  Future<List<Map<String, dynamic>>> listProjects(
      {bool includeArchived = false}) {
    projectRequests++;
    if (projectRequests == 1) return firstProjectsResponse.future;
    return super.listProjects(includeArchived: includeArchived);
  }
}

class _AccountBProjectsApiService extends _AuditFakeApiService {
  @override
  Future<List<Map<String, dynamic>>> listProjects(
      {bool includeArchived = false}) async =>
      [
        {
          'project_id': 'PRJ-B',
          'name': 'Projet compte B',
          'status': 'active',
          'studies_count': 0,
          'updated_at': '2026-11-24',
        },
      ];
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    AuthTokenStorage.setBackendForTesting(MemoryAuthTokenStorage());
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets(
      'AdminScreen enforces RBAC for read_only_analyst vs super_admin payments approval',
      (tester) async {
    final api = _AuditFakeApiService();
    await tester.pumpWidget(MaterialApp(home: AdminScreen(apiService: api)));
    await tester.pumpAndSettle();

    await tester.enterText(
        find.byType(TextField).first, 'analyst-token-1234567890');
    await tester.tap(find.text('Charger'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Connecté : amina · Rôle : read_only_analyst'),
        findsOneWidget);
    expect(find.text('Lecture seule'), findsOneWidget);
    expect(find.text('Rafraîchir données Gold'), findsNothing);
    expect(find.textContaining('Paiements ('), findsNothing);

    // Switch to super_admin with full permissions
    api.adminRole = 'super_admin';
    api.adminPerms = const [
      'read_overview',
      'manage_system',
      'manage_models',
      'manage_subscriptions',
      'manage_users'
    ];
    await tester.tap(find.text('Charger'));
    await tester.pumpAndSettle();

    expect(find.text('Lecture seule'), findsNothing);
    expect(find.text('Rafraîchir données Gold'), findsOneWidget);
    expect(find.text('Paiements (1)'), findsOneWidget);

    await tester.tap(find.text('Paiements (1)'));
    await tester.pumpAndSettle();
    expect(find.textContaining('AM-9988'), findsOneWidget);

    // The payment tab keeps its sections in the page-level ListView.
    // Scroll that viewport itself so the action is inside the 800x600 screen.
    await tester.drag(
      find.byType(ListView).first,
      const Offset(0, -420),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Approuver'));
    await tester.pumpAndSettle();
    expect(api.lastReviewedRequestId, 'PAY-001');
    expect(api.lastReviewedDecision, 'approved');
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'SubscriptionScreen renders French quotas and submits Mobile Money payment request',
      (tester) async {
    final api = _AuditFakeApiService()
      ..setAuthSession(
          token: 'test-bearer-token', user: const {'email': 'u@test.td'});
    await tester
        .pumpWidget(MaterialApp(home: SubscriptionScreen(apiService: api)));
    await tester.pumpAndSettle();

    expect(find.text('Messages IA / jour'), findsOneWidget);
    expect(find.text('4 / 30'), findsOneWidget);
    expect(find.text('Rapports PDF / mois'), findsOneWidget);

    final priceFinder =
        find.textContaining('Tarif mensuel PRO : 15 000 XAF / mois');
    await tester.scrollUntilVisible(priceFinder, 200,
        scrollable: find.byType(Scrollable).first);
    expect(priceFinder, findsOneWidget);

    final phoneField =
        find.widgetWithText(TextField, 'Numéro payeur ou référence compte');
    await tester.scrollUntilVisible(phoneField, 200,
        scrollable: find.byType(Scrollable).first);
    await tester.enterText(phoneField, '+23566112233');

    final txField =
        find.widgetWithText(TextField, 'Référence de transaction (SMS / reçu)');
    await tester.scrollUntilVisible(txField, 200,
        scrollable: find.byType(Scrollable).first);
    await tester.enterText(txField, 'AM-TX-7788');

    final submitBtn = find.text('Soumettre la preuve de paiement');
    await tester.scrollUntilVisible(submitBtn, 200,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(submitBtn);
    await tester.pumpAndSettle();

    expect(api.lastCreatedPayment?['provider'], 'airtel_money');
    expect(api.lastCreatedPayment?['transaction_ref'], 'AM-TX-7788');
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'SupportScreen gates guest access and submits ticket when signed in',
      (tester) async {
    final guestApi = _AuditFakeApiService();
    await tester
        .pumpWidget(MaterialApp(home: SupportScreen(apiService: guestApi)));
    await tester.pumpAndSettle();

    expect(find.text('Se connecter'), findsOneWidget);
    expect(find.text('Envoyer la demande'), findsNothing);

    final api = _AuditFakeApiService()
      ..setAuthSession(
          token: 'test-bearer-token', user: const {'email': 'u@test.td'});
    await tester.pumpWidget(MaterialApp(
        home: SupportScreen(key: const ValueKey('auth'), apiService: api)));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Envoyer la demande'));
    await tester.pumpAndSettle();
    expect(find.textContaining('min. 3 car.'), findsOneWidget);
    expect(api.lastCreatedTicket, isNull);

    await tester.enterText(
        find.widgetWithText(TextField, 'Sujet'), 'Erreur PDF');
    await tester.enterText(find.widgetWithText(TextField, 'Description'),
        'Le bouton PDF ne télécharge pas.');
    await tester.tap(find.text('Envoyer la demande'));
    await tester.pumpAndSettle();

    expect(api.lastCreatedTicket?['subject'], 'Erreur PDF');
    expect(tester.takeException(), isNull);
  });

  testWidgets('ProjectsScreen discards stale requests after account switch',
      (tester) async {
    final accountA = _DelayedProjectsApiService()
      ..setAuthSession(
        token: 'account-a-token',
        user: const {'email': 'a@example.td'},
      );
    final accountB = _AccountBProjectsApiService()
      ..setAuthSession(
        token: 'account-b-token',
        user: const {'email': 'b@example.td'},
      );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: ProjectsScreen(apiService: accountA)),
      ),
    );
    await tester.pump();

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: ProjectsScreen(apiService: accountB)),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Projet compte B'), findsOneWidget);

    accountA.firstProjectsResponse.complete([
      {
        'project_id': 'PRJ-A',
        'name': 'Projet compte A',
        'status': 'active',
        'studies_count': 0,
        'updated_at': '2026-11-23',
      },
    ]);
    await tester.pumpAndSettle();

    expect(find.text('Projet compte B'), findsOneWidget);
    expect(find.text('Projet compte A'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'ProjectsScreen loads dynamic products in PDF dialog without overflow',
      (tester) async {
    final api = _AuditFakeApiService()
      ..setAuthSession(
          token: 'test-bearer-token', user: const {'email': 'u@test.td'});
    await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: ProjectsScreen(apiService: api))));
    await tester.pumpAndSettle();

    expect(find.text('Négoce Sésame'), findsOneWidget);
    await tester.tap(find.text('Étude PDF'));
    await tester.pumpAndSettle();

    expect(find.text('Nouvelle étude PDF — Négoce Sésame'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'SettingsScreen displays account login/logout state and chat domains',
      (tester) async {
    final api = _AuditFakeApiService();
    await tester.pumpWidget(MaterialApp(
        home: SettingsScreen(
            key: const ValueKey('logged-out'), apiService: api)));
    await tester.pumpAndSettle();

    expect(find.text('Se connecter'), findsOneWidget);
    expect(find.text('Créer un compte'), findsOneWidget);
    expect(find.text('Domaine par défaut du chat'), findsOneWidget);

    api.setAuthSession(
      token: 'tok-abc',
      user: {
        'user_id': ApiService.generateUserId(),
        'email': 'kader@freedata.td',
        'display_name': 'Kader'
      },
      isPro: true,
    );
    await tester.pumpWidget(MaterialApp(
        home:
            SettingsScreen(key: const ValueKey('logged-in'), apiService: api)));
    await tester.pumpAndSettle();

    expect(find.textContaining('Kader · kader@freedata.td'), findsOneWidget);
    expect(find.text('ABONNEMENT PRO'), findsOneWidget);
    expect(find.text('Se déconnecter'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'MainShell lets guest browse freely, prompts AuthDialog on message send, and auto-sends after login',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 820);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    final api = _AuditFakeApiService();
    await tester.pumpWidget(MaterialApp(home: MainShell(apiService: api)));
    await tester.pumpAndSettle();

    // L'invité voit bien toute l'interface dès l'ouverture
    expect(find.text('Que souhaitez-vous analyser ?'), findsOneWidget);
    expect(find.text('Se connecter'), findsOneWidget);
    expect(find.text('S’inscrire'), findsOneWidget);

    // Dès qu'il écrit et envoie un message, le dialogue d'authentification s'ouvre
    await tester.enterText(find.byType(TextField), 'Quel est le prix du mil ?');
    await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
    await tester.pumpAndSettle();

    expect(find.text('Connexion à votre espace'), findsOneWidget);
    expect(
      find.textContaining('Connectez-vous ou créez un compte gratuit'),
      findsOneWidget,
    );
    expect(api.lastSentChatMessage, isNull);

    // S'il ferme le dialogue sans se connecter, son texte reste dans le champ
    await tester.tap(find.byTooltip('Fermer'));
    await tester.pumpAndSettle();
    expect(find.text('Connexion à votre espace'), findsNothing);
    expect(api.lastSentChatMessage, isNull);
    expect(
      tester.widget<TextField>(find.byType(TextField)).controller?.text,
      'Quel est le prix du mil ?',
    );

    // Il relance, se connecte -> le message part automatiquement et la sidebar affiche son profil !
    await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextField, 'Adresse e-mail'),
      'amina@freedata.td',
    );
    await tester.enterText(
      find.widgetWithText(TextField, 'Mot de passe'),
      'StrongPass123!',
    );
    await tester.tap(
      find.descendant(
        of: find.byType(Dialog),
        matching: find.byType(FDPrimaryButton),
      ),
    );
    await tester.pumpAndSettle();

    expect(api.isAuthenticated, isTrue);
    expect(api.lastSentChatMessage, 'Quel est le prix du mil ?');
    expect(
      find.text('Analyse mil à N’Djamena : 245 XAF/kg.'),
      findsOneWidget,
    );
    expect(find.text('Amina Tchad'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'AccountScreen renders profile initials, updates display name, and shows security/RGPD sections',
      (tester) async {
    final api = _AuditFakeApiService();
    api.setAuthSession(
      token: 'jwt-abc',
      user: {
        'user_id': ApiService.generateUserId(),
        'email': 'amina@freedata.td',
        'display_name': 'Amina',
      },
      isPro: false,
    );
    await LocalConversationStorage.instance.saveAll([
      ConversationThread(
        id: 'c-1',
        title: 'Mil Moundou',
        createdAt: DateTime.now(),
        updatedAt: DateTime.now(),
        messages: [ChatMessage.user('Mil Moundou ?')],
      ),
    ]);

    await tester.pumpWidget(MaterialApp(home: AccountScreen(apiService: api)));
    await tester.pumpAndSettle();

    expect(find.text('Amina'), findsWidgets);
    expect(find.text('amina@freedata.td'), findsWidgets);
    expect(find.text('PLAN GRATUIT'), findsOneWidget);

    final editNameBtn = find.byKey(const ValueKey('edit-name-btn'));
    await tester.scrollUntilVisible(editNameBtn, 200,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(editNameBtn);
    await tester.pumpAndSettle();

    final nameField =
        find.widgetWithText(TextField, 'Nom ou organisation affichée');
    await tester.enterText(nameField, 'Amina Agri-Tchad');
    await tester.tap(find.text('Enregistrer'));
    await tester.pumpAndSettle();

    expect(api.lastUpdatedDisplayName, 'Amina Agri-Tchad');

    final secFinder = find.text('Sécurité du compte');
    await tester.scrollUntilVisible(secFinder, 200,
        scrollable: find.byType(Scrollable).first);
    expect(secFinder, findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'ChatScreen uploads private PDF via attach button and renders Jina/Groq document chip',
      (tester) async {
    final api = _AuditFakeApiService();
    api.setAuthSession(
      token: 'jwt-doc-test',
      user: {
        'user_id': ApiService.generateUserId(),
        'email': 'amina@freedata.td',
        'display_name': 'Amina',
      },
      isPro: false,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ChatScreen(
            apiService: api,
            onConversationUpdated: () {},
            onRequireAuth: () async => true,
            onPickDocument: () async => PickedDocumentFile(
              name: 'rapport_salamat_2026.pdf',
              bytes: Uint8List.fromList(
                  'Contrat arachide Salamat 410 XAF'.codeUnits),
              mimeType: 'application/pdf',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final attachBtn = find.byIcon(Icons.attach_file_rounded);
    expect(attachBtn, findsOneWidget);
    await tester.tap(attachBtn);
    await tester.pumpAndSettle();

    expect(find.text('rapport_salamat_2026.pdf'), findsOneWidget);
    expect(api.uploadedDocs.length, 1);
    expect(api.uploadedDocs.first['embedding_provider'], 'jina-embeddings-v3');
    expect(tester.takeException(), isNull);
  });
}
