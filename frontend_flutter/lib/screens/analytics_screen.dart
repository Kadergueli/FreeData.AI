import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../services/api_service.dart';

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

  @override
  Widget build(BuildContext context) {
    final stats = (_summary?['descriptive'] as Map?)?['stats'] as Map?;
    final volatileList = (_summary?['most_volatile_commodities'] as List? ?? []).cast<Map>();
    final provinces = (_regional?['provinces'] as List? ?? []).cast<Map>();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Analytics & Intelligence Marchés'),
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
              ? Center(child: Text(_error!, style: const TextStyle(color: FDTheme.danger)))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    if (_profile != null)
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Text(
                            'Qualité & Couverture : ${_profile!['forecast_rows']} séries · ${_profile!['provinces_count']} provinces · ${_profile!['commodities_count']} produits · Dernier mois : ${_profile!['latest_observed_month'] ?? '—'}',
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                        ),
                      ),
                    if (stats != null) ...[
                      const SizedBox(height: 12),
                      Card(
                        child: ListTile(
                          title: const Text('Statistiques descriptives (XAF/kg)', style: TextStyle(fontWeight: FontWeight.bold)),
                          subtitle: Text(
                            'Médiane : ${stats['median']} · Moyenne : ${stats['mean']} · Min–Max : ${stats['min']}–${stats['max']} · CV : ${stats['cv_pct']} %',
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(height: 12),
                    const Text('Comparaison Provinciale (XAF/kg)', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 6),
                    ...provinces.take(8).map((p) => ListTile(
                          dense: true,
                          title: Text(p['province'].toString()),
                          subtitle: Text('Marchés suivis : ${p['markets_count']} · Prévu t+1 : ${p['median_forecast_t1_xaf_kg'] ?? '—'} XAF/kg'),
                          trailing: Text(
                            '${p['median_observed_xaf_kg'] ?? '—'} XAF/kg',
                            style: const TextStyle(fontWeight: FontWeight.bold, color: FDTheme.blue),
                          ),
                        )),
                    const SizedBox(height: 12),
                    const Text('Produits les plus volatils (CV %)', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 6),
                    ...volatileList.take(5).map((v) => ListTile(
                          dense: true,
                          title: Text(v['commodity'].toString()),
                          trailing: Text('${v['avg_cv_pct']} %', style: const TextStyle(fontWeight: FontWeight.w600)),
                        )),
                  ],
                ),
    );
  }
}

