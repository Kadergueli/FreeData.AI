import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/screens/passport_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

class _PassportFakeApiService extends ApiService {
  @override
  Future<Map<String, dynamic>> getMetadata() async => {
        'passport_products': ['Millet', 'Rice (imported)'],
      };

  @override
  Future<List<dynamic>> getCreditPassports({
    String? province,
    String? commodity,
    int collateralValueXaf = 1000000,
  }) async =>
      [
        {
          'province': "N'Djamena",
          'commodity_std': commodity ?? 'Millet',
          'credit_score': 72,
          'grade': 'A',
          'ltv_ratio': 0.65,
          'recommended_max_loan_xaf': 650000,
          'cv_pct': 12.4,
          'max_drawdown_pct': 8.2,
          'obs_months': 24,
          'policy_recommendation': 'Stabilité relative des prix observés.',
        },
      ];
}

void main() {
  testWidgets(
    'PassportScreen explains market index is not borrower credit score',
    (tester) async {
      tester.view.physicalSize = const Size(1280, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(
        MaterialApp(
          home: PassportScreen(apiService: _PassportFakeApiService()),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Ce que mesure cet indicateur'), findsOneWidget);
      expect(
        find.textContaining('ne constitue pas une note de crédit'),
        findsOneWidget,
      );
      expect(find.text('Plafond indicatif'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'PassportScreen stacks filters without narrow-screen overflow',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });

      await tester.pumpWidget(
        MaterialApp(
            home: PassportScreen(apiService: _PassportFakeApiService())),
      );
      await tester.pumpAndSettle();

      expect(find.text('Produit'), findsOneWidget);
      expect(find.text('Valeur estimée du stock nanti'), findsOneWidget);
      expect(find.textContaining('province(s) évaluée(s)'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
