import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/core/utils/file_picker.dart';
import 'package:freedata_ai/screens/ml_benchmark_studio.dart';
import 'package:freedata_ai/services/api_service.dart';

class _StudioFakeApiService extends ApiService {
  int pollCalls = 0;
  String? lastLaunchedDomain;
  String? lastLaunchedTask;
  String? lastDeployedModelId;
  int? lastDeployedVersion;
  int rollbackCalls = 0;
  int? lastRollbackTargetVersion;

  final List<Map<String, dynamic>> jobs = [
    {
      'job_id': 'BENCH-HIST001',
      'domain': 'agriculture',
      'task_type': 'forecasting',
      'dataset_name': 'chad_mil_2026.csv',
      'dataset_hash': 'abcdef1234567890',
      'status': 'completed',
      'created_at': '2026-11-19T18:00:00+00:00',
      'result': {
        'candidates': [
          {
            'model_id': 'bench_agriculture_forecasting_ridge_causal_lags_a1',
            'version': 1,
            'algorithm': 'ridge_causal_lags_a1',
            'lifecycle_status': 'EVALUATION',
            'metrics': {'mae': 18.2, 'rmse': 22.4, 'mape_pct': 4.8, 'r2': 0.87},
            'duration_ms': 6.5,
          },
        ],
      },
    },
  ];

  @override
  Future<List<Map<String, dynamic>>> listAdminBenchmarkJobs(
    String adminToken, {
    int limit = 20,
  }) async =>
      jobs;

  @override
  Future<Map<String, dynamic>> launchAdminBenchmark(
    String adminToken, {
    required String domain,
    required String taskType,
    required List<String> featureColumns,
    String? targetColumn,
    String? timeColumn,
    required String datasetName,
    String datasetScope = 'platform_public',
    Map<String, dynamic> datasetProvenance = const {},
    required String csvBase64,
  }) async {
    lastLaunchedDomain = domain;
    lastLaunchedTask = taskType;
    return {
      'job_id': 'BENCH-NEW001',
      'domain': domain,
      'task_type': taskType,
      'dataset_name': datasetName,
      'dataset_hash': '1122334455667788',
      'status': 'queued',
      'progress_pct': 0,
    };
  }

  @override
  Future<Map<String, dynamic>> getAdminBenchmarkJob(
    String adminToken,
    String jobId,
  ) async {
    pollCalls += 1;
    return {
      'job_id': jobId,
      'domain': lastLaunchedDomain ?? 'agriculture',
      'task_type': lastLaunchedTask ?? 'forecasting',
      'dataset_name': 'sample.csv',
      'dataset_hash': '1122334455667788',
      'status': 'completed',
      'progress_pct': 100,
      'result': {
        'candidates': [
          {
            'model_id': 'bench_agriculture_forecasting_naive_last',
            'version': 1,
            'algorithm': 'naive_last',
            'lifecycle_status': 'EVALUATION',
            'metrics': {'mae': 24.0, 'rmse': 29.0},
            'duration_ms': 1.2,
          },
          {
            'model_id': 'bench_agriculture_forecasting_ridge_causal_lags_a1',
            'version': 1,
            'algorithm': 'ridge_causal_lags_a1',
            'lifecycle_status': 'EVALUATION',
            'metrics': {'mae': 14.5, 'rmse': 18.1},
            'duration_ms': 4.3,
          },
        ],
      },
    };
  }

  @override
  Future<Map<String, dynamic>> rollbackAdminMlModel(
    String adminToken,
    String modelId, {
    required int targetVersion,
    String reason = 'Admin rollback',
  }) async {
    rollbackCalls++;
    lastRollbackTargetVersion = targetVersion;
    return {'model_id': modelId, 'target_version': targetVersion};
  }

  @override
  Future<Map<String, dynamic>> transitionAdminMlModelStatus(
    String adminToken,
    String modelId, {
    required int version,
    required String lifecycleStatus,
    bool setActive = false,
    bool? enabled,
    bool force = false,
    String reason = 'Admin AI Control Center',
  }) async {
    lastDeployedModelId = modelId;
    lastDeployedVersion = version;
    return {
      'model_id': modelId,
      'version': version,
      'lifecycle_status': lifecycleStatus,
      'is_active_production': setActive,
    };
  }
}

Map<String, dynamic> _sampleOverview() => {
      'domains_summary': {
        'total_domains': 2,
        'active_domains': 2,
        'domains': [
          {
            'domain_id': 'markets_and_prices',
            'label_fr': 'Marchés et prix des produits',
            'data_status': 'operational',
            'active': true,
            'required_tier': 'free',
            'usage_count': 12,
          },
          {
            'domain_id': 'economy',
            'label_fr': 'Économie',
            'data_status': 'in_preparation',
            'active': true,
            'required_tier': 'free',
            'usage_count': 4,
          },
        ],
      },
      'ml_registry_summary': {
        'persistence_backend': 'supabase_postgresql',
        'loaded_count': 1,
        'max_loaded_models': 4,
      },
      'ai_infrastructure': {
        'ml_engine': 'CONNECTED',
        'rag_engine': 'CONNECTED',
        'model_registry': 'CONNECTED',
      },
      'ml_models': [
        {
          'model_id': 'ridge_price_regressor',
          'version': 1,
          'algorithm': 'RidgeRegression_L2_Gold',
          'domain': 'agriculture',
          'task_type': 'forecasting',
          'training_dataset_ref': 'table_ml_forecasts:2026-10',
          'lifecycle_status': 'EVALUATION',
          'is_active_production': false,
          'evaluation_metrics': {'mae_xaf_kg': 17.5, 'rmse_xaf_kg': 21.8},
        },
      ],
    };

void main() {
  testWidgets(
      'MLBenchmarkStudio runs 5-step CSV benchmark with bounded polling and renders results',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 960);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    final api = _StudioFakeApiService();
    final csvBytes = Uint8List.fromList(
      utf8.encode(
          'month,"price, XAF"\n2025-01,300\n2025-02,310\n2025-03,320\n'),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: MLBenchmarkStudio(
              apiService: api,
              adminToken: 'super-admin-token-1234567890',
              overview: _sampleOverview(),
              canManageModels: true,
              onRefreshOverview: () async {},
              onCompareModel: (_) async {},
              statusColor: (_) => Colors.green,
              pollInterval: const Duration(milliseconds: 50),
              onPickCsv: () async => PickedDocumentFile(
                name: 'sample.csv',
                bytes: csvBytes,
                mimeType: 'text/csv',
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Overview KPIs rendered from real backend data
    expect(find.text('ML Benchmark Studio & Centre de Contrôle IA'),
        findsOneWidget);
    expect(find.text('supabase_postgresql'), findsOneWidget);

    // Navigate to Expériences -> pick CSV -> Config -> Revue -> Launch
    await tester.tap(find.widgetWithText(ChoiceChip, 'Expériences'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Sélectionner un fichier CSV'));
    await tester.pumpAndSettle();
    expect(find.textContaining('sample.csv'), findsOneWidget);
    expect(find.text('price, XAF'), findsOneWidget);

    await tester.tap(find.text('Continuer vers la configuration'));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextField, 'Source du jeu de données (obligatoire)'),
      'FreeData.td test dataset',
    );
    await tester.enterText(
      find.widgetWithText(TextField, 'Licence (obligatoire)'),
      'CC BY 4.0',
    );
    await tester.ensureVisible(find.text('Passer à la revue'));
    await tester.tap(find.text('Passer à la revue'));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.text('Lancer le benchmark'));
    await tester.tap(find.text('Lancer le benchmark'));
    await tester.pump(const Duration(milliseconds: 150));
    await tester.pumpAndSettle();

    expect(api.lastLaunchedDomain, 'markets_and_prices');
    expect(api.lastLaunchedTask, 'forecasting');
    expect(api.pollCalls, greaterThanOrEqualTo(1));
    expect(find.textContaining('ridge_causal_lags_a1'), findsOneWidget);
  });

  testWidgets(
      'MLBenchmarkStudio enforces Human Approval confirmation dialog and RBAC read-only mode',
      (tester) async {
    final api = _StudioFakeApiService();

    // 1. Read-only analyst cannot see launch or deploy controls
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: MLBenchmarkStudio(
              apiService: api,
              adminToken: 'analyst-token-1234567890',
              overview: _sampleOverview(),
              canManageModels: false,
              onRefreshOverview: () async {},
              onCompareModel: (_) async {},
              statusColor: (_) => Colors.blue,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Lecture seule'), findsOneWidget);
    expect(find.text('Nouvelle expérience CSV'), findsNothing);

    await tester.tap(find.text('Registre ML'));
    await tester.pumpAndSettle();
    expect(find.text('Approuver & Déployer'), findsNothing);

    // 2. Super admin must confirm deployment in explicit Human Approval dialog
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: MLBenchmarkStudio(
              apiService: api,
              adminToken: 'super-admin-token-1234567890',
              overview: _sampleOverview(),
              canManageModels: true,
              onRefreshOverview: () async {},
              onCompareModel: (_) async {},
              statusColor: (_) => Colors.green,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Registre ML'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Approuver & Déployer'));
    await tester.pumpAndSettle();
    expect(
        find.text('Approbation de déploiement en production'), findsOneWidget);
    expect(
        api.lastDeployedModelId, isNull); // Not deployed before confirmation!

    await tester.tap(find.text('Confirmer le déploiement'));
    await tester.pumpAndSettle();
    expect(api.lastDeployedModelId, 'ridge_price_regressor');
    expect(api.lastDeployedVersion, 1);
  });
  testWidgets(
      'MLBenchmarkStudio confirms rollback before changing model version',
      (tester) async {
    final api = _StudioFakeApiService();
    final overview = _sampleOverview();
    final models = overview['ml_models'] as List;
    models.add({
      ...Map<String, dynamic>.from(models.first as Map),
      'version': 2,
      'is_active_production': false,
    });

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: MLBenchmarkStudio(
              apiService: api,
              adminToken: 'super-admin-token-1234567890',
              overview: overview,
              canManageModels: true,
              onRefreshOverview: () async {},
              onCompareModel: (_) async {},
              statusColor: (_) => Colors.green,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Registre ML'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Rollback → v1'));
    await tester.tap(find.text('Rollback → v1'));
    await tester.pumpAndSettle();

    expect(find.text('Confirmer le rollback'), findsOneWidget);
    expect(api.rollbackCalls, 0);
    await tester.tap(find.text('Annuler'));
    await tester.pumpAndSettle();
    expect(api.rollbackCalls, 0);

    await tester.ensureVisible(find.text('Rollback → v1'));
    await tester.tap(find.text('Rollback → v1'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confirmer le rollback'));
    await tester.pumpAndSettle();
    expect(api.rollbackCalls, 1);
    expect(api.lastRollbackTargetVersion, 1);
  });
}
