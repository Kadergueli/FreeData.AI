import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import 'analytics_screen.dart';
import 'campaign_plan_screen.dart';
import 'farm_operating_account_screen.dart';
import 'forecast_screen.dart';
import 'passport_screen.dart';

/// Hub unifié Marchés & Crédit :
/// Regroupe Prévisions, Credit Passport et (en PRO) Analytics PRO.
class MarketsHubScreen extends StatefulWidget {
  final ApiService apiService;
  final void Function(String prompt)? onSelectPrompt;
  final VoidCallback? onRequestPro;

  const MarketsHubScreen({
    super.key,
    required this.apiService,
    this.onSelectPrompt,
    this.onRequestPro,
  });

  @override
  State<MarketsHubScreen> createState() => _MarketsHubScreenState();
}

class _MarketsHubScreenState extends State<MarketsHubScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 5, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isPro = widget.apiService.hasPremiumKey;

    return Container(
      color: AppColors.canvas,
      child: Column(
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            decoration: const BoxDecoration(
              color: Colors.white,
              border: Border(
                bottom: BorderSide(color: AppColors.line, width: 1),
              ),
            ),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1040),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          width: 34,
                          height: 34,
                          decoration: BoxDecoration(
                            color: AppColors.blueSoft,
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: const Icon(
                            Icons.show_chart_rounded,
                            color: AppColors.blue,
                            size: 20,
                          ),
                        ),
                        const SizedBox(width: 10),
                        const Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Marchés & Crédit',
                                style: TextStyle(
                                  fontSize: 16.5,
                                  fontWeight: FontWeight.w800,
                                  color: AppColors.ink,
                                ),
                              ),
                              Text(
                                'Prévisions de prix, scoring risque crédit et analytique avancée',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: AppColors.muted,
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (isPro)
                          const FDBadge(
                            label: 'ANALYTICS PRO',
                            color: AppColors.blue,
                            backgroundColor: AppColors.blueSoft,
                          ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    TabBar(
                      controller: _tabController,
                      isScrollable: true,
                      tabAlignment: TabAlignment.start,
                      labelColor: AppColors.blue,
                      unselectedLabelColor: AppColors.muted,
                      indicatorColor: AppColors.blue,
                      labelStyle: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 13.5,
                      ),
                      tabs: [
                        const Tab(
                          icon: Icon(Icons.show_chart_rounded, size: 18),
                          text: 'Prévisions',
                        ),
                        const Tab(
                          icon: Icon(Icons.calculate_outlined, size: 18),
                          text: 'Plan Campagne',
                        ),
                        const Tab(
                          icon: Icon(Icons.assessment_outlined, size: 18),
                          text: 'Exploitation',
                        ),
                        const Tab(
                          icon: Icon(Icons.shield_outlined, size: 18),
                          text: 'Credit Passport',
                        ),
                        Tab(
                          icon: Icon(
                            isPro
                                ? Icons.analytics_outlined
                                : Icons.lock_outline_rounded,
                            size: 18,
                          ),
                          text: isPro ? 'Analytics PRO' : 'Analytics (PRO)',
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                ForecastScreen(
                  apiService: widget.apiService,
                  onSelectPrompt: widget.onSelectPrompt,
                ),
                CampaignPlanScreen(
                  apiService: widget.apiService,
                  onSelectPrompt: widget.onSelectPrompt,
                ),
                FarmOperatingAccountScreen(
                  apiService: widget.apiService,
                  onSelectPrompt: widget.onSelectPrompt,
                ),
                PassportScreen(
                  apiService: widget.apiService,
                  onSelectPrompt: widget.onSelectPrompt,
                ),
                if (isPro)
                  AnalyticsScreen(apiService: widget.apiService)
                else
                  _ProLockView(
                    title: 'Analytics PRO — Analytique & Benchmarks ML',
                    description:
                        'Débloquez les courbes de tendance multi-provinces, l’analyse de volatilité, les benchmarks 70/30 et le profilage de marché complet.',
                    onUnlock: widget.onRequestPro,
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ProLockView extends StatelessWidget {
  final String title;
  final String description;
  final VoidCallback? onUnlock;

  const _ProLockView({
    required this.title,
    required this.description,
    this.onUnlock,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: FDCard(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const FDBadge(
                  label: 'FONCTIONNALITÉ PRO',
                  color: AppColors.blue,
                  backgroundColor: AppColors.blueSoft,
                ),
                const SizedBox(height: 12),
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: AppColors.ink,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  description,
                  style: const TextStyle(
                    fontSize: 13.5,
                    color: AppColors.muted,
                    height: 1.45,
                  ),
                ),
                if (onUnlock != null) ...[
                  const SizedBox(height: 16),
                  FDPrimaryButton(
                    label: 'Activer l’accès PRO',
                    icon: Icons.workspace_premium_outlined,
                    onPressed: onUnlock,
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
