import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/screens/market_pro_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

class _MarketRadarApi extends ApiService {
  @override
  Future<Map<String, dynamic>> getMarketProOverview({String? cropId}) async => {
        'validated_forecasts': const [],
        'arbitrage': const [],
        'watchlists': const [],
      };

  @override
  Future<Map<String, dynamic>> getSpatialArbitrage({
    required String cropId,
    double? transportCostXafKg,
    double? tonnage,
  }) async =>
      {
        'historical_mape_pct': 12.3,
        'routes': [
          {
            'origin_province': 'Salamat',
            'dest_province': "N'Djamena",
            'net_margin_xaf_kg': 45,
            'estimated_net_margin_xaf': 450000,
            'roi_pct': 18,
          },
        ],
      };

  @override
  Future<Map<String, dynamic>> getAgroCampaignRadar() async => {
        'summary': {
          'hubs_count': 1,
          'double_vulnerability_count': 1,
        },
        'hubs': [
          {
            'region': 'Moundou',
            'province': 'Logone Occidental',
            'root_anomaly_pct': 18.5,
            'critical_july_aug_years': 3,
            'dry_year_freq_pct': 25,
            'best_crop': {
              'label_fr': 'Sorgho rouge',
              'ca_per_ha_xaf': 420000,
            },
            'credit_risk_level': 'Élevé',
            'double_vulnerability': true,
          },
        ],
      };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('radar uses readable metric cards on narrow screens',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(
      MaterialApp(home: MarketProScreen(apiService: _MarketRadarApi())),
    );
    await tester.pumpAndSettle();

    final radarHub = find.text('Moundou');
    await tester.scrollUntilVisible(
      radarHub,
      240,
      scrollable: find.byType(Scrollable).first,
    );
    expect(radarHub, findsOneWidget);
    expect(find.text('Province : Logone Occidental'), findsOneWidget);
    expect(find.text('Anomalie Eau'), findsOneWidget);
    expect(find.text('18.5 %'), findsOneWidget);
    expect(find.text('Années sèches'), findsOneWidget);
    expect(find.text('3 (25 %)'), findsOneWidget);
    expect(find.text('Meilleure Culture'), findsOneWidget);
    expect(find.text('Sorgho rouge'), findsOneWidget);
    expect(find.text('CA / ha (ML t+1)'), findsOneWidget);
    expect(find.text('420000 F'), findsOneWidget);
    expect(find.text('Risque Crédit : Élevé'), findsOneWidget);
    expect(find.text('DOUBLE VULNÉRABILITÉ'), findsOneWidget);
    expect(find.byType(DataTable), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('radar retains the comparison table on wide screens',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(
      MaterialApp(home: MarketProScreen(apiService: _MarketRadarApi())),
    );
    await tester.pumpAndSettle();

    expect(find.byType(DataTable), findsOneWidget);
    expect(find.text('Pôle / Province'), findsOneWidget);
    expect(find.text('Anomalie Eau'), findsOneWidget);
    expect(find.text('Risque Crédit'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'arbitrage results can be explained or turned into a business plan by AI',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    String? capturedPrompt;
    await tester.pumpWidget(
      MaterialApp(
        home: MarketProScreen(
          apiService: _MarketRadarApi(),
          onAskAssistant: (prompt) => capturedPrompt = prompt,
        ),
      ),
    );
    await tester.pumpAndSettle();

    final simulate = find.text('Simuler marge & ROI');
    await tester.scrollUntilVisible(
      simulate,
      240,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(simulate);
    await tester.pumpAndSettle();

    final explain = find.text('Expliquer avec l’IA');
    await tester.scrollUntilVisible(
      explain,
      180,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(explain);
    expect(capturedPrompt, contains('Explique les résultats'));
    expect(capturedPrompt, contains('Salamat'));
    expect(capturedPrompt, contains('marge nette affichée'));

    final businessPlan = find.text('Créer un business plan');
    await tester.tap(businessPlan);
    expect(capturedPrompt, contains('business plan agricole professionnel'));
    expect(capturedPrompt,
        contains('demande-le avant de produire les projections'));
  });
}
