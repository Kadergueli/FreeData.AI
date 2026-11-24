import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/screens/subscription_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

class _FailingSubscriptionApi extends ApiService {
  @override
  Future<Map<String, dynamic>> getBillingPlans() async => {
        'plans': [
          {'id': 'free', 'name': 'Standard'},
          {'id': 'premium', 'name': 'PRO'},
        ],
      };

  @override
  Future<Map<String, dynamic>> getPaymentMethods() async =>
      throw Exception('payment catalog unavailable');

  @override
  Future<Map<String, dynamic>> getMyBilling() async =>
      throw Exception('billing profile unavailable');

  @override
  Future<List<Map<String, dynamic>>> listMyPaymentRequests() async =>
      throw Exception('payment requests unavailable');
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets(
      'subscription screen distinguishes failed sections from empty data',
      (tester) async {
    final api = _FailingSubscriptionApi()
      ..setAuthSession(
        token: 'test-token',
        user: const {'email': 'user@example.td'},
      );

    await tester.pumpWidget(
      MaterialApp(home: SubscriptionScreen(apiService: api)),
    );
    await tester.pumpAndSettle();

    expect(
        find.textContaining(
            'Impossible de charger votre abonnement et vos quotas'),
        findsOneWidget);
    expect(find.textContaining('Les moyens de paiement sont indisponibles'),
        findsOneWidget);
    expect(find.textContaining('Impossible de charger vos demandes'),
        findsOneWidget);
    expect(find.byTooltip('Réessayer'), findsNWidgets(3));
    expect(tester.takeException(), isNull);
  });
}
