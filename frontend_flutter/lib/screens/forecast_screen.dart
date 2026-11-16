import 'package:flutter/material.dart';
import '../core/fd_theme.dart';
import '../core/utils/formatters.dart';
import '../services/api_service.dart';

class ForecastScreen extends StatefulWidget {
  final ApiService apiService;
  const ForecastScreen({super.key, required this.apiService});

  @override
  State<ForecastScreen> createState() => _ForecastScreenState();
}

class _ForecastScreenState extends State<ForecastScreen> {
  static const List<String> _monthsFr = [
    'Janvier',
    'Février',
    'Mars',
    'Avril',
    'Mai',
    'Juin',
    'Juillet',
    'Août',
    'Septembre',
    'Octobre',
    'Novembre',
    'Décembre',
  ];

  static const List<String> _defaultProvinces = [
    "N'Djamena",
    'Logone Occidental',
    'Moyen-Chari',
    'Ouaddaï',
    'Salamat',
    'Lac',
  ];
  static const List<String> _defaultCommodities = [
    'Millet',
    'Sorghum (red)',
    'Maize (white)',
    'Rice (imported)',
    'Groundnuts (shelled)',
    'Sesame',
  ];

  List<String> _provinces = List<String>.from(_defaultProvinces);
  List<String> _commodities = List<String>.from(_defaultCommodities);
  String? _selectedProvince = "N'Djamena";
  String? _selectedCommodity = 'Millet';
  String _activeMode = 'forecasts';
  String _anomalyFilter = 'all';
  double? _storageCostPctMonth;
  List<dynamic> _items = [];
  List<dynamic> _alerts = [];
  List<dynamic> _anomalies = [];
  Map<String, dynamic> _trackRecords = const {};
  Map<String, dynamic>? _seasonality;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _init();
  }

  @override
  void didUpdateWidget(covariant ForecastScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.apiService.hasPremiumKey &&
        (_activeMode == 'seasonality' || _activeMode == 'anomalies')) {
      setState(() => _activeMode = 'forecasts');
      _loadForecasts();
    }
  }

  Future<void> _init() async {
    try {
      final meta = await widget.apiService.getMetadata();
      final legacy = meta['legacy_fields'];
      final rawProvs = meta['provinces'] ??
          (legacy is Map ? legacy['provinces'] : null) ??
          const [];
      final rawComms = meta['products'] ??
          (legacy is Map ? legacy['commodities'] : null) ??
          meta['commodities'] ??
          const [];
      final rawTrack = meta['track_records'];
      final provs = List<String>.from(rawProvs);
      final comms = List<String>.from(rawComms);
      if (!mounted) return;
      if (provs.isNotEmpty || comms.isNotEmpty || rawTrack is Map) {
        setState(() {
          if (provs.isNotEmpty) {
            _provinces = provs;
            _selectedProvince = provs.contains("N'Djamena") ? "N'Djamena" : provs.first;
          }
          if (comms.isNotEmpty) {
            _commodities = comms;
            _selectedCommodity = comms.contains('Millet') ? 'Millet' : comms.first;
          }
          if (rawTrack is Map) {
            _trackRecords = Map<String, dynamic>.from(rawTrack);
          }
        });
      }
    } catch (_) {
      // Conservation des filtres par défaut si les métadonnées échouent.
    }
    if (mounted) {
      await _loadCurrentMode();
    }
  }

  Future<void> _loadCurrentMode() async {
    if (_activeMode == 'alerts') {
      await _loadAlerts();
    } else if (_activeMode == 'seasonality') {
      await _loadSeasonality();
    } else if (_activeMode == 'anomalies') {
      await _loadAnomalies();
    } else {
      await _loadForecasts();
    }
  }

  Future<void> _loadForecasts() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await widget.apiService.getForecasts(
        province: _selectedProvince,
        commodity: _selectedCommodity,
      );
      if (mounted) setState(() => _items = items);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Les prévisions ne sont pas accessibles pour le moment.');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadAlerts() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await widget.apiService.getAlerts(
        province: _selectedProvince,
        commodity: _selectedCommodity,
      );
      if (mounted) setState(() => _alerts = items);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Les alertes ne sont pas accessibles pour le moment.');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadAnomalies() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await widget.apiService.getAnomalies(
        province: _selectedProvince,
        commodity: _selectedCommodity,
      );
      if (mounted) setState(() => _anomalies = items);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Le radar d’anomalies n’est pas accessible pour le moment.');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadSeasonality() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final study = await widget.apiService.getSeasonalityStudy(
        commodity: _selectedCommodity ?? 'Millet',
        province: _selectedProvince,
        storageCostPctMonth: _storageCostPctMonth,
      );
      if (mounted) setState(() => _seasonality = study);
    } on ApiHttpException catch (e) {
      if (mounted) {
        if (e.statusCode == 403 || e.statusCode == 503) {
          setState(
            () => _error =
                '${e.message}\nVérifiez votre clé d’accès Partenaire via « Clé Pro » ou utilisez l’Assistant IA.',
          );
        } else {
          setState(() => _error = e.message);
        }
      }
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'L’étude saisonnière n’est pas accessible pour le moment.');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _formatMonthList(dynamic rawMonths) {
    if (rawMonths is! List || rawMonths.isEmpty) return 'Non précisé';
    final names = <String>[];
    for (final m in rawMonths) {
      final idx = parseNum(m)?.toInt();
      if (idx != null && idx >= 1 && idx <= 12) {
        names.add(_monthsFr[idx - 1]);
      } else if (m != null) {
        names.add(m.toString());
      }
    }
    return names.isEmpty ? 'Non précisé' : names.join(', ');
  }

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 640;
    final hasPro = widget.apiService.hasPremiumKey;
    final effectiveMode = (!hasPro && (_activeMode == 'seasonality' || _activeMode == 'anomalies'))
        ? 'forecasts'
        : _activeMode;
    final trackRecord = hasPro ? _resolveTrackRecord(_selectedCommodity) : null;

    return SingleChildScrollView(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 14 : 24,
        vertical: compact ? 14 : 20,
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1080),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              FDCard(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        key: ValueKey(_selectedProvince),
                        initialValue: _selectedProvince,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Province',
                          isDense: true,
                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                        ),
                        items: _provinces
                            .map((p) => DropdownMenuItem(
                                  value: p,
                                  child: Text(p, maxLines: 1, overflow: TextOverflow.ellipsis),
                                ))
                            .toList(),
                        onChanged: (v) {
                          setState(() => _selectedProvince = v);
                          _loadCurrentMode();
                        },
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        key: ValueKey(_selectedCommodity),
                        initialValue: _selectedCommodity,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Produit',
                          isDense: true,
                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                        ),
                        items: _commodities
                            .map((c) => DropdownMenuItem(
                                  value: c,
                                  child: Text(
                                    commodityLabelFr(c),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ))
                            .toList(),
                        onChanged: (v) {
                          setState(() => _selectedCommodity = v);
                          _loadCurrentMode();
                        },
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    ChoiceChip(
                      avatar: Icon(
                        Icons.show_chart_rounded,
                        size: 16,
                        color: effectiveMode == 'forecasts' ? FDTheme.blue : FDTheme.subtle,
                      ),
                      label: const Text('Séries prévues'),
                      selected: effectiveMode == 'forecasts',
                      selectedColor: FDTheme.blueSoft,
                      labelStyle: TextStyle(
                        color: effectiveMode == 'forecasts' ? FDTheme.blue : FDTheme.body,
                        fontWeight: FontWeight.w600,
                      ),
                      onSelected: (_) {
                        if (_activeMode == 'forecasts') return;
                        setState(() => _activeMode = 'forecasts');
                        _loadCurrentMode();
                      },
                    ),
                    const SizedBox(width: 8),
                    ChoiceChip(
                      avatar: Icon(
                        Icons.warning_amber_rounded,
                        size: 16,
                        color: effectiveMode == 'alerts' ? FDTheme.danger : FDTheme.subtle,
                      ),
                      label: const Text('Alertes (>15%)'),
                      selected: effectiveMode == 'alerts',
                      selectedColor: FDTheme.dangerSoft,
                      labelStyle: TextStyle(
                        color: effectiveMode == 'alerts' ? FDTheme.danger : FDTheme.body,
                        fontWeight: FontWeight.w600,
                      ),
                      onSelected: (_) {
                        if (_activeMode == 'alerts') return;
                        setState(() => _activeMode = 'alerts');
                        _loadCurrentMode();
                      },
                    ),
                      if (hasPro) ...[
                        const SizedBox(width: 8),
                        ChoiceChip(
                          avatar: Icon(
                            Icons.calendar_month_outlined,
                            size: 16,
                            color: effectiveMode == 'seasonality' ? FDTheme.green : FDTheme.subtle,
                          ),
                          label: const Text('Saisonnalité & Stockage'),
                          selected: effectiveMode == 'seasonality',
                          selectedColor: FDTheme.greenSoft,
                          labelStyle: TextStyle(
                            color: effectiveMode == 'seasonality' ? FDTheme.greenDark : FDTheme.body,
                            fontWeight: FontWeight.w600,
                          ),
                          onSelected: (_) {
                            if (_activeMode == 'seasonality') return;
                            setState(() => _activeMode = 'seasonality');
                            _loadCurrentMode();
                          },
                        ),
                        const SizedBox(width: 8),
                        ChoiceChip(
                          avatar: Icon(
                            Icons.radar_rounded,
                            size: 16,
                            color: effectiveMode == 'anomalies' ? FDTheme.warningDark : FDTheme.subtle,
                          ),
                          label: const Text('Anomalies & Qualité'),
                          selected: effectiveMode == 'anomalies',
                          selectedColor: FDTheme.warning.withValues(alpha: 0.14),
                          labelStyle: TextStyle(
                            color: effectiveMode == 'anomalies' ? FDTheme.warningDark : FDTheme.body,
                            fontWeight: FontWeight.w600,
                          ),
                          onSelected: (_) {
                            if (_activeMode == 'anomalies') return;
                            setState(() => _activeMode = 'anomalies');
                            _loadCurrentMode();
                          },
                        ),
                      ],
                  ],
                ),
              ),
              if (trackRecord != null &&
                  (effectiveMode == 'forecasts' || effectiveMode == 'seasonality')) ...[
                const SizedBox(height: 12),
                _TrackRecordBanner(
                  commodityLabel: commodityLabelFr(_selectedCommodity ?? 'Millet'),
                  trackRecord: trackRecord,
                ),
              ],
              const SizedBox(height: 14),
              if (_loading)
                const Padding(
                  padding: EdgeInsets.all(40),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (_error != null)
                _StateMessage(text: _error!, onRetry: _loadCurrentMode)
              else if (effectiveMode == 'alerts')
                ..._buildAlertsSection()
              else if (effectiveMode == 'seasonality')
                ..._buildSeasonalitySection()
              else if (effectiveMode == 'anomalies')
                ..._buildAnomaliesSection()
              else if (_items.isEmpty)
                const _StateMessage(text: 'Aucune prévision disponible pour ces filtres.')
              else ...[
                Text(
                  '${_items.length} résultat(s)',
                  style: const TextStyle(
                    color: FDTheme.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 10),
                ..._items.map((raw) {
                  final r = Map<String, dynamic>.from(raw as Map);
                  final last = parseNum(r['last_observed_price']) ?? 0;
                  final forecast = parseNum(r['forecast_t1']) ?? 0;
                  final pct = last == 0 ? 0.0 : ((forecast - last) / last) * 100;
                  final up = pct >= 0;
                  final ciLow = parseNum(r['ci_low_80']);
                  final ciHigh = parseNum(r['ci_high_80']);
                  final quality = r['forecast_quality']?.toString() ?? 'standard';

                  return Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: FDCard(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(
                                child: Text(
                                  '${r['market_name'] ?? 'Marché non précisé'}',
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: FDTheme.ink,
                                    fontSize: 15,
                                  ),
                                ),
                              ),
                              if (quality == 'reduced') ...[
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                                  decoration: BoxDecoration(
                                    color: FDTheme.warning.withValues(alpha: 0.12),
                                    borderRadius: BorderRadius.circular(30),
                                  ),
                                  child: const Text(
                                    'Confiance réduite',
                                    style: TextStyle(
                                      color: FDTheme.warningDark,
                                      fontWeight: FontWeight.w700,
                                      fontSize: 11,
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 6),
                              ],
                              _ChangeBadge(
                                text: '${up ? '+' : ''}${pct.toStringAsFixed(1)}%',
                                positive: !up,
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),
                          Wrap(
                            spacing: 24,
                            runSpacing: 10,
                            children: [
                              _PriceValue(
                                label: 'Dernier prix observé',
                                value: '${formatXaf(last)} XAF/kg',
                              ),
                              _PriceValue(
                                label: 'Prévision ${r['forecast_month'] ?? ''}',
                                value: '${formatXaf(forecast)} XAF/kg',
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          Text(
                            'Source : ${r['source'] ?? 'Non précisée'}  •  Dernière observation : ${r['last_observed_month'] ?? '—'}',
                            style: const TextStyle(color: FDTheme.muted, fontSize: 11.5),
                          ),
                          if (ciLow != null && ciHigh != null) ...[
                            const SizedBox(height: 3),
                            Text(
                              'Intervalle indicatif 80 % : ${formatXaf(ciLow)} – ${formatXaf(ciHigh)} XAF/kg',
                              style: const TextStyle(color: FDTheme.muted, fontSize: 11.5),
                            ),
                          ],
                        ],
                      ),
                    ),
                  );
                }),
              ],
              const SizedBox(height: 12),
              Text(
                effectiveMode == 'alerts'
                    ? 'Alerte déclenchée lorsque l’écart observé dépasse le seuil de tension par rapport au prix attendu.'
                    : (effectiveMode == 'seasonality'
                        ? 'Étude fondée sur les écarts saisonniers historiques (hors frais de transport et pertes).'
                        : (effectiveMode == 'anomalies'
                            ? 'Signaux statistiques à vérifier sur le terrain avant engagement commercial ou décision de financement.'
                            : 'Une prévision est une estimation issue du modèle, et non un prix observé ou garanti.')),
                style: const TextStyle(color: FDTheme.muted, fontSize: 11.5),
              ),
            ],
          ),
        ),
      ),
    );
  }

  List<Widget> _buildAlertsSection() {
    if (_alerts.isEmpty) {
      return [
        const _StateMessage(text: 'Aucune alerte active (>15 %) pour ces filtres.'),
      ];
    }
    return [
      Text(
        '${_alerts.length} alerte(s) active(s)',
        style: const TextStyle(
          color: FDTheme.muted,
          fontSize: 12,
          fontWeight: FontWeight.w600,
        ),
      ),
      const SizedBox(height: 10),
      ..._alerts.map((raw) {
        final r = Map<String, dynamic>.from(raw as Map);
        final observed = parseNum(r['value'] ?? r['last_observed_price']) ?? 0;
        final expected = parseNum(r['predicted_price']) ?? 0;
        final dev = parseNum(r['deviation_pct']) ?? 0;
        final commRaw = r['commodity_std']?.toString() ?? '';

        return Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: FDCard(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        '${r['market_name'] ?? 'Marché'} (${r['province'] ?? '—'})',
                        style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          color: FDTheme.ink,
                          fontSize: 15,
                        ),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: FDTheme.danger.withValues(alpha: 0.10),
                        borderRadius: BorderRadius.circular(30),
                      ),
                      child: Text(
                        '+${dev.toStringAsFixed(1)}%',
                        style: const TextStyle(
                          color: FDTheme.danger,
                          fontWeight: FontWeight.w800,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  commodityLabelFr(commRaw),
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: FDTheme.blue,
                  ),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 24,
                  runSpacing: 10,
                  children: [
                    _PriceValue(
                      label: 'Prix observé',
                      value: '${formatXaf(observed)} XAF/kg',
                    ),
                    _PriceValue(
                      label: 'Prix attendu',
                      value: '${formatXaf(expected)} XAF/kg',
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  'Source : ${r['source'] ?? 'Non précisée'}  •  Mois : ${r['month'] ?? '—'}',
                  style: const TextStyle(color: FDTheme.muted, fontSize: 11.5),
                ),
              ],
            ),
          ),
        );
      }),
    ];
  }

  List<Widget> _buildSeasonalitySection() {
    final study = _seasonality;
    if (study == null || study['status'] != 'ok') {
      return [
        const _StateMessage(
          text: 'Historique insuffisant pour établir une étude saisonnière fiable pour cette sélection.',
        ),
      ];
    }

    final cal = study['calendar'] is Map
        ? Map<String, dynamic>.from(study['calendar'] as Map)
        : const <String, dynamic>{};
    final buyMonths = cal['buy_months'] ?? study['low_months'] ?? study['best_buy_months'];
    final sellMonths = cal['sell_months'] ?? study['high_months'] ?? study['best_sell_months'];
    final amplitude = parseNum(cal['amplitude_pct'] ?? study['amplitude_pct']);
    final buyDiscount = parseNum(cal['buy_discount_pct']);
    final sellPremium = parseNum(cal['sell_premium_pct']);
    final strategy = study['storage_strategy'] is Map
        ? Map<String, dynamic>.from(study['storage_strategy'] as Map)
        : const <String, dynamic>{};
    final caveats = study['caveats'] is List ? study['caveats'] as List : const <dynamic>[];
    final scope = study['scope_province']?.toString() ?? 'Toutes provinces suivies';
    final commName = commodityLabelFr(study['commodity']?.toString() ?? _selectedCommodity ?? '');

    const storageOptions = <({double? value, String label})>[
      (value: null, label: 'Sans frais (0%)'),
      (value: 1.5, label: 'Stockage 1,5%/mois'),
      (value: 3.0, label: 'Stockage 3%/mois'),
    ];

    return [
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: storageOptions.map((opt) {
          final selected = _storageCostPctMonth == opt.value;
          return ChoiceChip(
            label: Text(opt.label),
            selected: selected,
            selectedColor: FDTheme.blueSoft,
            labelStyle: TextStyle(
              fontSize: 12.5,
              color: selected ? FDTheme.blue : FDTheme.body,
              fontWeight: FontWeight.w600,
            ),
            onSelected: (_) {
              if (_storageCostPctMonth == opt.value) return;
              setState(() => _storageCostPctMonth = opt.value);
              _loadSeasonality();
            },
          );
        }).toList(),
      ),
      const SizedBox(height: 12),
      FDCard(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.calendar_month_rounded, color: FDTheme.blue, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '$commName · $scope',
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                      color: FDTheme.ink,
                    ),
                  ),
                ),
                if (amplitude != null)
                  FDBadge(
                    label: 'AMPLITUDE ${amplitude.toStringAsFixed(0)} %',
                    color: FDTheme.blueDark,
                    backgroundColor: FDTheme.blueSoft,
                  ),
              ],
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 24,
              runSpacing: 12,
              children: [
                _PriceValue(
                  label: buyDiscount != null
                      ? 'Mois favorables d’achat (${buyDiscount.toStringAsFixed(0)}%)'
                      : 'Mois favorables d’achat',
                  value: _formatMonthList(buyMonths),
                ),
                _PriceValue(
                  label: sellPremium != null
                      ? 'Mois hauts de revente (+${sellPremium.toStringAsFixed(0)}%)'
                      : 'Mois hauts de revente',
                  value: _formatMonthList(sellMonths),
                ),
              ],
            ),
            if (strategy['status'] == 'ok') ...[
              const SizedBox(height: 16),
              const Divider(height: 1, color: FDTheme.line),
              const SizedBox(height: 12),
              Text(
                'Stratégie achat au creux / vente au pic : '
                '${(parseNum(strategy['hit_rate_pct']) ?? 0).toStringAsFixed(0)} % de réussite '
                '(rendement médian ${(parseNum(strategy['median_return_pct']) ?? 0).toStringAsFixed(1)} % '
                'sur ${strategy['n_cycles'] ?? '—'} cycles)',
                style: const TextStyle(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w600,
                  color: FDTheme.inkSoft,
                  height: 1.45,
                ),
              ),
              if (strategy['net_hit_rate_pct'] != null &&
                  strategy['net_median_return_pct'] != null) ...[
                const SizedBox(height: 6),
                Text(
                  'Rendement net après frais de stockage (${(parseNum(strategy['storage_cost_pct_month']) ?? _storageCostPctMonth ?? 0).toStringAsFixed(1)} %/mois) : '
                  '${(parseNum(strategy['net_hit_rate_pct']) ?? 0).toStringAsFixed(0)} % de réussite '
                  '(médiane nette ${(parseNum(strategy['net_median_return_pct']) ?? 0).toStringAsFixed(1)} %)',
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: FDTheme.greenDark,
                    height: 1.4,
                  ),
                ),
              ],
            ],
            if (caveats.isNotEmpty) ...[
              const SizedBox(height: 12),
              ...caveats.take(3).map(
                    (c) => Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text(
                        '• $c',
                        style: const TextStyle(fontSize: 12, color: FDTheme.muted, height: 1.4),
                      ),
                    ),
                  ),
            ],
          ],
        ),
      ),
    ];
  }

  Map<String, dynamic>? _resolveTrackRecord(String? commodity) {
    if (commodity == null || _trackRecords.isEmpty) return null;
    final direct = _trackRecords[commodity];
    if (direct is Map) return Map<String, dynamic>.from(direct);
    final lower = commodity.trim().toLowerCase();
    for (final entry in _trackRecords.entries) {
      if (entry.key.toLowerCase() == lower && entry.value is Map) {
        return Map<String, dynamic>.from(entry.value as Map);
      }
    }
    return null;
  }

  List<Widget> _buildAnomaliesSection() {
    const filters = <({String id, String label})>[
      (id: 'all', label: 'Tous les signaux'),
      (id: 'arbitrage', label: 'Écarts & Arbitrage'),
      (id: 'regional', label: 'Chocs régionaux'),
      (id: 'quality', label: 'Qualité relevés'),
    ];

    final filtered = _anomalies.where((raw) {
      if (raw is! Map) return false;
      final kind = raw['kind']?.toString() ?? '';
      switch (_anomalyFilter) {
        case 'arbitrage':
          return kind == 'divergence' || kind == 'jump+divergence' || kind == 'jump';
        case 'regional':
          return kind == 'regional';
        case 'quality':
          return kind == 'stale' || kind == 'stopped';
        default:
          return true;
      }
    }).toList();

    return [
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: filters.map((f) {
          final selected = _anomalyFilter == f.id;
          return ChoiceChip(
            label: Text(f.label),
            selected: selected,
            selectedColor: FDTheme.blueSoft,
            labelStyle: TextStyle(
              fontSize: 12.5,
              color: selected ? FDTheme.blue : FDTheme.body,
              fontWeight: FontWeight.w600,
            ),
            onSelected: (_) {
              if (_anomalyFilter == f.id) return;
              setState(() => _anomalyFilter = f.id);
            },
          );
        }).toList(),
      ),
      const SizedBox(height: 12),
      if (filtered.isEmpty)
        const _StateMessage(
          text: 'Aucun signal d’anomalie ou de qualité détecté pour ces filtres.',
        )
      else ...[
        Text(
          '${filtered.length} signal(aux) détecté(s)',
          style: const TextStyle(
            color: FDTheme.muted,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 10),
        ...filtered.map((raw) {
          final r = Map<String, dynamic>.from(raw as Map);
          final kind = r['kind']?.toString() ?? '';
          final severity = r['severity']?.toString() ?? 'modérée';
          final isStrong = severity == 'forte';
          final isQuality = kind == 'stale' || kind == 'stopped';
          final value = parseNum(r['value'])?.toDouble() ?? 0.0;
          final reference = parseNum(r['reference'])?.toDouble() ?? 0.0;
          final changePct = parseNum(r['change_pct'])?.toDouble() ?? 0.0;
          final score = parseNum(r['score'])?.toDouble() ?? 0.0;
          final commLabel = commodityLabelFr(r['commodity_std']?.toString() ?? '');
          final kindLabel = _anomalyKindLabel(kind);
          final b2bHint = _anomalyB2bInsight(kind, changePct, score, value);

          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: FDCard(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Text(
                          '${r['market_name'] ?? 'Marché'} (${r['province'] ?? '—'})',
                          style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            color: FDTheme.ink,
                            fontSize: 15,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      FDBadge(
                        label: isStrong ? 'FORTE' : 'MODÉRÉE',
                        color: isStrong ? FDTheme.danger : FDTheme.warningDark,
                        backgroundColor: isStrong
                            ? FDTheme.dangerSoft
                            : FDTheme.warning.withValues(alpha: 0.14),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    runSpacing: 6,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(
                        '$commLabel · ${r['month'] ?? '—'}',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: FDTheme.blue,
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: FDTheme.canvasSoft,
                          borderRadius: BorderRadius.circular(99),
                          border: Border.all(color: FDTheme.line),
                        ),
                        child: Text(
                          kindLabel,
                          style: const TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: FDTheme.body,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  if (!isQuality)
                    Wrap(
                      spacing: 24,
                      runSpacing: 10,
                      children: [
                        _PriceValue(
                          label: 'Prix observé',
                          value: '${formatXaf(value)} XAF/kg',
                        ),
                        _PriceValue(
                          label: 'Référence attendue',
                          value: '${formatXaf(reference)} XAF/kg',
                        ),
                        _PriceValue(
                          label: 'Écart',
                          value: '${changePct >= 0 ? '+' : ''}${changePct.toStringAsFixed(1)} %',
                        ),
                      ],
                    )
                  else
                    _PriceValue(
                      label: kind == 'stopped'
                          ? 'Collecte interrompue'
                          : 'Série figée',
                      value: '${score.toStringAsFixed(0)} mois · ${formatXaf(value)} XAF/kg',
                    ),
                  const SizedBox(height: 10),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    decoration: BoxDecoration(
                      color: FDTheme.canvas,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: FDTheme.line),
                    ),
                    child: Text(
                      b2bHint,
                      style: const TextStyle(
                        fontSize: 12,
                        color: FDTheme.inkSoft,
                        height: 1.4,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          );
        }),
      ],
    ];
  }

  String _anomalyKindLabel(String kind) {
    switch (kind) {
      case 'divergence':
        return 'Écart inter-marchés';
      case 'jump+divergence':
        return 'Saut & Écart';
      case 'regional':
        return 'Épisode régional';
      case 'jump':
        return 'Saut brusque';
      case 'stale':
        return 'Prix figé';
      case 'stopped':
        return 'Collecte arrêtée';
      default:
        return kind;
    }
  }

  String _anomalyB2bInsight(String kind, double changePct, double score, double value) {
    switch (kind) {
      case 'stopped':
        return 'Risque décisionnel : aucun relevé depuis ${score.toStringAsFixed(0)} mois. Vérifiez la disponibilité réelle avant financement ou contrat.';
      case 'stale':
        return 'Qualité à vérifier : prix identique (${formatXaf(value)} XAF/kg) depuis ${score.toStringAsFixed(0)} mois. Ne pas engager de chiffrage sur cette seule série.';
      case 'regional':
        return 'Choc provincial coordonné : vérifiez l’état des routes, la logistique et l’offre régionale.';
      case 'divergence':
      case 'jump+divergence':
        if (changePct <= -15) {
          return 'Décote locale marquée par rapport aux marchés pairs : piste potentielle d’approvisionnement B2B (à confirmer sur place).';
        }
        if (changePct >= 15) {
          return 'Prime locale marquée par rapport aux marchés pairs : tension d’offre ou débouché vendeur potentiel.';
        }
        return 'Décrochage par rapport aux marchés pairs : vérifiez les conditions locales d’offre et de transport.';
      default:
        return 'Variation mensuelle atypique : confirmez s’il s’agit d’un choc d’offre ou d’une anomalie de relevé.';
    }
  }
}

class _TrackRecordBanner extends StatelessWidget {
  final String commodityLabel;
  final Map<String, dynamic> trackRecord;

  const _TrackRecordBanner({
    required this.commodityLabel,
    required this.trackRecord,
  });

  @override
  Widget build(BuildContext context) {
    final verdict = trackRecord['verdict']?.toString() ?? 'equivalent';
    final vsNaive = parseNum(trackRecord['vs_naive_pct'])?.toDouble() ?? 0.0;
    final months = parseNum(trackRecord['months'])?.toInt() ?? 12;

    final Color bg;
    final Color border;
    final Color fg;
    final IconData icon;
    final String title;
    final String subtitle;

    if (verdict == 'better') {
      bg = FDTheme.greenSoft;
      border = FDTheme.greenBorder;
      fg = FDTheme.greenDark;
      icon = Icons.verified_outlined;
      title =
          'Fiabilité vérifiée ($months mois · $commodityLabel) : +${vsNaive.abs().toStringAsFixed(0)} % plus précis que la référence naïve';
      subtitle = 'Exploitable pour calibrer vos achats, stocks et besoins de trésorerie B2B.';
    } else if (verdict == 'worse') {
      bg = FDTheme.warning.withValues(alpha: 0.10);
      border = FDTheme.warning.withValues(alpha: 0.35);
      fg = FDTheme.warningDark;
      icon = Icons.info_outline_rounded;
      title =
          'Prudence modèle ($months mois · $commodityLabel) : écart supérieur de ${vsNaive.abs().toStringAsFixed(0)} % à la référence naïve';
      subtitle = 'Privilégiez des engagements courts et croisez avec les cours locaux.';
    } else {
      bg = FDTheme.blueSoft;
      border = FDTheme.blue.withValues(alpha: 0.25);
      fg = FDTheme.blueDark;
      icon = Icons.balance_outlined;
      title =
          'Fiabilité ($months mois · $commodityLabel) : précision équivalente au prix du mois précédent';
      subtitle = 'Croisez la prévision avec les écarts inter-marchés et la saisonnalité.';
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: fg),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: fg,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  style: TextStyle(
                    fontSize: 12,
                    color: fg.withValues(alpha: 0.85),
                    height: 1.35,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PriceValue extends StatelessWidget {
  final String label;
  final String value;
  const _PriceValue({required this.label, required this.value});

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 11.5, color: FDTheme.muted)),
          const SizedBox(height: 3),
          Text(
            value,
            style: const TextStyle(
              fontSize: 17,
              fontWeight: FontWeight.w800,
              color: FDTheme.ink,
            ),
          ),
        ],
      );
}

class _ChangeBadge extends StatelessWidget {
  final String text;
  final bool positive;
  const _ChangeBadge({required this.text, required this.positive});

  @override
  Widget build(BuildContext context) {
    final color = positive ? FDTheme.green : const Color(0xFFB54745);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .09),
        borderRadius: BorderRadius.circular(30),
      ),
      child: Text(
        text,
        style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12),
      ),
    );
  }
}

class _StateMessage extends StatelessWidget {
  final String text;
  final VoidCallback? onRetry;
  const _StateMessage({required this.text, this.onRetry});

  @override
  Widget build(BuildContext context) => FDCard(
        child: Column(
          children: [
            const Icon(Icons.query_stats, size: 30, color: FDTheme.muted),
            const SizedBox(height: 10),
            Text(text, textAlign: TextAlign.center, style: const TextStyle(color: FDTheme.muted)),
            if (onRetry != null)
              TextButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Réessayer'),
              ),
          ],
        ),
      );
}
