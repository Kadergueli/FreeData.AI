import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import 'agriculture_screen.dart';
import 'agronomist_pro_screen.dart';
import 'market_pro_screen.dart';

/// Espace dédié Agro PRO (séparé d'Analytics PRO).
/// Regroupe les 3 piliers agricoles PRO :
/// 1. Agronome PRO (diagnostic de terrain + PDF co-brandé + comparaison)
/// 2. Marché & Arbitrage PRO (prévisions 4 cultures + arbitrage spatial + Credit Passport Agro + watchlists + CSV)
/// 3. Zones & Climat (12 pôles NASA POWER Agro + World Bank)
class AgroProScreen extends StatefulWidget {
  final ApiService apiService;
  final void Function(String prompt)? onAskAssistant;

  const AgroProScreen({
    super.key,
    required this.apiService,
    this.onAskAssistant,
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
                constraints: const BoxConstraints(maxWidth: 960),
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
                              width: 36,
                              height: 36,
                              decoration: BoxDecoration(
                                color: AppColors.greenSoft,
                                borderRadius: BorderRadius.circular(10),
                              ),
                              child: const Icon(
                                Icons.agriculture_rounded,
                                color: AppColors.greenDark,
                                size: 20,
                              ),
                            ),
                            const SizedBox(width: 10),
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text(
                                  'Agro PRO',
                                  style: TextStyle(
                                    fontSize: 17,
                                    fontWeight: FontWeight.w800,
                                    color: AppColors.ink,
                                  ),
                                ),
                                Text(
                                  displayName.isNotEmpty
                                      ? 'Espace terrain, arbitrage & crédit · $displayName'
                                      : 'Espace terrain, arbitrage & crédit agricole',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: AppColors.muted,
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                        const FDBadge(
                          label: 'AGRO PRO ACTIF',
                          color: AppColors.greenDark,
                          backgroundColor: AppColors.greenSoft,
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
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
                      tabs: const [
                        Tab(
                          icon: Icon(Icons.science_outlined, size: 18),
                          text: 'Agronome PRO',
                        ),
                        Tab(
                          icon: Icon(Icons.trending_up_rounded, size: 18),
                          text: 'Marché & Crédit Agro',
                        ),
                        Tab(
                          icon: Icon(Icons.water_drop_outlined, size: 18),
                          text: 'Zones & Climat (12 pôles)',
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
                AgronomistProScreen(
                  apiService: widget.apiService,
                  embedded: true,
                ),
                MarketProScreen(
                  apiService: widget.apiService,
                  embedded: true,
                ),
                AgricultureScreen(
                  apiService: widget.apiService,
                  onAskAssistant: widget.onAskAssistant,
                  embedded: true,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

