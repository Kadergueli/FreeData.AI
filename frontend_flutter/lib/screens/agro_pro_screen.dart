import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import 'agriculture_screen.dart';
import 'agronomist_pro_screen.dart';
import 'market_pro_screen.dart';

/// Hub unifié Agriculture & Agro PRO :
/// 1. Zones & Climat (12 pôles NASA POWER Agro + World Bank) — ouvert à tous
/// 2. Agronome PRO (diagnostic de terrain + PDF co-brandé) — PRO
/// 3. Marché & Crédit Agro (prévisions 4 cultures + arbitrage spatial + Credit Passport Agro + watchlists + CSV) — PRO
class AgroProScreen extends StatefulWidget {
  final ApiService apiService;
  final void Function(String prompt)? onAskAssistant;
  final VoidCallback? onRequestPro;

  const AgroProScreen({
    super.key,
    required this.apiService,
    this.onAskAssistant,
    this.onRequestPro,
  });

  @override
  State<AgroProScreen> createState() => _AgroProScreenState();
}

class _AgroProScreenState extends State<AgroProScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isPro = widget.apiService.hasPremiumKey;
    final displayName =
        widget.apiService.authUser?['display_name']?.toString().trim() ?? '';

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
                    Wrap(
                      spacing: 10,
                      runSpacing: 8,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      alignment: WrapAlignment.spaceBetween,
                      children: [
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Container(
                              width: 34,
                              height: 34,
                              decoration: BoxDecoration(
                                color: AppColors.greenSoft,
                                borderRadius: BorderRadius.circular(10),
                              ),
                              child: const Icon(
                                Icons.eco_outlined,
                                color: AppColors.greenDark,
                                size: 20,
                              ),
                            ),
                            const SizedBox(width: 10),
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  isPro ? 'Agriculture · Agro PRO' : 'Agriculture',
                                  style: const TextStyle(
                                    fontSize: 16.5,
                                    fontWeight: FontWeight.w800,
                                    color: AppColors.ink,
                                  ),
                                ),
                                Text(
                                  isPro && displayName.isNotEmpty
                                      ? 'Zones, diagnostic terrain, arbitrage & crédit · $displayName'
                                      : 'Pré-diagnostic agro-climatique (12 pôles), terrain & crédit agricole',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: AppColors.muted,
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                        FDBadge(
                          label: isPro ? 'AGRO PRO ACTIF' : 'DONNÉES OUVERTES + PRO',
                          color: AppColors.greenDark,
                          backgroundColor: AppColors.greenSoft,
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    TabBar(
                      controller: _tabController,
                      isScrollable: true,
                      tabAlignment: TabAlignment.start,
                      labelColor: AppColors.greenDark,
                      unselectedLabelColor: AppColors.muted,
                      indicatorColor: AppColors.greenDark,
                      labelStyle: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 13.5,
                      ),
                      tabs: [
                        const Tab(
                          icon: Icon(Icons.water_drop_outlined, size: 18),
                          text: 'Zones & Climat (12 pôles)',
                        ),
                        Tab(
                          icon: Icon(
                            isPro
                                ? Icons.science_outlined
                                : Icons.lock_outline_rounded,
                            size: 18,
                          ),
                          text: isPro ? 'Agronome PRO' : 'Agronome (PRO)',
                        ),
                        Tab(
                          icon: Icon(
                            isPro
                                ? Icons.trending_up_rounded
                                : Icons.lock_outline_rounded,
                            size: 18,
                          ),
                          text: isPro
                              ? 'Marché & Crédit Agro'
                              : 'Marché & Crédit Agro (PRO)',
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
                AgricultureScreen(
                  apiService: widget.apiService,
                  onAskAssistant: widget.onAskAssistant,
                  embedded: true,
                ),
                AgronomistProScreen(
                  apiService: widget.apiService,
                  embedded: true,
                ),
                if (isPro)
                  MarketProScreen(
                    apiService: widget.apiService,
                    embedded: true,
                  )
                else
                  _AgroProLockCard(onUnlock: widget.onRequestPro),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AgroProLockCard extends StatelessWidget {
  final VoidCallback? onUnlock;

  const _AgroProLockCard({this.onUnlock});

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
                  label: 'AGRO PRO',
                  color: AppColors.greenDark,
                  backgroundColor: AppColors.greenSoft,
                ),
                const SizedBox(height: 12),
                const Text(
                  'Arbitrage Spatial, Watchlists & Credit Passport Agro',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: AppColors.ink,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Accédez aux prévisions ML sur les 4 cultures validées (avec MAPE), au simulateur d’arbitrage inter-provinces, aux 3 scénarios DSCR du Credit Passport Agro et à l’export CSV institutionnel.',
                  style: TextStyle(
                    fontSize: 13.5,
                    color: AppColors.muted,
                    height: 1.45,
                  ),
                ),
                if (onUnlock != null) ...[
                  const SizedBox(height: 16),
                  FDPrimaryButton(
                    label: 'Passer à Agro PRO',
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
