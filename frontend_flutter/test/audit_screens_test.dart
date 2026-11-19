import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/screens/admin_screen.dart';
import 'package:freedata_ai/screens/projects_screen.dart';
import 'package:freedata_ai/screens/settings_screen.dart';
import 'package:freedata_ai/screens/subscription_screen.dart';
import 'package:freedata_ai/screens/support_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

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
  Future<Map<String, dynamic>> getAdminOverview(String adminToken) async => {
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
            'label': 'Partenaire PRO',
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

  @override
  Future<Map<String, dynamic>> getProject(String projectId) async => {
        'project_id': projectId,
        'name': 'Négoce Sésame',
        'studies': const [],
      };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
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

    await tester.tap(find.text('Approuver'));
    await tester.pumpAndSettle();
    expect(api.lastReviewedRequestId, 'PAY-001');
    expect(api.lastReviewedDecision, 'approved');
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'SubscriptionScreen renders French quotas and submits Mobile Money payment request',
      (tester) async {
    final api = _AuditFakeApiService();
    await tester
        .pumpWidget(MaterialApp(home: SubscriptionScreen(apiService: api)));
    await tester.pumpAndSettle();

    expect(find.text('Messages IA / jour'), findsOneWidget);
    expect(find.text('4 / 30'), findsOneWidget);
    expect(find.text('Rapports PDF / mois'), findsOneWidget);
    expect(find.textContaining('Tarif mensuel PRO : 15 000 XAF / mois'),
        findsOneWidget);

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

  testWidgets('SupportScreen validates short fields and submits ticket cleanly',
      (tester) async {
    final api = _AuditFakeApiService();
    await tester.pumpWidget(MaterialApp(home: SupportScreen(apiService: api)));
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

  testWidgets(
      'ProjectsScreen loads dynamic products in PDF dialog without overflow',
      (tester) async {
    final api = _AuditFakeApiService();
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

    expect(find.textContaining('Connecté : kader@freedata.td (Kader)'),
        findsOneWidget);
    expect(find.text('Se déconnecter'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
