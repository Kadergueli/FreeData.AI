import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/screens/agriculture_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

List<Map<String, dynamic>> _series(String key, double base, double lastValue,
    {String unit = 'ratio (0-1)'}) {
  final points = <Map<String, dynamic>>[];
  for (final y in [2020, 2021, 2022, 2023]) {
    points.add({
      'reference_date': '$y-03-01',
      'value': base,
      'unit': unit,
      'baseline_mean': base,
      'anomaly_pct': 0.0,
    });
  }
  points.add({
    'reference_date': '2026-03-01',
    'value': lastValue,
    'unit': 'ratio (0-1)',
    'baseline_mean': base,
    'anomaly_pct': ((lastValue - base) / base * 100).roundToDouble(),
  });
  return points;
}

class _AgroFakeApi extends ApiService {
  bool dataAvailable = true;
  String? lastRegion;
  int profileCalls = 0;

  @override
  Future<Map<String, dynamic>> getAgroZones(
          {bool forceRefresh = false}) async =>
      {
        'title': 'Pré-diagnostic agro-climatique de zone',
        'data_available': dataAvailable,
        'zones': dataAvailable
            ? [
                {'region': 'Moundou', 'province': 'Logone Occidental'},
                {'region': "N'Djamena", 'province': "N'Djamena"},
              ]
            : <Map<String, dynamic>>[],
      };

  @override
  Future<Map<String, dynamic>> getAgroZoneProfile(String region,
      {bool forceRefresh = false}) async {
    lastRegion = region;
    profileCalls++;
    return {
      'title': 'Pré-diagnostic agro-climatique de zone',
      'region': region,
      'province': region == 'Moundou' ? 'Logone Occidental' : "N'Djamena",
      'indicator_labels': {
        'root_zone_wetness': 'Humidité de la zone racinaire',
        'surface_wetness': 'Humidité de surface du sol',
        'precipitation_daily_mean': 'Précipitations moyennes quotidiennes',
        'temperature_mean': 'Température moyenne',
      },
      'series': {
        'root_zone_wetness': _series('root_zone_wetness', 0.5, 0.3),
        'surface_wetness': _series('surface_wetness', 0.4, 0.38),
        'precipitation_daily_mean': _series(
          'precipitation_daily_mean', 3.0, 0.5, unit: 'mm/day'),
        'temperature_mean': _series(
          'temperature_mean', 28.0, 30.0, unit: '°C'),
      },
      'latest': {
        'root_zone_wetness': {
          'label': 'Humidité de la zone racinaire',
          'unit': unit,
          'reference_date': '2026-03-01',
          'value': 0.3,
        },
        'surface_wetness': {
          'label': 'Humidité de surface du sol',
          'unit': 'ratio (0-1)',
          'reference_date': '2026-03-01',
          'value': 0.38,
        },
        'precipitation_daily_mean': {
          'label': 'Précipitations moyennes quotidiennes',
          'unit': 'mm/day',
          'reference_date': '2026-03-01',
          'value': 0.5,
        },
        'temperature_mean': {
          'label': 'Température moyenne',
          'unit': '°C',
          'reference_date': '2026-03-01',
          'value': 30.0,
        },
      },
      'alerts': [
        {
          'region': region,
          'indicator_label': 'Humidité de la zone racinaire',
          'reference_date': '2026-03-01',
          'anomaly_pct': -40.0,
          'level': 'severe',
          'stale': false,
          'message': 'Humidité inférieure de 40 % à la normale du même mois.',
        }
      ],
      'stale': false,
      'provenance': {
        'sources': ['NASA POWER Agro', 'NASA POWER'],
        'licenses': ['Public Domain (U.S. Government / NASA)', 'CC BY 4.0'],
        'reference_period': {'first': '2020-01-01', 'last': '2026-03-01'},
        'spatial_resolution': ['regional_city_hub'],
        'confidence_level': ['Satellite_Modeled_Regional'],
      },
      'national': {
        'indicators': [
          {
            'key': 'cereal_yield',
            'indicator': 'Cereal yield',
            'unit': 'kg/ha',
            'latest': {'reference_date': '2024-01-01', 'value': 1050.0},
          },
        ],
        'provenance': {
          'sources': ['World Bank'],
          'licenses': ['CC BY 4.0'],
        },
      },
      'limitations': [
        'Précipitations et températures mensuelles modélisées à l’échelle régionale ; pas de mesure parcellaire.',
      ],
    };
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets(
      'AgricultureScreen enriches the existing zone view with NASA rainfall and temperature',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    final api = _AgroFakeApi();
    String? asked;
    await tester.pumpWidget(MaterialApp(
      home:
          AgricultureScreen(apiService: api, onAskAssistant: (p) => asked = p),
    ));
    await tester.pumpAndSettle();

    expect(find.text('Pré-diagnostic agro-climatique de zone'), findsOneWidget);
    expect(api.lastRegion, "N'Djamena");
    expect(find.textContaining('Déficit hydrique sévère'), findsOneWidget);
    expect(find.byKey(const ValueKey('agro-trend-chart')), findsOneWidget);
    expect(find.text('Rendement céréalier'), findsOneWidget);
    expect(find.text('Satellite modélisé (régional)'), findsOneWidget);
    expect(find.textContaining('NASA POWER Agro'), findsWidgets);
    expect(find.textContaining('Précipitations moyennes quotidiennes'),
        findsWidgets);
    expect(find.textContaining('Température moyenne'), findsWidgets);
    expect(find.textContaining('NASA POWER'), findsWidgets);
    expect(find.textContaining('analyse de parcelle'), findsWidgets);

    await tester.tap(find.text('Analyser cette zone avec l’assistant'));
    await tester.pumpAndSettle();
    expect(asked, contains("N'Djamena"));
    expect(asked, contains('précipitations'));
    expect(asked, contains('températures'));
    expect(tester.takeException(), isNull);
  });

  testWidgets('AgricultureScreen uses the saved default agro hub',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });
    SharedPreferences.setMockInitialValues({'fd_pref_agro_hub': 'Moundou'});

    final api = _AgroFakeApi();
    await tester.pumpWidget(
      MaterialApp(home: AgricultureScreen(apiService: api)),
    );
    await tester.pumpAndSettle();

    expect(api.lastRegion, 'Moundou');
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'AgricultureScreen shows a clean empty state when no data is ingested',
      (tester) async {
    final api = _AgroFakeApi()..dataAvailable = false;
    await tester
        .pumpWidget(MaterialApp(home: AgricultureScreen(apiService: api)));
    await tester.pumpAndSettle();

    expect(find.text('Données agro-climatiques en cours de chargement'),
        findsOneWidget);
    expect(api.profileCalls, 0);
    expect(tester.takeException(), isNull);
  });
}
