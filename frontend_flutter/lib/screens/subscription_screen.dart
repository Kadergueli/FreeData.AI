import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../services/api_service.dart';

class SubscriptionScreen extends StatefulWidget {
  final ApiService apiService;
  final VoidCallback? onConfigureKey;

  const SubscriptionScreen({super.key, required this.apiService, this.onConfigureKey});

  @override
  State<SubscriptionScreen> createState() => _SubscriptionScreenState();
}

class _SubscriptionScreenState extends State<SubscriptionScreen> {
  Map<String, dynamic>? _me;
  List<Map<String, dynamic>> _plans = [];
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
      final res = await Future.wait([
        widget.apiService.getMyBilling(),
        widget.apiService.getBillingPlans(),
      ]);
      if (!mounted) return;
      setState(() {
        _me = res[0];
        _plans = ((res[1]['plans'] as List?) ?? []).cast<Map<String, dynamic>>();
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
    final sub = _me?['subscription'] as Map? ?? {};
    final quotas = _me?['quotas'] as Map? ?? {};

    return Scaffold(
      appBar: AppBar(title: const Text('Abonnement & Quotas')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!, style: const TextStyle(color: FDTheme.danger)))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Card(
                      child: ListTile(
                        title: Text(
                          'Plan actif : ${sub['effective_plan_id'] ?? 'free'} (${sub['status'] ?? 'active'})',
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        subtitle: Text(
                          sub['current_period_end'] != null
                              ? 'Échéance : ${sub['current_period_end']}'
                              : 'Activation manuelle ou clé partenaire requise pour PRO.',
                        ),
                        trailing: ElevatedButton(
                          onPressed: widget.onConfigureKey,
                          child: const Text('Clé PRO'),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    const Text('Utilisation & Quotas restants', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 6),
                    ...quotas.entries.map((e) {
                      final q = e.value as Map;
                      final used = (q['used'] as num?)?.toInt() ?? 0;
                      final limit = (q['limit'] as num?)?.toInt() ?? 0;
                      final pct = limit > 0 ? (used / limit).clamp(0.0, 1.0) : 0.0;
                      return Card(
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('${e.key} : $used / $limit', style: const TextStyle(fontWeight: FontWeight.w600)),
                              const SizedBox(height: 6),
                              LinearProgressIndicator(value: pct),
                            ],
                          ),
                        ),
                      );
                    }),
                    const SizedBox(height: 12),
                    const Text('Plans disponibles (quotas appliqués côté serveur)', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 6),
                    ..._plans.map((p) => Card(
                          child: ListTile(
                            title: Text('${p['label']} (${p['plan_id']})', style: const TextStyle(fontWeight: FontWeight.w600)),
                            subtitle: Text(
                              'Chat/jour : ${p['daily_chat_limit']} · PDF/mois : ${p['monthly_pdf_limit']} · ML/jour : ${p['daily_ml_limit']} · Projets max : ${p['max_projects']}',
                            ),
                          ),
                        )),
                  ],
                ),
    );
  }
}

