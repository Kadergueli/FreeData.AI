import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/screens/analytics_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

class _FakeAnalyticsApiService extends ApiService {
  _FakeAnalyticsApiService();

  @override
  Future<Map<String, dynamic>> getMetadata() async => {
        'commodities': [
          'Millet',
          'Sorghum (red)',
          'Groundnuts (shelled)',
          'Cowpeas'
        ],
        'provinces': ["N'Djamena", 'Lac', 'Salamat', 'Batha'],
      };

  @override
  Future<Map<String, dynamic>> getAnalyticsProfile() async => {
        'forecast_rows': 120,
        'provinces_count': 12,
        'commodities_count': 8,
        'latest_observed_month': '2026-10',
      };

  @override
  Future<Map<String, dynamic>> getAnalyticsSummary(
          {String? commodity, String? province}) async =>
      {
        'descriptive': {
          'stats': {
            'median': 275,
            'mean': 280,
            'min': 190,
            'max': 390,
            'cv_pct': 14.2
          },
        },
        'most_volatile_commodities': [
          {'commodity': 'Fish (dry)', 'avg_cv_pct': 24.5},
          {'commodity': 'Millet', 'avg_cv_pct': 12.1},
        ],
      };

  @override
  Future<Map<String, dynamic>> getRegionalComparison(
          {String? commodity}) async =>
      {
        'provinces': [
          {
            'province': "N'Djamena",
            'markets_count': 2,
            'median_observed_xaf_kg': 290,
            'median_forecast_t1_xaf_kg': 276,
          },
          {
            'province': 'Lac',
            'markets_count': 3,
            'median_observed_xaf_kg': 230,
            'median_forecast_t1_xaf_kg': 235,
          },
        ],
      };

  @override
  Future<Map<String, dynamic>> getAnalyticsTrends(
          {String? commodity, String? province, int limit = 24}) async =>
      {
        'change_12m_pct': -4.5,
        'records': [
          {'month': '2026-07', 'median_price_xaf_kg': 300.0},
          {'month': '2026-08', 'median_price_xaf_kg': 295.0},
          {'month': '2026-09', 'median_price_xaf_kg': 285.0},
          {'month': '2026-10', 'median_price_xaf_kg': 276.0},
        ],
      };

  @override
  Future<Map<String, dynamic>> getForecastBenchmark(
          {required String commodity, required String province}) async =>
      {
        'status': 'evaluated',
        'observations': 24,
        'models': [
          {'model': 'Naive (t-1)', 'mae': 18.4, 'rmse': 22.1, 'mape_pct': 6.7},
          {
            'model': 'Moyenne Mobile (3m)',
            'mae': 15.2,
            'rmse': 19.0,
            'mape_pct': 5.5
          },
        ],
      };

  @override
  Future<List<dynamic>> getForecasts(
          {String? province, String? commodity}) async =>
      [
        {
          'commodity': 'Millet',
          'province': "N'Djamena",
          'forecast_t1': 276.0,
          'ci_low_80': 245.0,
          'ci_high_80': 308.0,
        },
      ];
}

class _UnavailableOptionalAnalyticsApiService
    extends _FakeAnalyticsApiService {
  @override
  Future<Map<String, dynamic>> getForecastBenchmark({
    required String commodity,
    required String province,
  }) async {
    throw Exception('benchmark unavailable');
  }

  @override
  Future<List<dynamic>> getForecasts({
    String? province,
    String? commodity,
  }) async {
    throw Exception('forecast unavailable');
  }

  @override
  Future<Map<String, dynamic>> getAnalyticsTrends({
    String? commodity,
    String? province,
    int limit = 24,
  }) async =>
      {
        'records': [
          {'month': '2026-08', 'median_price_xaf_kg': 295.0},
          {'month': '2026-09', 'median_price_xaf_kg': null},
          {'month': '2026-10', 'median_price_xaf_kg': 276.0},
        ],
      };
}

void main() {
  testWidgets(
      'AnalyticsScreen renders trend curve, backtest benchmark, and formula panel',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: AnalyticsScreen(apiService: _FakeAnalyticsApiService()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Courbe d’évolution mensuelle (XAF/kg)'), findsOneWidget);
    expect(find.textContaining('Prévision t+1 : 276'), findsOneWidget);
    expect(
        find.textContaining('Intervalle 80 % : [245 – 308]'), findsOneWidget);
    expect(find.textContaining('Backtest 70/30'), findsOneWidget);
    expect(find.textContaining('MAE : 15.2'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Méthode & Formules Mathématiques'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Méthode & Formules Mathématiques'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('AnalyticsScreen labels optional service failures and ignores invalid prices',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: AnalyticsScreen(
          apiService: _UnavailableOptionalAnalyticsApiService(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.textContaining('Prévision temporairement indisponible'),
      findsOneWidget,
    );
    expect(
      find.textContaining('backtest est temporairement indisponible'),
      findsOneWidget,
    );
    expect(find.textContaining('Min : 0 XAF/kg'), findsNothing);
    expect(tester.takeException(), isNull);
  });

}
