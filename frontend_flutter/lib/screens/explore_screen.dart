import 'package:flutter/material.dart';

import '../core/fd_theme.dart';
import '../core/utils/formatters.dart';
import '../services/api_service.dart';

class ExploreScreen extends StatefulWidget {
  final ApiService apiService;
  final void Function(String prompt)? onSelectPrompt;

  const ExploreScreen({
    super.key,
    required this.apiService,
    this.onSelectPrompt,
  });

  @override
  State<ExploreScreen> createState() => _ExploreScreenState();
}

class _ExploreScreenState extends State<ExploreScreen> {
  Map<String, dynamic>? _metadata;
  List<dynamic> _forecasts = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool forceRefresh = false}) async {
    if (forceRefresh) {
      widget.apiService.invalidateMetadataCache();
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final meta = await widget.apiService.getMetadata();
      if (!mounted) return;

      final rawProducts = _asStringList(meta['products']);
      final forecasts = rawProducts.isEmpty
          ? await widget.apiService.getForecasts().catchError((_) => <dynamic>[])
          : const <dynamic>[];
      if (!mounted) return;

      setState(() {
        _metadata = meta;
        _forecasts = forecasts;
        _loading = false;
        _error = null;
      });
    } catch (_) {
      try {
        final forecasts = await widget.apiService.getForecasts();
        if (!mounted) return;
        if (forecasts.isNotEmpty) {
          setState(() {
            _metadata = const <String, dynamic>{};
            _forecasts = forecasts;
            _loading = false;
            _error = null;
          });
          return;
        }
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Les métadonnées ne sont pas accessibles pour le moment.';
      });
    }
  }

  void _triggerPrompt(String entity, bool isProduct) {
    if (widget.onSelectPrompt != null) {
      final prompt = isProduct
          ? 'Quelle est la prévision du prix et la tendance pour le produit $entity au Tchad ?'
          : 'Quelle est la situation des marchés et des prix dans la province de $entity ?';
      widget.onSelectPrompt!(prompt);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Sélection : $entity. Ouvrez l’Assistant IA pour analyser.'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final metadata = _metadata ?? const <String, dynamic>{};
    final domain = _asMap(metadata['active_domain']);

    // Extraire les listes depuis metadata
    final rawProducts = _asStringList(metadata['products']);
    final rawCereals = _asStringList(metadata['cereals']);
    final rawMarkets = _asStringList(metadata['markets']);
    final rawProvinces = _asStringList(metadata['provinces']);
    final rawSources = _asStringList(metadata['sources']);

    // Enrichir avec les observations réelles des prévisions si disponibles
    final Set<String> productsSet = Set<String>.from(rawProducts);
    final Set<String> marketsSet = Set<String>.from(rawMarkets);
    final Set<String> provincesSet = Set<String>.from(rawProvinces);
    final Set<String> sourcesSet = Set<String>.from(rawSources);

    String? minObs;
    String? maxObs;
    String? forecastMonth;

    for (final raw in _forecasts) {
      if (raw is Map) {
        final m = Map<String, dynamic>.from(raw);
        if (m['commodity'] != null) productsSet.add(m['commodity'].toString());
        if (m['commodity_std'] != null) productsSet.add(m['commodity_std'].toString());
        if (m['market_name'] != null) marketsSet.add(m['market_name'].toString());
        if (m['province'] != null) provincesSet.add(m['province'].toString());
        if (m['source'] != null) sourcesSet.add(m['source'].toString());

        final obs = m['last_observed_month']?.toString();
        if (obs != null && obs.isNotEmpty) {
          if (minObs == null || obs.compareTo(minObs) < 0) minObs = obs;
          if (maxObs == null || obs.compareTo(maxObs) > 0) maxObs = obs;
        }
        if (m['forecast_month'] != null) {
          forecastMonth = m['forecast_month'].toString();
        }
      }
    }

    final products = productsSet.toList()..sort();
    final cereals = rawCereals.isNotEmpty ? rawCereals : products;
    final markets = marketsSet.toList()..sort();
    final provinces = provincesSet.toList()..sort();
    final sources = sourcesSet.toList()..sort();

    final periods = metadata['periods_covered'] is Map
        ? Map<String, dynamic>.from(metadata['periods_covered'] as Map)
        : const {};
    final startPeriod = periods['start']?.toString() ?? minObs;
    final endPeriod = periods['end']?.toString() ?? maxObs;
    final lastUpdated = metadata['last_updated']?.toString() ?? maxObs;

    // Domaines multidomaines
    final futureDomains = [
      {'slug': 'agriculture', 'label': 'Agriculture', 'desc': 'Surfaces cultivées, rendements et intrants'},
      {'slug': 'economy', 'label': 'Économie', 'desc': 'Indices des prix, inflation et commerce transfrontalier'},
      {'slug': 'health', 'label': 'Santé', 'desc': 'Centres de santé, accès aux soins et nutrition'},
      {'slug': 'population', 'label': 'Population', 'desc': 'Démographie, mouvements et sécurité alimentaire'},
      {'slug': 'environment', 'label': 'Environnement', 'desc': 'Précipitations, stress hydrique et végétation NDVI'},
      {'slug': 'infrastructure', 'label': 'Infrastructures', 'desc': 'Réseaux routiers, marchés physiques et stockage'},
      {'slug': 'transport', 'label': 'Transport', 'desc': 'Corridors logistiques et coûts d’acheminement'},
    ];

    return Material(
      color: Colors.white,
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 36),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Explorer les données',
                  style: TextStyle(fontSize: 27, fontWeight: FontWeight.w800, color: FDTheme.ink),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Catalogue multidomaine des sources et indicateurs authentiques de FreeData.AI.',
                  style: TextStyle(color: FDTheme.muted, height: 1.45),
                ),
                const SizedBox(height: 24),
                if (_loading)
                  const FDLoadingState(message: 'Chargement du catalogue…')
                else if (_error != null)
                  FDErrorState(
                    message: _error!,
                    onRetry: () => _load(forceRefresh: true),
                  )
                else ...[
                  FDCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(Icons.storefront_outlined, color: FDTheme.blue),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                domain['label']?.toString() ?? 'Marchés et prix des produits',
                                style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 20, color: FDTheme.ink),
                              ),
                            ),
                            FDBadge(
                              label: 'OPÉRATIONNEL',
                              color: FDTheme.green,
                              backgroundColor: FDTheme.green.withValues(alpha: 0.10),
                            ),
                          ],
                        ),
                        const SizedBox(height: 10),
                        Text(
                          domain['description']?.toString() ??
                              'Premier domaine exploitable de FreeData.AI : marchés, céréales, provinces et sources authentiques (WFP, FEWS NET).',
                          style: const TextStyle(color: FDTheme.muted, height: 1.5),
                        ),
                        const SizedBox(height: 20),
                        Wrap(
                          spacing: 12,
                          runSpacing: 12,
                          children: [
                            FDMetricCard(label: 'Produits', value: '${products.length}', icon: Icons.inventory_2_outlined),
                            FDMetricCard(label: 'Céréales', value: '${cereals.length}', icon: Icons.grass_outlined),
                            FDMetricCard(label: 'Marchés', value: '${markets.length}', icon: Icons.storefront_rounded),
                            FDMetricCard(label: 'Provinces', value: '${provinces.length}', icon: Icons.location_on_outlined),
                            FDMetricCard(label: 'Sources', value: '${sources.length}', icon: Icons.source_outlined),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 18),
                  _MetadataSection(
                    title: 'Produits',
                    values: products,
                    color: FDTheme.blue,
                    labelBuilder: commodityLabelFr,
                    onTapItem: (item) => _triggerPrompt(commodityLabelFr(item), true),
                  ),
                  const SizedBox(height: 18),
                  _MetadataSection(
                    title: 'Céréales',
                    values: cereals,
                    color: FDTheme.green,
                    labelBuilder: commodityLabelFr,
                    onTapItem: (item) => _triggerPrompt(commodityLabelFr(item), true),
                  ),
                  const SizedBox(height: 18),
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final itemWidth = constraints.maxWidth < 700 ? constraints.maxWidth : (constraints.maxWidth - 16) / 2;
                      return Wrap(
                        spacing: 16,
                        runSpacing: 16,
                        children: [
                          SizedBox(
                            width: itemWidth,
                            child: _InfoPanelCard(
                              title: 'Marchés',
                              subtitle: markets.isEmpty ? 'Aucun marché référencé' : '${markets.length} marchés disponibles',
                              values: markets,
                            ),
                          ),
                          SizedBox(
                            width: itemWidth,
                            child: _InfoPanelCard(
                              title: 'Provinces',
                              subtitle: provinces.isEmpty ? 'Aucune province référencée' : '${provinces.length} provinces couvertes',
                              values: provinces,
                              onTapItem: (item) => _triggerPrompt(item, false),
                            ),
                          ),
                          SizedBox(
                            width: itemWidth,
                            child: _InfoPanelCard(
                              title: 'Sources',
                              subtitle: sources.isEmpty ? 'Aucune source disponible' : '${sources.length} sources de données',
                              values: sources,
                            ),
                          ),
                          SizedBox(
                            width: itemWidth,
                            child: _InfoPanelCard(
                              title: 'Périodes couvertes',
                              subtitle: startPeriod == null || endPeriod == null
                                  ? 'Aucune période disponible'
                                  : '$startPeriod → $endPeriod ${forecastMonth != null ? '(Prévision : $forecastMonth)' : ''}',
                              values: [
                                if (startPeriod != null) 'Début : $startPeriod',
                                if (endPeriod != null) 'Fin : $endPeriod',
                                if (forecastMonth != null) 'Horizon prévisionnel : $forecastMonth',
                              ],
                            ),
                          ),
                        ],
                      );
                    },
                  ),
                  const SizedBox(height: 18),
                  FDCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Dates de mise à jour',
                          style: TextStyle(fontWeight: FontWeight.w800, color: FDTheme.ink, fontSize: 18),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          lastUpdated != null
                              ? 'Dernière mise à jour connue : $lastUpdated'
                              : 'Aucune date de mise à jour fournie par le backend.',
                          style: const TextStyle(color: FDTheme.muted, height: 1.5),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 28),
                  const Text(
                    'Architecture Multidomaine Extensible',
                    style: TextStyle(fontSize: 19, fontWeight: FontWeight.w800, color: FDTheme.ink),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Les domaines ci-dessous constituent la feuille de route d’extension de FreeData.AI. Le raccordement de chaque pipeline est documenté de manière transparente.',
                    style: TextStyle(color: FDTheme.muted, fontSize: 13, height: 1.45),
                  ),
                  const SizedBox(height: 16),
                  Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: futureDomains.map((entry) {
                      return SizedBox(
                        width: 260,
                        child: _ComingCard(
                          icon: _domainIcon(entry['slug']!),
                          title: entry['label']!,
                          desc: entry['desc']!,
                          onTap: () {
                            showDialog(
                              context: context,
                              builder: (ctx) => AlertDialog(
                                title: Row(
                                  children: [
                                    Icon(_domainIcon(entry['slug']!), color: const Color(0xFF64748B)),
                                    const SizedBox(width: 8),
                                    Text(entry['label']!),
                                  ],
                                ),
                                content: Text(
                                  'Le domaine "${entry['label']}" est actuellement en préparation. Les pipelines d’ingestion et de normalisation des données pour le Tchad ne sont pas encore reliés à l’API.',
                                  style: const TextStyle(height: 1.5),
                                ),
                                actions: [
                                  TextButton(
                                    onPressed: () => Navigator.pop(ctx),
                                    child: const Text('Compris'),
                                  ),
                                ],
                              ),
                            );
                          },
                        ),
                      );
                    }).toList(),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Map<String, dynamic> _asMap(dynamic value) {
    if (value is Map) {
      return Map<String, dynamic>.from(value);
    }
    return const <String, dynamic>{};
  }

  List<String> _asStringList(dynamic value) {
    if (value is List) {
      return value.map((item) => item?.toString() ?? '').where((item) => item.isNotEmpty).toList();
    }
    return const <String>[];
  }

  IconData _domainIcon(String slug) {
    switch (slug) {
      case 'agriculture':
        return Icons.eco_outlined;
      case 'economy':
        return Icons.trending_up_rounded;
      case 'health':
        return Icons.medical_services_outlined;
      case 'population':
        return Icons.groups_outlined;
      case 'environment':
        return Icons.park_outlined;
      case 'infrastructure':
        return Icons.construction_outlined;
      case 'transport':
        return Icons.route_outlined;
      default:
        return Icons.pending_outlined;
    }
  }
}

class _MetadataSection extends StatelessWidget {
  final String title;
  final List<String> values;
  final Color color;
  final String Function(String)? labelBuilder;
  final ValueChanged<String>? onTapItem;

  const _MetadataSection({
    required this.title,
    required this.values,
    required this.color,
    this.labelBuilder,
    this.onTapItem,
  });

  @override
  Widget build(BuildContext context) {
    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(fontWeight: FontWeight.w800, color: FDTheme.ink, fontSize: 18),
          ),
          const SizedBox(height: 12),
          if (values.isEmpty)
            const Text('Aucune valeur disponible dans les métadonnées backend.', style: TextStyle(color: FDTheme.muted))
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: values
                  .map(
                    (value) => _Pill(
                      text: labelBuilder != null ? labelBuilder!(value) : value,
                      color: color,
                      onTap: onTapItem != null ? () => onTapItem!(value) : null,
                    ),
                  )
                  .toList(),
            ),
        ],
      ),
    );
  }
}

class _InfoPanelCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final List<String> values;
  final ValueChanged<String>? onTapItem;

  const _InfoPanelCard({
    required this.title,
    required this.subtitle,
    required this.values,
    this.onTapItem,
  });

  @override
  Widget build(BuildContext context) {
    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w800, color: FDTheme.ink, fontSize: 17)),
          const SizedBox(height: 6),
          Text(subtitle, style: const TextStyle(color: FDTheme.muted, fontSize: 12)),
          const SizedBox(height: 12),
          if (values.isEmpty)
            const Text('Aucune donnée liée à ce critère.', style: TextStyle(color: FDTheme.muted, fontSize: 12))
          else
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: values
                  .take(12)
                  .map(
                    (value) => _Pill(
                      text: value,
                      color: FDTheme.blue,
                      onTap: onTapItem != null ? () => onTapItem!(value) : null,
                    ),
                  )
                  .toList(),
            ),
        ],
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  final String text;
  final Color color;
  final VoidCallback? onTap;

  const _Pill({required this.text, required this.color, this.onTap});

  @override
  Widget build(BuildContext context) {
    final pillContent = Padding(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
      child: Text(
        text,
        style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12),
      ),
    );

    if (onTap == null) {
      return Container(
        decoration: BoxDecoration(
          color: color.withValues(alpha: .09),
          borderRadius: BorderRadius.circular(30),
          border: Border.all(color: color.withValues(alpha: .18)),
        ),
        child: pillContent,
      );
    }

    return Semantics(
      button: true,
      label: text,
      child: Material(
        color: color.withValues(alpha: .09),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(30),
          side: BorderSide(color: color.withValues(alpha: .18)),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(30),
          onTap: onTap,
          child: pillContent,
        ),
      ),
    );
  }
}

class _ComingCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String desc;
  final VoidCallback? onTap;

  const _ComingCard({
    required this.icon,
    required this.title,
    required this.desc,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final content = Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: FDTheme.muted),
              const Spacer(),
              FDBadge(
                label: 'En préparation',
                color: const Color(0xFF64748B),
                backgroundColor: const Color(0xFFF1F5F9),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(title, style: const TextStyle(fontWeight: FontWeight.w700, color: FDTheme.ink)),
          const SizedBox(height: 5),
          Text(desc, style: const TextStyle(fontSize: 12, color: FDTheme.muted, height: 1.4)),
        ],
      ),
    );

    return FDCard(
      padding: EdgeInsets.zero,
      child: Semantics(
        button: onTap != null,
        label: title,
        child: Material(
          color: Colors.transparent,
          borderRadius: BorderRadius.circular(18),
          child: InkWell(
            borderRadius: BorderRadius.circular(18),
            onTap: onTap,
            child: content,
          ),
        ),
      ),
    );
  }
}
