import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/screens/agronomist_pro_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

class _AgroProFakeApi extends ApiService {
  Map<String, dynamic>? lastPayload;
  String? lastPdfId;

  @override
  Future<Map<String, dynamic>?> getMyAgroProfile() async => {
        'firm_name': 'Cabinet Test',
        'license_number': 'AGR-TEST-01',
        'address': "N'Djamena",
        'contact': '+235 66 00 00 00',
        'status': 'approved',
      };

  @override
  Future<List<Map<String, dynamic>>> listAgroFieldAssessments(
          {String? projectId}) async =>
      const [];

  @override
  Future<Map<String, dynamic>> createAgroFieldAssessment({
    required String provinceHub,
    String? projectId,
    double? gpsLat,
    double? gpsLon,
    double? areaHectares,
    double? customYieldKgHa,
    required Map<String, dynamic> labSoilInputs,
    String agronomistFieldNotes = '',
    List<String> targetCrops = const [
      'millet',
      'sorghum',
      'maize',
      'groundnut_raw',
    ],
  }) async {
    lastPayload = {
      'province_hub': provinceHub,
      'lab_soil_inputs': labSoilInputs,
    };
    final hasLab = labSoilInputs.isNotEmpty;
    return {
      'assessment': {
        'id': 'AG-TEST-1',
        'province_hub': provinceHub,
        'report_verification_code': 'FDT-2026-AB12CD',
        'computed_scores': {
          'title': hasLab
              ? 'Diagnostic de terrain (pré-achat)'
              : 'Pré-diagnostic agro-climatique de zone',
          'confidence_level': hasLab
              ? 'Terrain + Régional (Mesures labo fournies)'
              : 'Régional uniquement — Mesures sol non fournies',
          'crop_assessments': [
            {
              'crop_id': 'millet',
              'label_fr': 'Mil',
              'suitability_score': 85,
              'suitability_label': 'Favorable',
              'limiting_factors':
                  hasLab ? <String>[] : <String>['Mesures labo non fournies'],
              'market_forecast': {
                'scope': 'Logone Occidental',
                'predicted_xaf_kg': 285.0,
              },
              'indicative_gross_revenue_xaf': 2992500,
            },
          ],
        },
      },
      'qa': {
        'can_deliver_pdf': hasLab,
        'blockers': hasLab
            ? <String>[]
            : <String>['Mesures de sol laboratoire absentes.'],
      },
    };
  }

  @override
  Future<Uint8List> downloadAgroAssessmentPdf(
    String assessmentId, {
    String agronomistName = '',
    String agronomistLicense = '',
    String agronomistAddress = '',
    String agronomistContact = '',
    List<String> compareAssessmentIds = const [],
  }) async {
    lastPdfId = assessmentId;
    return Uint8List.fromList([0x25, 0x50, 0x44, 0x46]);
  }
}

void main() {
  testWidgets(
      'AgronomistProScreen gates guest users and runs field diagnostic when PRO',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 1600);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    final guestApi = _AgroProFakeApi();
    await tester.pumpWidget(
      MaterialApp(home: AgronomistProScreen(apiService: guestApi)),
    );
    await tester.pumpAndSettle();
    expect(find.text('ESPACE AGRONOME PRO'), findsOneWidget);
    expect(find.text('Se connecter'), findsOneWidget);

    final proApi = _AgroProFakeApi()
      ..setAuthSession(
        token: 'jwt-pro',
        user: {'user_id': 'u123', 'email': 'agro@tchad.td'},
        isPro: true,
      );
    await tester.pumpWidget(
      MaterialApp(
          home: AgronomistProScreen(
              key: const ValueKey('pro'), apiService: proApi)),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextField, 'pH du sol (labo)'),
      '6.3',
    );
    final areaField =
        find.widgetWithText(TextField, 'Superficie exacte (ha) *');
    await tester.scrollUntilVisible(
      areaField,
      160,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.enterText(areaField, '2.5');
    final calcBtn = find.text('Calculer le diagnostic');
    await tester.scrollUntilVisible(calcBtn, 200,
        scrollable: find.byType(Scrollable).first);
    await tester.tap(calcBtn);
    await tester.pumpAndSettle();

    expect(proApi.lastPayload?['lab_soil_inputs']?['ph'], 6.3);
    expect(find.textContaining('FDT-2026-AB12CD'), findsWidgets);
    expect(find.textContaining('1. Fiche d’Identification Parcellaire'),
        findsOneWidget);
    expect(find.textContaining('3. Matrice Comparative d’Aptitude Culturale'),
        findsOneWidget);
    expect(find.text('Mil'), findsOneWidget);
    expect(find.text('Favorable'), findsOneWidget);
    expect(find.text('Télécharger le rapport PDF co-brandé'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
