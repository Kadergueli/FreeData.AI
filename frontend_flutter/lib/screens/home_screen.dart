import 'package:flutter/material.dart';
import '../core/fd_theme.dart';

class HomeScreen extends StatelessWidget {
  final VoidCallback onAsk, onExplore, onForecasts, onCredit;

  const HomeScreen({
    super.key,
    required this.onAsk,
    required this.onExplore,
    required this.onForecasts,
    required this.onCredit,
  });

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 720;

    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(compact ? 18 : 36, 28, compact ? 18 : 36, 40),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1120),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _Hero(onAsk: onAsk, compact: compact),
              const SizedBox(height: 28),
              const FDSectionTitle(
                title: 'Votre espace de travail',
                subtitle: 'Accédez rapidement aux outils FreeData.AI.',
              ),
              const SizedBox(height: 14),
              LayoutBuilder(
                builder: (context, constraints) {
                  final cols = constraints.maxWidth > 850 ? 3 : (constraints.maxWidth > 540 ? 2 : 1);
                  final cards = [
                    _WorkspaceCard(
                      icon: Icons.forum_outlined,
                      title: 'Assistant IA',
                      desc: 'Posez vos questions et obtenez des réponses contextualisées à partir des données disponibles.',
                      tag: 'CONVERSATION',
                      onTap: onAsk,
                    ),
                    _WorkspaceCard(
                      icon: Icons.explore_outlined,
                      title: 'Explorer les données',
                      desc: 'Découvrez les domaines, les jeux de données et leurs sources.',
                      tag: 'DONNÉES & SOURCES',
                      onTap: onExplore,
                    ),
                    _WorkspaceCard(
                      icon: Icons.show_chart_rounded,
                      title: 'Prévisions de marché',
                      desc: 'Consultez les estimations disponibles par produit et par province.',
                      tag: 'MODÈLE ANALYTIQUE',
                      onTap: onForecasts,
                    ),
                  ];

                  return GridView.count(
                    crossAxisCount: cols,
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    crossAxisSpacing: 14,
                    mainAxisSpacing: 14,
                    childAspectRatio: cols == 1 ? 1.5 : 1.35,
                    children: cards,
                  );
                },
              ),
              const SizedBox(height: 28),
              FDCard(
                padding: const EdgeInsets.all(22),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x1A0F172A),
                    blurRadius: 18,
                    offset: Offset(0, 8),
                  )
                ],
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 42,
                      height: 42,
                      decoration: BoxDecoration(
                        color: FDTheme.green.withValues(alpha: .10),
                        borderRadius: BorderRadius.circular(13),
                      ),
                      child: const Icon(Icons.account_balance_outlined, color: FDTheme.green),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'Credit Passport',
                            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: FDTheme.ink),
                          ),
                          const SizedBox(height: 5),
                          const Text(
                            'Consultez les indicateurs de risque et les recommandations disponibles pour les analyses de financement.',
                            style: TextStyle(color: FDTheme.muted, height: 1.45),
                          ),
                          const SizedBox(height: 12),
                          FDSecondaryButton(
                            label: 'Ouvrir Credit Passport',
                            icon: Icons.arrow_forward,
                            onPressed: onCredit,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              const Row(
                children: [
                  Icon(Icons.verified_outlined, size: 17, color: FDTheme.green),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Les résultats dépendent des données disponibles et de leur date de mise à jour.',
                      style: TextStyle(color: FDTheme.muted, fontSize: 12),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Hero extends StatelessWidget {
  final VoidCallback onAsk;
  final bool compact;

  const _Hero({required this.onAsk, required this.compact});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: EdgeInsets.all(compact ? 22 : 34),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(28),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFFEFF7FF), Color(0xFFF1FBF8), Color(0xFFEAF5FF)],
        ),
        border: Border.all(color: const Color(0xFFD8E7FF)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x1A1B4C9D),
            blurRadius: 22,
            offset: Offset(0, 12),
          ),
        ],
      ),
      child: Stack(
        children: [
          Positioned(
            right: 0,
            top: 0,
            child: Container(
              width: compact ? 110 : 180,
              height: compact ? 110 : 180,
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [FDTheme.blue.withValues(alpha: 0.12), FDTheme.turquoise.withValues(alpha: 0.18)],
                ),
                borderRadius: BorderRadius.circular(999),
              ),
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 42,
                    height: 42,
                    decoration: BoxDecoration(
                      color: FDTheme.blue,
                      borderRadius: BorderRadius.circular(13),
                      boxShadow: const [
                        BoxShadow(
                          color: Color(0x4D1D4ED8),
                          blurRadius: 16,
                          offset: Offset(0, 8),
                        ),
                      ],
                    ),
                    child: const Center(
                      child: Text(
                        'FD',
                        style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w900,
                          fontSize: 17,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 11),
                  const Text(
                    'FreeData.AI',
                    style: TextStyle(fontWeight: FontWeight.w800, fontSize: 17, color: FDTheme.ink),
                  ),
                  const SizedBox(width: 9),
                  FDBadge(
                    label: 'INTELLIGENCE',
                    color: FDTheme.blueDark,
                    backgroundColor: FDTheme.turquoise.withValues(alpha: .18),
                  ),
                ],
              ),
              const SizedBox(height: 28),
              Text(
                'Explorez vos données.\nObtenez des réponses.',
                style: TextStyle(
                  fontSize: compact ? 29 : 38,
                  height: 1.13,
                  fontWeight: FontWeight.w800,
                  letterSpacing: -1.1,
                  color: FDTheme.ink,
                ),
              ),
              const SizedBox(height: 12),
              const SizedBox(
                width: 650,
                child: Text(
                  'Interrogez les données disponibles, comparez les marchés et transformez les informations en analyses compréhensibles.',
                  style: TextStyle(fontSize: 15, height: 1.55, color: FDTheme.muted),
                ),
              ),
              const SizedBox(height: 22),
              FDPrimaryButton(label: 'Commencer une conversation', icon: Icons.auto_awesome, onPressed: onAsk),
            ],
          ),
        ],
      ),
    );
  }
}

class _WorkspaceCard extends StatelessWidget {
  final IconData icon;
  final String title, desc, tag;
  final VoidCallback onTap;

  const _WorkspaceCard({
    required this.icon,
    required this.title,
    required this.desc,
    required this.tag,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(20),
      onTap: onTap,
      child: FDCard(
        padding: const EdgeInsets.all(19),
        borderRadius: BorderRadius.circular(20),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0F0F172A),
            blurRadius: 16,
            offset: Offset(0, 8),
          ),
        ],
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: FDTheme.blue.withValues(alpha: .09),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(icon, color: FDTheme.blue),
                ),
                const Spacer(),
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: FDTheme.surface,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: FDTheme.line),
                  ),
                  child: const Icon(Icons.arrow_outward, color: FDTheme.muted, size: 18),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text(
              title,
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: FDTheme.ink),
            ),
            const SizedBox(height: 7),
            Expanded(
              child: Text(
                desc,
                style: const TextStyle(color: FDTheme.muted, height: 1.4, fontSize: 13),
              ),
            ),
            const SizedBox(height: 12),
            FDBadge(label: tag, color: FDTheme.blue, backgroundColor: FDTheme.blue.withValues(alpha: 0.08)),
          ],
        ),
      ),
    );
  }
}
