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

    expect(find.text('Moundou'), findsOneWidget);
    expect(find.text('Province : Logone Occidental'), findsOneWidget);
    expect(find.text('Anomalie Eau'), findsOneWidget);
    expect(find.text('18.5 %'), findsOneWidget);
    expect(find.text('Années sèches'), findsOneWidget);
    expect(find.text('3 (25 %)'), findsOneWidget);
    expect(find.text('Meilleure Culture'), findsOneWidget);
    expect(find.text('Sorgho rouge'), findsOneWidget);
    expect(find.text('CA / ha (ML t+1)'), findsOneWidget);
    expect(find.text('420000 F'), findsOneWidget);
    expect(find.text('Risque Crédit'), findsOneWidget);
    expect(find.text('Élevé'), findsOneWidget);
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
}
