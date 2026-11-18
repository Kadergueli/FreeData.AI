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
  String? _selectedCommodity;
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
      final results = await Future.wait([
        widget.apiService.getAnalyticsProfile(),
        widget.apiService.getAnalyticsSummary(commodity: _selectedCommodity),
        widget.apiService.getRegionalComparison(commodity: _selectedCommodity),
      ]);
      if (!mounted) return;
      setState(() {
        _profile = results[0];
        _summary = results[1];
        _regional = results[2];
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
        title: const Text('Analytics & Intelligence Marchés', style: TextStyle(fontWeight: FontWeight.w700)),
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
                  ],
                ),
    );
  }
}
