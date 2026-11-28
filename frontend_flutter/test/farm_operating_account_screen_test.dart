import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/screens/farm_operating_account_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

class _FarmAccountFakeApi extends ApiService {
  int calls = 0;

  @override
  Future<Map<String, dynamic>> computeFarmOperatingAccount({
    required String province,
    required String cropId,
    required double areaHectares,
    double? targetYieldKgHa,
    double farmgateDiscountPct = 8.0,
    double seedCostPerHaXaf = 0,
    double fertilizerCostPerHaXaf = 0,
    double laborCostPerHaXaf = 0,
    double landPrepIrrigationPerHaXaf = 0,
    double harvestPostharvestPerHaXaf = 0,
    double otherOpexPerHaXaf = 0,
    double capexTotalXaf = 0,
    double loanAmountXaf = 0,
    double interestRatePct = 0,
  }) async {
    calls++;
    return <String, dynamic>{};
  }
}

void main() {
  testWidgets('farm account rejects NaN area before calling the API',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 1600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    final api = _FarmAccountFakeApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FarmOperatingAccountScreen(apiService: api),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextField, 'Superficie (ha)'),
      'NaN',
    );
    final calculate = find.text('Calculer le Compte d’Exploitation');
    await tester.scrollUntilVisible(
      calculate,
      160,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(calculate);
    await tester.pumpAndSettle();

    expect(find.textContaining('nombre fini'), findsOneWidget);
    expect(api.calls, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets('farm account rejects infinite CAPEX before calling the API',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 1600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    final api = _FarmAccountFakeApi();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: FarmOperatingAccountScreen(apiService: api),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextField, 'CAPEX initial total (FCFA)'),
      'Infinity',
    );
    final calculate = find.text('Calculer le Compte d’Exploitation');
    await tester.scrollUntilVisible(
      calculate,
      160,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(calculate);
    await tester.pumpAndSettle();

    expect(find.textContaining('nombre fini'), findsOneWidget);
    expect(api.calls, 0);
    expect(tester.takeException(), isNull);
  });
}
