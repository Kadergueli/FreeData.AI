import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
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
      backgroundColor: AppColors.canvas,
      appBar: AppBar(title: const Text('Abonnement & Quotas', style: TextStyle(fontWeight: FontWeight.w700))),
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
                    FDCard(
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Plan actif : ${sub['effective_plan_id'] ?? 'free'} (${sub['status'] ?? 'active'})',
                                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  sub['current_period_end'] != null
                                      ? 'Échéance : ${sub['current_period_end']}'
                                      : 'Activation par clé partenaire pour l\'accès PRO.',
                                  style: const TextStyle(fontSize: 13, color: AppColors.muted),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 12),
                          FDPrimaryButton(
                            label: 'Clé PRO',
                            icon: Icons.vpn_key_outlined,
                            onPressed: widget.onConfigureKey,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    const Text(
                      'Utilisation & Quotas restants',
                      style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                    ),
                    const SizedBox(height: 8),
                    ...quotas.entries.map((e) {
                      final q = e.value as Map;
                      final used = (q['used'] as num?)?.toInt() ?? 0;
                      final limit = (q['limit'] as num?)?.toInt() ?? 0;
                      final pct = limit > 0 ? (used / limit).clamp(0.0, 1.0) : 0.0;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: FDCard(
                          padding: const EdgeInsets.all(14),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(e.key, style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.ink)),
                                  Text('$used / $limit', style: const TextStyle(fontWeight: FontWeight.w700, color: AppColors.blue)),
                                ],
                              ),
                              const SizedBox(height: 8),
                              ClipRRect(
                                borderRadius: BorderRadius.circular(99),
                                child: LinearProgressIndicator(
                                  value: pct,
                                  minHeight: 7,
                                  backgroundColor: AppColors.canvasSoft,
                                  color: pct > 0.85 ? AppColors.warning : AppColors.blue,
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    }),
                    const SizedBox(height: 10),
                    const Text(
                      'Plans disponibles (quotas appliqués côté serveur)',
                      style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                    ),
                    const SizedBox(height: 8),
                    ..._plans.map(
                      (p) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: FDCard(
                          padding: const EdgeInsets.all(14),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${p['label']} (${p['plan_id']})',
                                style: const TextStyle(fontWeight: FontWeight.w700, color: AppColors.ink),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                'Chat/jour : ${p['daily_chat_limit']} · PDF/mois : ${p['monthly_pdf_limit']} · ML/jour : ${p['daily_ml_limit']} · Projets max : ${p['max_projects']}',
                                style: const TextStyle(fontSize: 13, color: AppColors.muted),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
    );
  }
}

