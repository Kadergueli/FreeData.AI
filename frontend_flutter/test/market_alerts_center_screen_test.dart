import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/screens/market_alerts_center_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

class _AlertsCenterApi extends ApiService {
  @override
  bool get hasPremiumKey => true;

  @override
  Future<List<dynamic>> getAlerts({
    double thresholdPct = 15.0,
    String? province,
    String? commodity,
  }) async =>
      [
        {
          'market_name': 'Moundou',
          'province': 'Logone Occidental',
          'commodity_std': 'Millet',
          'value': 250,
          'predicted_price': 210,
          'deviation_pct': 19.0,
        },
      ];

  @override
  Future<Map<String, dynamic>> getMarketIntelAlerts() async => {
        'rules': [
          {
            'rule_id': 'A-TEST',
            'kind': 'threshold',
            'triggered': true,
            'message': 'Mil : seuil observé atteint',
            'as_of': '2026-11',
          },
        ],
        'triggered': const [],
      };

  @override
  Future<Map<String, dynamic>> getMarketProOverview({String? cropId}) async => {
        'watchlists': [
          {
            'watch_id': 'W-TEST',
            'label_fr': 'Mil',
            'direction': 'above',
            'threshold_xaf_kg': 300,
            'predicted_xaf_kg': 315,
            'province': 'Salamat',
            'triggered': true,
          },
        ],
        'validated_forecasts': const [],
        'arbitrage': const [],
      };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets(
    'surveillance distinguishes observed rules from forecast watchlists',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: MarketAlertsCenterScreen(apiService: _AlertsCenterApi()),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Surveillance des marchés'), findsOneWidget);
      expect(find.text('Écarts de prix observés'), findsOneWidget);
      expect(find.text('Règles personnalisées · prix observés'), findsOneWidget);
      expect(find.text('Watchlists · prix prévisionnels'), findsOneWidget);
      expect(find.textContaining('Moundou'), findsOneWidget);
      expect(find.text('Mil : seuil observé atteint'), findsOneWidget);
      expect(find.textContaining('315 XAF/kg'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
