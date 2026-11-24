import 'package:flutter/material.dart';

import '../core/fd_theme.dart';
import '../core/utils/formatters.dart';
import '../services/api_service.dart';
import 'agriculture_screen.dart';

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
  static const int _defaultVisiblePills = 10;

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
          ? await widget.apiService
              .getForecasts()
              .catchError((_) => <dynamic>[])
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

  void _openAgriculture() {
    final ask = widget.onSelectPrompt;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (routeContext) => AgricultureScreen(
          apiService: widget.apiService,
          onAskAssistant: ask == null
              ? null
              : (prompt) {
                  Navigator.of(routeContext).pop();
                  ask(prompt);
                },
        ),
      ),
    );
  }

  void _sendPromptOrNotice(String prompt, String fallbackLabel) {
    if (widget.onSelectPrompt != null) {
      widget.onSelectPrompt!(prompt);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
              'Sélection : $fallbackLabel. Ouvrez l’Assistant IA pour analyser.'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  void _triggerPrompt(String entity, bool isProduct) {
    final prompt = isProduct
        ? 'Quelle est la prévision du prix et la tendance pour le produit $entity au Tchad ?'
        : 'Quelle est la situation des marchés et des prix dans la province de $entity ?';
    _sendPromptOrNotice(prompt, entity);
  }

  void _triggerMarketPrompt(String market) {
    _sendPromptOrNotice(
      'Quelle est la situation des prix et la prévision sur le marché de $market ?',
      market,
    );
  }

  String? _nextYearMonth(String? yearMonth) {
    if (yearMonth == null) return null;
    final match = RegExp(r'^(\d{4})-(\d{2})$').firstMatch(yearMonth.trim());
    if (match == null) return null;
    final year = int.tryParse(match.group(1)!);
    final month = int.tryParse(match.group(2)!);
    if (year == null || month == null || month < 1 || month > 12) return null;
    final nextMonth = month == 12 ? 1 : month + 1;
    final nextYear = month == 12 ? year + 1 : year;
    return '${nextYear.toString().padLeft(4, '0')}-${nextMonth.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 640;
    final metadata = _metadata ?? const <String, dynamic>{};
    final domain = _asMap(metadata['active_domain']);

    final rawProducts = _asStringList(metadata['products']);
    final rawCereals = _asStringList(metadata['cereals']);
    final rawMarkets = _asStringList(metadata['markets']);
    final rawProvinces = _asStringList(metadata['provinces']);
    final rawSources = _asStringList(metadata['sources']);

    final Set<String> productsSet = Set<String>.from(rawProducts);
    final Set<String> marketsSet = Set<String>.from(rawMarkets);
    final Set<String> provincesSet = Set<String>.from(rawProvinces);
    final Set<String> sourcesSet = Set<String>.from(rawSources);

    String? minObs;
    String? maxObs;
    String? fallbackForecastMonth;

    for (final raw in _forecasts) {
      if (raw is Map) {
        final m = Map<String, dynamic>.from(raw);
        if (m['commodity'] != null) productsSet.add(m['commodity'].toString());
        if (m['commodity_std'] != null)
          productsSet.add(m['commodity_std'].toString());
        if (m['market_name'] != null)
          marketsSet.add(m['market_name'].toString());
        if (m['province'] != null) provincesSet.add(m['province'].toString());
        if (m['source'] != null) sourcesSet.add(m['source'].toString());

        final obs = m['last_observed_month']?.toString();
        if (obs != null && obs.isNotEmpty) {
          if (minObs == null || obs.compareTo(minObs) < 0) minObs = obs;
          if (maxObs == null || obs.compareTo(maxObs) > 0) maxObs = obs;
        }
        if (m['forecast_month'] != null) {
          fallbackForecastMonth = m['forecast_month'].toString();
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
        : const <String, dynamic>{};
    final startPeriod = periods['start']?.toString() ?? minObs;
    final endPeriod = periods['end']?.toString() ?? maxObs;
    final lastUpdated =
        metadata['last_updated']?.toString() ?? maxObs ?? endPeriod;
    final forecastMonth = periods['forecast_month']?.toString() ??
        metadata['forecast_month']?.toString() ??
        fallbackForecastMonth ??
        _nextYearMonth(endPeriod);

    final futureDomains = [
      {
        'slug': 'economy',
        'label': 'Économie',
        'desc': 'Indices des prix, inflation et commerce transfrontalier'
      },
      {
        'slug': 'health',
        'label': 'Santé',
        'desc': 'Centres de santé, accès aux soins et nutrition'
      },
      {
        'slug': 'population',
        'label': 'Population',
        'desc': 'Démographie, mouvements et sécurité alimentaire'
      },
      {
        'slug': 'environment',
        'label': 'Environnement',
        'desc': 'Précipitations, stress hydrique et végétation NDVI'
      },
      {
        'slug': 'infrastructure',
        'label': 'Infrastructures',
        'desc': 'Réseaux routiers, marchés physiques et stockage'
      },
      {
        'slug': 'transport',
        'label': 'Transport',
        'desc': 'Corridors logistiques et coûts d’acheminement'
      },
    ];

    return Material(
      color: Colors.white,
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
            compact ? 14 : 24, compact ? 14 : 20, compact ? 14 : 24, 32),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Explorer les données',
                  style: TextStyle(
                    fontSize: compact ? 23 : 27,
                    fontWeight: FontWeight.w800,
                    color: FDTheme.ink,
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  'Catalogue multidomaine des sources et indicateurs authentiques de FreeData.AI.',
                  style: TextStyle(color: FDTheme.muted, height: 1.45),
                ),
                const SizedBox(height: 18),
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
                            const Icon(Icons.storefront_outlined,
                                color: FDTheme.blue),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                domain['label']?.toString() ??
                                    'Marchés et prix des produits',
                                style: const TextStyle(
                                  fontWeight: FontWeight.w800,
                                  fontSize: 19,
                                  color: FDTheme.ink,
                                ),
                              ),
                            ),
                            FDBadge(
                              label: products.isNotEmpty || markets.isNotEmpty
                                  ? 'OPÉRATIONNEL'
                                  : 'AUCUNE DONNÉE',
                              color: products.isNotEmpty || markets.isNotEmpty
                                  ? FDTheme.green
                                  : FDTheme.subtle,
                              backgroundColor:
                                  products.isNotEmpty || markets.isNotEmpty
                                      ? FDTheme.green.withValues(alpha: 0.10)
                                      : FDTheme.canvasSoft,
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          domain['description']?.toString() ??
                              'Premier domaine exploitable de FreeData.AI : marchés, produits alimentaires, provinces et sources suivies en temps réel.',
                          style: const TextStyle(
                              color: FDTheme.muted, height: 1.45),
                        ),
                        const SizedBox(height: 16),
                        Wrap(
                          spacing: 12,
                          runSpacing: 12,
                          children: [
                            FDMetricCard(
                                label: 'Produits',
                                value: '${products.length}',
                                icon: Icons.inventory_2_outlined),
                            FDMetricCard(
                                label: 'Céréales',
                                value: '${cereals.length}',
                                icon: Icons.grass_outlined),
                            FDMetricCard(
                                label: 'Marchés',
                                value: '${markets.length}',
                                icon: Icons.storefront_rounded),
                            FDMetricCard(
                                label: 'Provinces',
                                value: '${provinces.length}',
                                icon: Icons.location_on_outlined),
                            FDMetricCard(
                                label: 'Sources',
                                value: '${sources.length}',
                                icon: Icons.source_outlined),
                          ],
                        ),
                        if (products.isEmpty && markets.isEmpty) ...[
                          const SizedBox(height: 8),
                          const Text(
                            'Aucune donnée de marché exploitable n’est actuellement renvoyée par le catalogue. Réessayez plus tard.',
                            style: TextStyle(
                              fontSize: 12.5,
                              color: FDTheme.muted,
                              height: 1.4,
                            ),
                          ),
                        ],
                        const SizedBox(height: 12),
                        const Text(
                          'Périmètre : séries actives des 3 derniers mois (prévisions temps réel) · L’onglet Credit Passport couvre l’historique multi-annuel complet.',
                          style: TextStyle(
                              fontSize: 12, color: FDTheme.subtle, height: 1.4),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final twoCols = constraints.maxWidth >= 700;
                      final itemWidth = twoCols
                          ? (constraints.maxWidth - 16) / 2
                          : constraints.maxWidth;
                      return Wrap(
                        spacing: 16,
                        runSpacing: 16,
                        children: [
                          SizedBox(
                            width: itemWidth,
                            child: _MetadataSection(
                              title: 'Produits',
                              values: products,
                              color: FDTheme.blue,
                              initialLimit: _defaultVisiblePills,
                              labelBuilder: commodityLabelFr,
                              onTapItem: (item) =>
                                  _triggerPrompt(commodityLabelFr(item), true),
                            ),
                          ),
                          SizedBox(
                            width: itemWidth,
                            child: _MetadataSection(
                              title: 'Céréales',
                              values: cereals,
                              color: FDTheme.green,
                              initialLimit: _defaultVisiblePills,
                              labelBuilder: commodityLabelFr,
                              onTapItem: (item) =>
                                  _triggerPrompt(commodityLabelFr(item), true),
                            ),
                          ),
                          SizedBox(
                            width: itemWidth,
                            child: _InfoPanelCard(
                              title: 'Marchés',
                              subtitle: markets.isEmpty
                                  ? 'Aucun marché référencé'
                                  : '${markets.length} marchés disponibles',
                              values: markets,
                              initialLimit: _defaultVisiblePills,
                              onTapItem: _triggerMarketPrompt,
                            ),
                          ),
                          SizedBox(
                            width: itemWidth,
                            child: _InfoPanelCard(
                              title: 'Provinces',
                              subtitle: provinces.isEmpty
                                  ? 'Aucune province référencée'
                                  : '${provinces.length} provinces couvertes',
                              values: provinces,
                              initialLimit: _defaultVisiblePills,
                              onTapItem: (item) => _triggerPrompt(item, false),
                            ),
                          ),
                          SizedBox(
                            width: itemWidth,
                            child: _InfoPanelCard(
                              title: 'Sources',
                              subtitle: sources.isEmpty
                                  ? 'Aucune source disponible'
                                  : '${sources.length} source(s) active(s)',
                              values: sources,
                              initialLimit: _defaultVisiblePills,
                            ),
                          ),
                          SizedBox(
                            width: itemWidth,
                            child: _InfoPanelCard(
                              title: 'Périodes couvertes',
                              subtitle: startPeriod == null || endPeriod == null
                                  ? 'Aucune période disponible'
                                  : '$startPeriod → $endPeriod${forecastMonth != null ? ' (Prévision : $forecastMonth)' : ''}',
                              values: [
                                if (startPeriod != null) 'Début : $startPeriod',
                                if (endPeriod != null) 'Fin : $endPeriod',
                                if (forecastMonth != null)
                                  'Horizon prévisionnel : $forecastMonth',
                              ],
                              initialLimit: _defaultVisiblePills,
                            ),
                          ),
                        ],
                      );
                    },
                  ),
                  const SizedBox(height: 16),
                  FDCard(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 18, vertical: 14),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        const Icon(Icons.update_rounded,
                            color: FDTheme.blue, size: 20),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                'Dates de mise à jour',
                                style: TextStyle(
                                    fontWeight: FontWeight.w800,
                                    color: FDTheme.ink,
                                    fontSize: 16),
                              ),
                              const SizedBox(height: 3),
                              Text(
                                lastUpdated != null
                                    ? 'Dernier relevé actif : $lastUpdated${forecastMonth != null ? '  ·  Prochaine échéance : $forecastMonth' : ''}'
                                    : 'Aucune date de mise à jour fournie par le backend.',
                                style: const TextStyle(
                                    color: FDTheme.muted,
                                    fontSize: 13,
                                    height: 1.4),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),
                  const Text(
                    'Domaines actifs',
                    style: TextStyle(
                        fontSize: 18.5,
                        fontWeight: FontWeight.w800,
                        color: FDTheme.ink),
                  ),
                  const SizedBox(height: 10),
                  InkWell(
                    key: const ValueKey('open-agriculture-domain'),
                    borderRadius: BorderRadius.circular(18),
                    onTap: _openAgriculture,
                    child: FDCard(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 18, vertical: 16),
                      child: Row(
                        children: [
                          Container(
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: FDTheme.blueSoft,
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: const Icon(Icons.eco_outlined,
                                color: FDTheme.blue, size: 22),
                          ),
                          const SizedBox(width: 14),
                          const Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Agriculture',
                                  style: TextStyle(
                                      fontSize: 16,
                                      fontWeight: FontWeight.w800,
                                      color: FDTheme.ink),
                                ),
                                SizedBox(height: 3),
                                Text(
                                  'Pré-diagnostic agro-climatique de zone : humidité des sols et rayonnement sur 12 pôles, indicateurs agricoles nationaux.',
                                  style: TextStyle(
                                      fontSize: 13,
                                      color: FDTheme.muted,
                                      height: 1.4),
                                ),
                              ],
                            ),
                          ),
                          const Icon(Icons.chevron_right_rounded,
                              color: FDTheme.muted),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                  const Text(
                    'Architecture Multidomaine Extensible',
                    style: TextStyle(
                        fontSize: 18.5,
                        fontWeight: FontWeight.w800,
                        color: FDTheme.ink),
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Les domaines ci-dessous constituent la feuille de route d’extension de FreeData.AI. Le raccordement de chaque pipeline est documenté de manière transparente.',
                    style: TextStyle(
                        color: FDTheme.muted, fontSize: 13, height: 1.45),
                  ),
                  const SizedBox(height: 14),
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final cols = constraints.maxWidth < 560
                          ? 1
                          : (constraints.maxWidth < 980 ? 2 : 4);
                      final cardWidth =
                          (constraints.maxWidth - (cols - 1) * 12) / cols;
                      return Wrap(
                        spacing: 12,
                        runSpacing: 12,
                        children: futureDomains.map((entry) {
                          return SizedBox(
                            width: cardWidth,
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
                                        Icon(_domainIcon(entry['slug']!),
                                            color: const Color(0xFF64748B)),
                                        const SizedBox(width: 8),
                                        Flexible(child: Text(entry['label']!)),
                                      ],
                                    ),
                                    content: Text(
                                      'Le domaine « ${entry['label']} » est en cours d’intégration pour le Tchad. Vous pouvez déjà analyser vos propres documents privés dans ce domaine depuis le chat.',
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
                      );
                    },
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
      return value
          .map((item) => item?.toString() ?? '')
          .where((item) => item.isNotEmpty)
          .toList();
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

class _ExpandablePillList extends StatefulWidget {
  final List<String> values;
  final Color color;
  final int initialLimit;
  final String Function(String)? labelBuilder;
  final ValueChanged<String>? onTapItem;

  const _ExpandablePillList({
    required this.values,
    required this.color,
    this.initialLimit = 10,
    this.labelBuilder,
    this.onTapItem,
  });

  @override
  State<_ExpandablePillList> createState() => _ExpandablePillListState();
}

class _ExpandablePillListState extends State<_ExpandablePillList> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final hasOverflow = widget.values.length > widget.initialLimit;
    final visible = (_expanded || !hasOverflow)
        ? widget.values
        : widget.values.take(widget.initialLimit).toList();
    final remaining = widget.values.length - visible.length;

    return Wrap(
      spacing: 7,
      runSpacing: 7,
      children: [
        ...visible.map(
          (value) => _Pill(
            text: widget.labelBuilder != null
                ? widget.labelBuilder!(value)
                : value,
            color: widget.color,
            onTap: widget.onTapItem != null
                ? () => widget.onTapItem!(value)
                : null,
          ),
        ),
        if (hasOverflow)
          _TogglePill(
            label: _expanded ? 'Réduire' : '+$remaining autres · Voir tout',
            onTap: () => setState(() => _expanded = !_expanded),
          ),
      ],
    );
  }
}

class _MetadataSection extends StatelessWidget {
  final String title;
  final List<String> values;
  final Color color;
  final int initialLimit;
  final String Function(String)? labelBuilder;
  final ValueChanged<String>? onTapItem;

  const _MetadataSection({
    required this.title,
    required this.values,
    required this.color,
    this.initialLimit = 10,
    this.labelBuilder,
    this.onTapItem,
  });

  @override
  Widget build(BuildContext context) {
    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                title,
                style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    color: FDTheme.ink,
                    fontSize: 17.5),
              ),
              const SizedBox(width: 8),
              Text(
                '(${values.length})',
                style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: FDTheme.muted),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (values.isEmpty)
            const Text('Aucune valeur disponible dans les métadonnées backend.',
                style: TextStyle(color: FDTheme.muted))
          else
            _ExpandablePillList(
              values: values,
              color: color,
              initialLimit: initialLimit,
              labelBuilder: labelBuilder,
              onTapItem: onTapItem,
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
  final int initialLimit;
  final ValueChanged<String>? onTapItem;

  const _InfoPanelCard({
    required this.title,
    required this.subtitle,
    required this.values,
    this.initialLimit = 10,
    this.onTapItem,
  });

  @override
  Widget build(BuildContext context) {
    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  color: FDTheme.ink,
                  fontSize: 17)),
          const SizedBox(height: 4),
          Text(subtitle,
              style: const TextStyle(color: FDTheme.muted, fontSize: 12)),
          const SizedBox(height: 12),
          if (values.isEmpty)
            const Text('Aucune donnée liée à ce critère.',
                style: TextStyle(color: FDTheme.muted, fontSize: 12))
          else
            _ExpandablePillList(
              values: values,
              color: FDTheme.blue,
              initialLimit: initialLimit,
              onTapItem: onTapItem,
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
        style:
            TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12),
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

class _TogglePill extends StatelessWidget {
  final String label;
  final VoidCallback onTap;

  const _TogglePill({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: label,
      child: Material(
        color: FDTheme.canvas,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(30),
          side: const BorderSide(color: FDTheme.line),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(30),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
            child: Text(
              label,
              style: const TextStyle(
                color: FDTheme.muted,
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
          ),
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
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: FDTheme.muted, size: 20),
              const Spacer(),
              FDBadge(
                label: 'En préparation',
                color: const Color(0xFF64748B),
                backgroundColor: const Color(0xFFF1F5F9),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(title,
              style: const TextStyle(
                  fontWeight: FontWeight.w700, color: FDTheme.ink)),
          const SizedBox(height: 4),
          Text(desc,
              style: const TextStyle(
                  fontSize: 12, color: FDTheme.muted, height: 1.4)),
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
