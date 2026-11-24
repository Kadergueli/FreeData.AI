import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/screens/market_pro_screen.dart';
import 'package:freedata_ai/screens/farm_operating_account_screen.dart';
import 'package:freedata_ai/screens/campaign_plan_screen.dart';
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
        'status': 'ok',
        'forecast_month': '2026-11',
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
  }) async =>
      {
        'label_fr': 'Mil',
        'province': province,
        'area_hectares': areaHectares,
        'production_kg': 2000,
        'yield_kg_ha': 1000,
        'yield_source': 'saisie utilisateur',
        'opex_total_xaf': 200000,
        'capex_total_xaf': capexTotalXaf,
        'total_investment_xaf': 200000 + capexTotalXaf,
        'breakeven_price_opex_xaf_kg': 100,
        'breakeven_yield_kg_ha': 500,
        'opex_breakdown': const [],
        'investor_readiness_notes': const ['Prix de vente à confirmer.'],
        'scenarios': [
          {
            'label': 'Central',
            'farmgate_price_xaf_kg': 180,
            'gross_revenue_xaf': 360000,
            'ebitda_margin_xaf': 160000,
            'net_profit_after_capex_xaf': 120000,
            'roi_on_opex_pct': 60,
            'dscr': 1.4,
          },
        ],
      };

  @override
  Future<Map<String, dynamic>> computeCampaignPlan({
    required double capitalXaf,
    required String originProvince,
    String entrepreneurStatus = 'petit_commercant',
    String? cropId,
    int? holdingMonths,
    double coroWeightKg = 2.5,
    double transportPerBagXaf = 0,
    double storagePerBagMonthXaf = 0,
    double lossPct = 0,
  }) async =>
      {
        'origin_province': originProvince,
        'entrepreneur_label': 'Petit commerçant',
        'recommended_plan': {
          'label_fr': 'Mil',
          'timing_signal': 'fenetre_achat',
          'timing_label': 'Fenêtre d’achat',
          'percentile_rank_pct': 25,
          'bags_count': 10,
          'coros_equiv': 20,
          'coro_weight_kg': coroWeightKg,
          'buy_price_xaf_kg': 150,
          'buy_price_bag_100kg_xaf': 15000,
          'breakeven_price_xaf_kg': 180,
          'cash_reserve_xaf': 100000,
          'cheapest_months': ['Juin'],
          'peak_months': ['Novembre'],
          'holding_months': holdingMonths ?? 2,
          'target_exit_month': 'Août',
          'whatsapp_summary': 'Plan test',
          'scenarios': [
            {
              'label': 'Central',
              'sell_price_xaf_kg': 250,
              'net_profit_xaf': 200000,
              'roi_pct': 40,
            },
          ],
        },
        'strategic_advice': const [],
        'all_opportunities': const [],
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

class _InsufficientArbitrageApi extends _MarketRadarApi {
  @override
  Future<Map<String, dynamic>> getSpatialArbitrage({
    required String cropId,
    double? transportCostXafKg,
    double? tonnage,
  }) async => {
        'status': 'insufficient_data',
        'status_message': 'Aucun mois de prévision commun à au moins deux provinces.',
        'forecast_month': null,
        'routes': const [],
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

  testWidgets('arbitrage displays the shared forecast month and gross-spread caveat',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(
      MaterialApp(home: MarketProScreen(apiService: _MarketRadarApi())),
    );
    await tester.pumpAndSettle();

    final simulate = find.text('Calculer écart / marge');
    await tester.scrollUntilVisible(
      simulate,
      240,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(simulate);
    await tester.pumpAndSettle();

    expect(find.text('Période commune de comparaison : 2026-11'),
        findsOneWidget);
    expect(find.textContaining('L’écart de prix est un indicateur brut'),
        findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('arbitrage explains when no shared forecast month is available',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(
      MaterialApp(home: MarketProScreen(apiService: _InsufficientArbitrageApi())),
    );
    await tester.pumpAndSettle();

    final simulate = find.text('Calculer écart / marge');
    await tester.scrollUntilVisible(
      simulate,
      240,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(simulate);
    await tester.pumpAndSettle();

    expect(find.text(
      'Aucun mois de prévision commun à au moins deux provinces.',
    ), findsOneWidget);
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

    final simulate = find.text('Calculer écart / marge');
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
    expect(capturedPrompt, contains('marge après transport déclaré'));

    final businessPlan = find.text('Créer un business plan');
    await tester.tap(businessPlan);
    expect(capturedPrompt, contains('business plan agricole professionnel'));
    expect(capturedPrompt,
        contains('demande-le avant de produire les projections'));
  });

  testWidgets(
      'farm operating account results can be explained and planned with AI',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    String? capturedPrompt;
    await tester.pumpWidget(
      MaterialApp(
        home: FarmOperatingAccountScreen(
          apiService: _MarketRadarApi(),
          onSelectPrompt: (prompt) => capturedPrompt = prompt,
        ),
      ),
    );
    await tester.pumpAndSettle();

    final calculate = find.text('Calculer le Compte d’Exploitation');
    await tester.scrollUntilVisible(
      calculate,
      240,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(calculate);
    await tester.pumpAndSettle();

    final explain = find.text('Expliquer avec l’IA');
    await tester.scrollUntilVisible(
      explain,
      240,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(explain);
    expect(
        capturedPrompt, contains('Explique le compte d’exploitation agricole'));
    expect(capturedPrompt, contains('marge EBITDA'));
    expect(capturedPrompt, contains('Seuil de rentabilité'));

    await tester.tap(find.text('Créer un business plan'));
    expect(capturedPrompt, contains('business plan agricole'));
    expect(capturedPrompt, contains('capital initial'));
  });

  testWidgets(
      'campaign plan results pass capital provenance and scenarios to AI',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    String? capturedPrompt;
    await tester.pumpWidget(
      MaterialApp(
        home: CampaignPlanScreen(
          apiService: _MarketRadarApi(),
          onSelectPrompt: (prompt) => capturedPrompt = prompt,
        ),
      ),
    );
    await tester.pumpAndSettle();

    final capitalField = find.byType(TextField).first;
    expect(tester.widget<TextField>(capitalField).controller!.text, isEmpty);
    await tester.enterText(capitalField, '500000');

    final simulate = find.text('Simuler mon Plan de Campagne');
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
      240,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(explain);
    expect(capturedPrompt, contains('Explique la recommandation'));
    expect(capturedPrompt, contains('point mort'));
    expect(capturedPrompt, contains('Fenêtre d’achat'));

    await tester.tap(find.text('Créer un business plan'));
    expect(capturedPrompt, contains('business plan commercial agricole'));
    expect(capturedPrompt,
        contains('Capital saisi par l’utilisateur : 500000 XAF'));
    expect(capturedPrompt,
        isNot(contains('capital réel de l’utilisateur n’est pas confirmé')));
  });
}
