import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import '../widgets/chat/data_cards.dart';

class AnalyticsScreen extends StatefulWidget {
  final ApiService apiService;

  const AnalyticsScreen({super.key, required this.apiService});

  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  Map<String, dynamic>? _profile;
  Map<String, dynamic>? _summary;
  Map<String, dynamic>? _regional;
  Map<String, dynamic>? _trends;
  Map<String, dynamic>? _benchmark;
  Map<String, dynamic>? _latestForecast;
  String? _selectedCommodity;
  String? _selectedProvince;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final benchComm = _selectedCommodity ?? 'Millet';
      final benchProv = _selectedProvince ?? "N'Djamena";
      final results = await Future.wait([
        widget.apiService.getAnalyticsProfile(),
        widget.apiService.getAnalyticsSummary(commodity: _selectedCommodity),
        widget.apiService.getRegionalComparison(commodity: _selectedCommodity),
        widget.apiService.getAnalyticsTrends(
          commodity: _selectedCommodity,
          province: _selectedProvince,
          limit: 24,
        ),
        widget.apiService.getForecastBenchmark(
          commodity: benchComm,
          province: benchProv,
        ),
      ]);
      Map<String, dynamic>? forecastSample;
      try {
        final fcList = await widget.apiService.getForecasts(
          commodity: benchComm,
          province: _selectedProvince,
        );
        if (fcList.isNotEmpty && fcList.first is Map) {
          forecastSample = Map<String, dynamic>.from(fcList.first as Map);
        }
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _profile = results[0];
        _summary = results[1];
        _regional = results[2];
        _trends = results[3];
        _benchmark = results[4];
        _latestForecast = forecastSample;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Widget _statPill(String label, String value, {Color color = AppColors.ink}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.canvas,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label, style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
          const SizedBox(height: 2),
          Text(value, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: color)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final stats = (_summary?['descriptive'] as Map?)?['stats'] as Map?;
    final volatileList = (_summary?['most_volatile_commodities'] as List? ?? []).cast<Map>();
    final provinces = (_regional?['provinces'] as List? ?? []).cast<Map>();
    final trendRecords = (_trends?['records'] as List? ?? []).cast<Map>();
    final change12m = _trends?['change_12m_pct'];
    final benchModels = (_benchmark?['models'] as List? ?? []).cast<Map>();

    final provinceChart = <String, dynamic>{
      for (final p in provinces.take(8))
        if (p['median_observed_xaf_kg'] != null)
          p['province'].toString(): num.tryParse(p['median_observed_xaf_kg'].toString()) ?? 0,
    };
    final volatilityChart = <String, dynamic>{
      for (final v in volatileList.take(6))
        if (v['avg_cv_pct'] != null)
          v['commodity'].toString(): num.tryParse(v['avg_cv_pct'].toString()) ?? 0,
    };

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
        title: const Text('Analytics & Preuves Statistiques', style: TextStyle(fontWeight: FontWeight.w700)),
        actions: [
          DropdownButton<String?>(
            value: _selectedCommodity,
            hint: const Text('Tous produits'),
            underline: const SizedBox.shrink(),
            items: const [
              DropdownMenuItem(value: null, child: Text('Tous produits')),
              DropdownMenuItem(value: 'Millet', child: Text('Mil')),
              DropdownMenuItem(value: 'Sorghum (red)', child: Text('Sorgho')),
              DropdownMenuItem(value: 'Rice (imported)', child: Text('Riz importé')),
              DropdownMenuItem(value: 'Maize (white)', child: Text('Maïs blanc')),
            ],
            onChanged: (v) {
              setState(() => _selectedCommodity = v);
              _load();
            },
          ),
          const SizedBox(width: 8),
          DropdownButton<String?>(
            value: _selectedProvince,
            hint: const Text('Toutes provinces'),
            underline: const SizedBox.shrink(),
            items: const [
              DropdownMenuItem(value: null, child: Text('Toutes provinces')),
              DropdownMenuItem(value: "N'Djamena", child: Text("N'Djamena")),
              DropdownMenuItem(value: 'Lac', child: Text('Lac')),
              DropdownMenuItem(value: 'Salamat', child: Text('Salamat')),
              DropdownMenuItem(value: 'Logone Occidental', child: Text('Logone Occ.')),
              DropdownMenuItem(value: 'Ouaddai', child: Text('Ouaddaï')),
            ],
            onChanged: (v) {
              setState(() => _selectedProvince = v);
              _load();
            },
          ),
          const SizedBox(width: 12),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: FDCard(
                    child: Text(_error!, style: const TextStyle(color: AppColors.danger)),
                  ),
                )
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    if (_profile != null)
                      FDCard(
                        child: Wrap(
                          spacing: 10,
                          runSpacing: 10,
                          children: [
                            _statPill('Séries suivies', '${_profile!['forecast_rows'] ?? '—'}', color: AppColors.blue),
                            _statPill('Provinces', '${_profile!['provinces_count'] ?? '—'}'),
                            _statPill('Produits', '${_profile!['commodities_count'] ?? '—'}'),
                            _statPill('Dernier mois', '${_profile!['latest_observed_month'] ?? '—'}', color: AppColors.green),
                          ],
                        ),
                      ),
                    if (trendRecords.length >= 2) ...[
                      const SizedBox(height: 12),
                      FDCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                const Expanded(
                                  child: Text(
                                    'Courbe d’évolution mensuelle (XAF/kg)',
                                    style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                                  ),
                                ),
                                if (change12m != null)
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                                    decoration: BoxDecoration(
                                      color: (num.tryParse(change12m.toString()) ?? 0) > 0
                                          ? AppColors.dangerSoft
                                          : AppColors.greenSoft,
                                      borderRadius: BorderRadius.circular(99),
                                    ),
                                    child: Text(
                                      '12m : $change12m %',
                                      style: TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                        color: (num.tryParse(change12m.toString()) ?? 0) > 0
                                            ? AppColors.dangerDark
                                            : AppColors.greenDark,
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            _PriceTrendLineChart(
                              records: trendRecords,
                              forecastT1: double.tryParse(_latestForecast?['forecast_t1_xaf_kg']?.toString() ?? ''),
                              ciLow80: double.tryParse(_latestForecast?['ci_low_80']?.toString() ?? ''),
                              ciHigh80: double.tryParse(_latestForecast?['ci_high_80']?.toString() ?? ''),
                            ),
                          ],
                        ),
                      ),
                    ],
                    if (benchModels.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      FDCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Preuve Statistique — Backtest 70/30 (${_selectedCommodity ?? 'Millet'} · ${_selectedProvince ?? "N'Djamena"})',
                              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'Évaluation chronologique hors-échantillon sur ${_benchmark?['observations'] ?? '—'} mois observés (zéro fuite future).',
                              style: const TextStyle(fontSize: 12.5, color: AppColors.muted),
                            ),
                            const SizedBox(height: 10),
                            ...benchModels.map((m) => Padding(
                                  padding: const EdgeInsets.symmetric(vertical: 4),
                                  child: Row(
                                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                    children: [
                                      Expanded(
                                        child: Text(
                                          m['model']?.toString() ?? 'Modèle',
                                          style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.ink),
                                        ),
                                      ),
                                      Text(
                                        'MAE : ${m['mae'] ?? '—'} · RMSE : ${m['rmse'] ?? '—'} · MAPE : ${m['mape_pct'] ?? '—'} %',
                                        style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: AppColors.blue),
                                      ),
                                    ],
                                  ),
                                )),
                          ],
                        ),
                      ),
                    ],
                    if (stats != null) ...[
                      const SizedBox(height: 12),
                      FDCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Statistiques descriptives (XAF/kg)',
                              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                            ),
                            const SizedBox(height: 10),
                            Wrap(
                              spacing: 10,
                              runSpacing: 10,
                              children: [
                                _statPill('Médiane', '${stats['median']} XAF/kg', color: AppColors.blue),
                                _statPill('Moyenne', '${stats['mean']} XAF/kg'),
                                _statPill('Min – Max', '${stats['min']} – ${stats['max']}'),
                                _statPill('Volatilité (CV)', '${stats['cv_pct']} %', color: AppColors.warning),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                    if (provinceChart.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      FDCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Graphique — Prix médians observés par province (XAF/kg)',
                              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                            ),
                            ChartCard(data: provinceChart),
                            const SizedBox(height: 10),
                            ...provinces.take(8).map(
                                  (p) => Padding(
                                    padding: const EdgeInsets.symmetric(vertical: 4),
                                    child: Row(
                                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                      children: [
                                        Expanded(
                                          child: Text(
                                            '${p['province']} (${p['markets_count']} marchés · prévu t+1 : ${p['median_forecast_t1_xaf_kg'] ?? '—'})',
                                            style: const TextStyle(fontSize: 13, color: AppColors.body),
                                          ),
                                        ),
                                        Text(
                                          '${p['median_observed_xaf_kg'] ?? '—'} XAF/kg',
                                          style: const TextStyle(fontWeight: FontWeight.w700, color: AppColors.blue),
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                          ],
                        ),
                      ),
                    ],
                    if (volatilityChart.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      FDCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Graphique — Produits les plus volatils (CV %)',
                              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                            ),
                            ChartCard(data: volatilityChart),
                          ],
                        ),
                      ),
                    ],
                    const SizedBox(height: 12),
                    FDCard(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                      child: const ExpansionTile(
                        tilePadding: EdgeInsets.zero,
                        title: Text(
                          'Méthode & Formules Mathématiques',
                          style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700, color: AppColors.ink),
                        ),
                        children: [
                          Padding(
                            padding: EdgeInsets.only(bottom: 10),
                            child: Text(
                              '1. Normalisation : tous les relevés WFP / FEWS NET sont convertis en XAF/kg.\n'
                              '2. Backtest chronologique 70/30 : MAE = moyenne(|y - ŷ|), RMSE = √(moyenne((y - ŷ)²)), MAPE = moyenne(|y - ŷ| / y) × 100.\n'
                              '3. Intervalles 80 % : calibration conforme hors-échantillon (ci_low_80, ci_high_80) avec mention explicite si l’historique est lacunaire.\n'
                              '4. Moteur financier 80/8/12 : sépare données observées, simulées et hypothèses promoteur sans jamais forcer la rentabilité.',
                              style: TextStyle(fontSize: 12.5, height: 1.5, color: AppColors.body),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
    );
  }
}

class _PriceTrendLineChart extends StatelessWidget {
  final List<Map> records;
  final double? forecastT1;
  final double? ciLow80;
  final double? ciHigh80;

  const _PriceTrendLineChart({
    required this.records,
    this.forecastT1,
    this.ciLow80,
    this.ciHigh80,
  });

  @override
  Widget build(BuildContext context) {
    final values = records
        .map((r) => double.tryParse(r['median_price_xaf_kg']?.toString() ?? '') ?? 0.0)
        .toList();
    final allScale = <double>[
      ...values,
      if (forecastT1 != null) forecastT1!,
      if (ciLow80 != null) ciLow80!,
      if (ciHigh80 != null) ciHigh80!,
    ];
    final minVal = allScale.reduce(math.min);
    final maxVal = allScale.reduce(math.max);
    final firstMonth = records.first['month']?.toString() ?? '';
    final lastMonth = records.last['month']?.toString() ?? '';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('Min : ${minVal.toStringAsFixed(0)} XAF/kg', style: const TextStyle(fontSize: 11.5, color: AppColors.muted)),
            Text('Max : ${maxVal.toStringAsFixed(0)} XAF/kg', style: const TextStyle(fontSize: 11.5, color: AppColors.blue, fontWeight: FontWeight.w600)),
          ],
        ),
        const SizedBox(height: 6),
        SizedBox(
          height: 145,
          width: double.infinity,
          child: CustomPaint(
            painter: _TrendPainter(
              values: values,
              forecastT1: forecastT1,
              ciLow80: ciLow80,
              ciHigh80: ciHigh80,
            ),
          ),
        ),
        const SizedBox(height: 6),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(firstMonth, style: const TextStyle(fontSize: 11, color: AppColors.subtle)),
            Text(
              forecastT1 != null ? '$lastMonth → t+1 (${forecastT1!.toStringAsFixed(0)})' : lastMonth,
              style: const TextStyle(fontSize: 11, color: AppColors.subtle),
            ),
          ],
        ),
        if (forecastT1 != null) ...[
          const SizedBox(height: 6),
          Wrap(
            spacing: 12,
            runSpacing: 4,
            children: [
              const Text('● Historique (XAF/kg)', style: TextStyle(fontSize: 11, color: AppColors.blue, fontWeight: FontWeight.w600)),
              Text(
                '● Prévision t+1 : ${forecastT1!.toStringAsFixed(0)} XAF/kg',
                style: const TextStyle(fontSize: 11, color: AppColors.greenDark, fontWeight: FontWeight.w600),
              ),
              if (ciLow80 != null && ciHigh80 != null)
                Text(
                  '▒ Intervalle 80 % : [${ciLow80!.toStringAsFixed(0)} – ${ciHigh80!.toStringAsFixed(0)}]',
                  style: const TextStyle(fontSize: 11, color: AppColors.muted),
                ),
            ],
          ),
        ],
      ],
    );
  }
}

class _TrendPainter extends CustomPainter {
  final List<double> values;
  final double? forecastT1;
  final double? ciLow80;
  final double? ciHigh80;

  _TrendPainter({
    required this.values,
    this.forecastT1,
    this.ciLow80,
    this.ciHigh80,
  });

  @override
  void paint(Canvas canvas, Size size) {
    if (values.length < 2) return;
    final allScale = <double>[
      ...values,
      if (forecastT1 != null) forecastT1!,
      if (ciLow80 != null) ciLow80!,
      if (ciHigh80 != null) ciHigh80!,
    ];
    final minVal = allScale.reduce(math.min);
    final maxVal = allScale.reduce(math.max);
    final span = (maxVal - minVal).abs() < 1e-6 ? 1.0 : (maxVal - minVal);
    final totalSteps = forecastT1 != null ? values.length : values.length - 1;

    double yFor(double v) => size.height - (((v - minVal) / span) * (size.height - 16) + 8);

    final gridPaint = Paint()
      ..color = AppColors.line
      ..strokeWidth = 1;
    for (int i = 0; i <= 2; i++) {
      final y = size.height * (i / 2);
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    final points = <Offset>[];
    for (int i = 0; i < values.length; i++) {
      final x = (i / totalSteps) * size.width;
      points.add(Offset(x, yFor(values[i])));
    }

    final fillPath = Path()..moveTo(points.first.dx, size.height);
    for (final p in points) {
      fillPath.lineTo(p.dx, p.dy);
    }
    fillPath.lineTo(points.last.dx, size.height);
    fillPath.close();
    canvas.drawPath(
      fillPath,
      Paint()..color = AppColors.blue.withValues(alpha: 0.10),
    );

    final linePath = Path()..moveTo(points.first.dx, points.first.dy);
    for (int i = 1; i < points.length; i++) {
      linePath.lineTo(points[i].dx, points[i].dy);
    }
    canvas.drawPath(
      linePath,
      Paint()
        ..color = AppColors.blue
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );

    final dotPaint = Paint()..color = AppColors.blueDark;
    for (final p in points) {
      canvas.drawCircle(p, 3.0, dotPaint);
    }

    if (forecastT1 != null) {
      final fx = size.width;
      final fy = yFor(forecastT1!);
      if (ciLow80 != null && ciHigh80 != null) {
        final yLow = yFor(ciLow80!);
        final yHigh = yFor(ciHigh80!);
        final band = Path()
          ..moveTo(points.last.dx, points.last.dy)
          ..lineTo(fx, yHigh)
          ..lineTo(fx, yLow)
          ..close();
        canvas.drawPath(band, Paint()..color = AppColors.green.withValues(alpha: 0.18));
      }
      canvas.drawLine(
        points.last,
        Offset(fx, fy),
        Paint()
          ..color = AppColors.green
          ..strokeWidth = 2.0,
      );
      canvas.drawCircle(Offset(fx, fy), 4.5, Paint()..color = AppColors.greenDark);
    }
  }

  @override
  bool shouldRepaint(covariant _TrendPainter oldDelegate) =>
      oldDelegate.values != values ||
      oldDelegate.forecastT1 != forecastT1 ||
      oldDelegate.ciLow80 != ciLow80 ||
      oldDelegate.ciHigh80 != ciHigh80;
}
