import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import 'agronomist_pro_screen.dart';
import '../core/utils/error_text.dart';

/// Pré-diagnostic agro-climatique de zone (espace Grand Public, gratuit).
///
/// Données : NASA POWER Agro (humidité/PAR), NASA POWER (pluie/températures mensuelles)
/// et World Bank (national, annuel). Jamais une « analyse de parcelle ».
class AgricultureScreen extends StatefulWidget {
  final ApiService apiService;
  final void Function(String prompt)? onAskAssistant;
  final bool embedded;

  const AgricultureScreen({
    super.key,
    required this.apiService,
    this.onAskAssistant,
    this.embedded = false,
  });

  @override
  State<AgricultureScreen> createState() => _AgricultureScreenState();
}

class _AgricultureScreenState extends State<AgricultureScreen> {
  static const String _screenTitle = 'Pré-diagnostic agro-climatique de zone';

  static const Map<String, String> _confidenceFr = {
    'Satellite_Modeled_Regional': 'Satellite modélisé (régional)',
    'Official_Macro_National': 'Statistiques officielles (national)',
  };
  static const Map<String, String> _spatialFr = {
    'regional_city_hub': 'Pôle régional (ville)',
    'national': 'National',
  };
  static const Map<String, String> _nationalLabelsFr = {
    'cereal_yield': 'Rendement céréalier',
    'cereal_production': 'Production céréalière',
    'crop_production_index': 'Indice de production agricole',
    'food_production_index': 'Indice de production alimentaire',
    'arable_land_share': 'Terres arables',
    'agricultural_land_share': 'Terres agricoles',
    'agricultural_land_area': 'Superficie agricole',
    'forest_area_share': 'Couvert forestier',
    'fertilizer_consumption': 'Consommation d’engrais',
    'agriculture_forestry_and_fishing_value_added':
        'Valeur ajoutée agricole (PIB)',
    'employment_in_agriculture_ilo_modeled': 'Emploi agricole',
  };
  static const Map<String, String> _unitsFr = {
    'metric tons': 'tonnes',
    'sq. km': 'km²',
    '% of land area': '% du territoire',
    '% of GDP': '% du PIB',
    '% of total employment': '% de l’emploi',
    'index (2014-2016=100)': 'indice (2014-2016 = 100)',
    'ratio (0-1)': 'indice (0-1)',
  };

  List<Map<String, dynamic>> _zones = const [];
  String? _selectedRegion;
  String _selectedIndicator = 'root_zone_wetness';
  Map<String, dynamic>? _profile;
  bool _zonesAvailable = true;
  bool _loadingZones = true;
  bool _loadingProfile = false;
  String? _error;
  int _profileSeq = 0;

  @override
  void initState() {
    super.initState();
    _loadZones();
  }

  Future<void> _loadZones({bool forceRefresh = false}) async {
    setState(() {
      _loadingZones = _zones.isEmpty;
      _error = null;
    });
    try {
      final res =
          await widget.apiService.getAgroZones(forceRefresh: forceRefresh);
      final zones = ((res['zones'] as List?) ?? const [])
          .whereType<Map>()
          .map((z) => Map<String, dynamic>.from(z))
          .toList();
      if (!mounted) return;
      final available = res['data_available'] == true && zones.isNotEmpty;
      String? region = _selectedRegion;
      if (region == null || !zones.any((z) => z['region'] == region)) {
        String? preferredRegion;
        try {
          final prefs = await SharedPreferences.getInstance();
          preferredRegion = prefs.getString('fd_pref_agro_hub');
        } catch (_) {
          // Le choix par défaut reste facultatif si les préférences sont indisponibles.
        }
        if (preferredRegion != null &&
            zones.any((z) => z['region'] == preferredRegion)) {
          region = preferredRegion;
        } else {
          region = zones.any((z) => z['region'] == "N'Djamena")
              ? "N'Djamena"
              : (zones.isNotEmpty ? zones.first['region']?.toString() : null);
        }
      }
      setState(() {
        _zones = zones;
        _zonesAvailable = available;
        _selectedRegion = region;
        _loadingZones = false;
      });
      if (available && region != null) {
        await _loadProfile(region, forceRefresh: forceRefresh);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = _friendlyError(e);
        _loadingZones = false;
      });
    }
  }

  Future<void> _loadProfile(String region, {bool forceRefresh = false}) async {
    final seq = ++_profileSeq;
    final cached = widget.apiService.cachedAgroZoneProfile(region);
    setState(() {
      _selectedRegion = region;
      _profile = cached ?? _profile;
      _loadingProfile = cached == null;
      _error = null;
    });
    try {
      final profile = await widget.apiService
          .getAgroZoneProfile(region, forceRefresh: forceRefresh);
      if (!mounted || seq != _profileSeq) return;
      final keys = _seriesKeys(profile);
      setState(() {
        _profile = profile;
        if (!keys.contains(_selectedIndicator) && keys.isNotEmpty) {
          _selectedIndicator = keys.first;
        }
        _loadingProfile = false;
      });
    } catch (e) {
      if (!mounted || seq != _profileSeq) return;
      setState(() {
        _error = _friendlyError(e);
        _loadingProfile = false;
      });
    }
  }

  String _friendlyError(Object e) {
    final text = errText(e);
    if (text.contains('TimeoutException')) {
      return 'Le serveur met plus de temps que prévu à répondre (démarrage en cours).';
    }
    return text.replaceFirst('Exception: ', '');
  }

  List<String> _seriesKeys(Map<String, dynamic> profile) {
    final series = profile['series'];
    if (series is! Map) return const [];
    const order = [
      'root_zone_wetness',
      'surface_wetness',
      'par',
      'precipitation_daily_mean',
      'temperature_mean',
      'temperature_max',
      'temperature_min',
    ];
    final keys = series.keys.map((k) => k.toString()).toList();
    keys.sort((a, b) {
      final ia = order.indexOf(a);
      final ib = order.indexOf(b);
      return (ia < 0 ? 99 : ia).compareTo(ib < 0 ? 99 : ib);
    });
    return keys;
  }

  String _monthYear(String? iso) {
    if (iso == null || iso.length < 7) return '—';
    return '${iso.substring(5, 7)}/${iso.substring(0, 4)}';
  }

  String _year(String? iso) =>
      (iso == null || iso.length < 4) ? '—' : iso.substring(0, 4);

  String _formatNumber(num value) {
    final abs = value.abs();
    String text;
    if (abs >= 1000) {
      text = value.round().toString();
      final sign = text.startsWith('-') ? '-' : '';
      final digits = sign.isEmpty ? text : text.substring(1);
      final buffer = StringBuffer();
      for (var i = 0; i < digits.length; i++) {
        if (i > 0 && (digits.length - i) % 3 == 0) buffer.write('\u202F');
        buffer.write(digits[i]);
      }
      return '$sign$buffer';
    }
    text = abs >= 100
        ? value.toStringAsFixed(0)
        : (abs >= 10 ? value.toStringAsFixed(1) : value.toStringAsFixed(2));
    return text;
  }

  String _unit(String? raw) {
    if (raw == null || raw.isEmpty) return '';
    return _unitsFr[raw] ?? raw;
  }

  String _askPrompt() {
    final region = _selectedRegion ?? 'cette zone';
    return 'Donne-moi le pré-diagnostic agro-climatique de la zone de $region (humidité des sols, rayonnement, anomalies par rapport à la normale 2020–2023) en citant les sources.';
  }

  @override
  Widget build(BuildContext context) {
    if (widget.embedded) {
      return Container(
        color: AppColors.canvas,
        child: _buildBody(),
      );
    }
    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
        title: const Text('Agriculture',
            style: TextStyle(fontWeight: FontWeight.w700)),
        actions: [
          IconButton(
            tooltip: 'Actualiser',
            icon: const Icon(Icons.refresh_rounded),
            onPressed: () => _loadZones(forceRefresh: true),
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loadingZones) {
      return const FDLoadingState(message: 'Chargement des zones agricoles…');
    }
    if (_error != null && _profile == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: FDErrorState(
              message: _error!,
              onRetry: () => _loadZones(forceRefresh: true),
            ),
          ),
        ),
      );
    }
    if (!_zonesAvailable) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: FDCard(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: const [
                  Icon(Icons.eco_outlined, size: 34, color: AppColors.blue),
                  SizedBox(height: 10),
                  Text(
                    'Données agro-climatiques en cours de chargement',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                        fontSize: 15.5,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ink),
                  ),
                  SizedBox(height: 6),
                  Text(
                    'Le pré-diagnostic de zone sera disponible dès que les indicateurs auront été publiés.',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 13, color: AppColors.muted),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }
    final profile = _profile;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 980),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
              _screenTitle,
              style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                  letterSpacing: -0.2,
                  color: AppColors.ink),
            ),
            const SizedBox(height: 4),
            const Text(
              'Humidité des sols, pluie et températures mensuelles issues de données satellitaires modélisées aux pôles régionaux. Ce n’est pas une analyse de parcelle.',
              style:
                  TextStyle(fontSize: 13, color: AppColors.muted, height: 1.4),
            ),
            const SizedBox(height: 14),
            _buildZoneSelector(),
            const SizedBox(height: 14),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: FDErrorState(
                  message: _error!,
                  onRetry: () {
                    final r = _selectedRegion;
                    if (r != null) _loadProfile(r, forceRefresh: true);
                  },
                ),
              ),
            if (_loadingProfile && profile == null)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 40),
                child: FDLoadingState(message: 'Chargement du profil de zone…'),
              )
            else if (profile != null) ...[
              if (_loadingProfile)
                const Padding(
                  padding: EdgeInsets.only(bottom: 10),
                  child: LinearProgressIndicator(minHeight: 2),
                ),
              ..._buildProfile(profile),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildZoneSelector() {
    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          DropdownButtonFormField<String>(
            key: ValueKey(_selectedRegion),
            initialValue: _selectedRegion,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Zone (pôle)'),
            items: _zones.map((z) {
              final region = z['region']?.toString() ?? '';
              final province = z['province']?.toString();
              return DropdownMenuItem<String>(
                value: region,
                child: Text(province == null || province.isEmpty
                    ? region
                    : '$region · $province'),
              );
            }).toList(),
            onChanged: (v) {
              if (v != null) _loadProfile(v);
            },
          ),
          if (widget.onAskAssistant != null) ...[
            const SizedBox(height: 12),
            Wrap(
              spacing: 10,
              runSpacing: 8,
              children: [
                FDSecondaryButton(
                  label: 'Analyser cette zone avec l’assistant',
                  icon: Icons.auto_awesome_outlined,
                  onPressed: () => widget.onAskAssistant!(_askPrompt()),
                ),
                FDPrimaryButton(
                  label: 'Diagnostic de terrain (Agronome PRO)',
                  icon: Icons.science_outlined,
                  onPressed: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => AgronomistProScreen(
                          apiService: widget.apiService,
                          initialHub: _selectedRegion,
                        ),
                      ),
                    );
                  },
                ),
              ],
            ),
          ] else ...[
            const SizedBox(height: 12),
            FDPrimaryButton(
              label: 'Diagnostic de terrain (Agronome PRO)',
              icon: Icons.science_outlined,
              onPressed: () {
                Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => AgronomistProScreen(
                      apiService: widget.apiService,
                      initialHub: _selectedRegion,
                    ),
                  ),
                );
              },
            ),
          ],
        ],
      ),
    );
  }

  List<Widget> _buildProfile(Map<String, dynamic> profile) {
    final keys = _seriesKeys(profile);
    final latest = profile['latest'] is Map
        ? Map<String, dynamic>.from(profile['latest'] as Map)
        : const <String, dynamic>{};
    final labels = profile['indicator_labels'] is Map
        ? Map<String, dynamic>.from(profile['indicator_labels'] as Map)
        : const <String, dynamic>{};
    final alerts = ((profile['alerts'] as List?) ?? const [])
        .whereType<Map>()
        .map((a) => Map<String, dynamic>.from(a))
        .toList();
    final signals = profile['hydric_risk_signals'] is Map
        ? Map<String, dynamic>.from(profile['hydric_risk_signals'] as Map)
        : const <String, dynamic>{};
    final falseSowing = signals['false_sowing_start'] == true;
    final cropPrices = ((profile['validated_crop_prices'] as List?) ?? const [])
        .whereType<Map>()
        .map((c) => Map<String, dynamic>.from(c))
        .toList();
    final selectedKey = keys.contains(_selectedIndicator)
        ? _selectedIndicator
        : (keys.isNotEmpty ? keys.first : null);
    final points = selectedKey == null
        ? const <Map<String, dynamic>>[]
        : (((profile['series'] as Map)[selectedKey] as List?) ?? const [])
            .whereType<Map>()
            .map((p) => Map<String, dynamic>.from(p))
            .toList();

    return [
      if (profile['stale'] == true)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: _notice(
            Icons.schedule_rounded,
            'Les derniers relevés de cette zone datent de plus de 3 mois : interprétez les valeurs avec prudence.',
            AppColors.warning,
          ),
        ),
      if (falseSowing)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: _notice(
            Icons.warning_amber_rounded,
            'Alerte fenêtre de semis : l’humidité de surface est en hausse alors que l’humidité racinaire reste sous la normale (risque de faux démarrage).',
            AppColors.warning,
          ),
        ),
      if (alerts.isNotEmpty) ...[
        ...alerts.map(_alertCard),
        const SizedBox(height: 4),
      ],
      Wrap(
        spacing: 12,
        runSpacing: 12,
        children: keys.map((k) {
          final item = latest[k] is Map
              ? Map<String, dynamic>.from(latest[k] as Map)
              : const <String, dynamic>{};
          final value = item['value'];
          return SizedBox(
            width: 290,
            child: FDCard(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    labels[k]?.toString() ?? item['label']?.toString() ?? k,
                    style: const TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600,
                        color: AppColors.muted),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    value is num ? _formatNumber(value) : '—',
                    style: const TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${_unit(item['unit']?.toString())} · ${_monthYear(item['reference_date']?.toString())}',
                    style:
                        const TextStyle(fontSize: 12, color: AppColors.muted),
                  ),
                ],
              ),
            ),
          );
        }).toList(),
      ),
      const SizedBox(height: 14),
      FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Évolution mensuelle',
              style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppColors.ink),
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: keys.map((k) {
                return ChoiceChip(
                  label: Text(labels[k]?.toString() ?? k),
                  selected: k == selectedKey,
                  onSelected: (_) => setState(() => _selectedIndicator = k),
                );
              }).toList(),
            ),
            const SizedBox(height: 14),
            if (points.isEmpty)
              const Text('Aucune donnée pour cet indicateur.',
                  style: TextStyle(color: AppColors.muted))
            else ...[
              SizedBox(
                height: 220,
                child: CustomPaint(
                  key: const ValueKey('agro-trend-chart'),
                  size: Size.infinite,
                  painter: _TrendPainter(
                    values: points
                        .map((p) => (p['value'] as num?)?.toDouble())
                        .toList(),
                    normal: points
                        .map((p) => (p['baseline_mean'] as num?)?.toDouble())
                        .toList(),
                    firstLabel:
                        _monthYear(points.first['reference_date']?.toString()),
                    lastLabel:
                        _monthYear(points.last['reference_date']?.toString()),
                    lineColor: AppColors.blue,
                    normalColor: AppColors.subtle,
                    gridColor: AppColors.line,
                    textColor: AppColors.muted,
                    formatter: _formatNumber,
                  ),
                ),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  _legendDot(AppColors.blue, 'Valeur observée'),
                  const SizedBox(width: 16),
                  _legendDot(
                      AppColors.subtle, 'Normale 2020–2023 du même mois'),
                ],
              ),
            ],
          ],
        ),
      ),
      const SizedBox(height: 14),
      if (cropPrices.isNotEmpty) ...[
        FDCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Prévisions de prix — 4 cultures validées',
                style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: AppColors.ink),
              ),
              const SizedBox(height: 8),
              ...cropPrices.map((cp) {
                final mape = cp['historical_mape_pct'];
                return ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(
                    cp['label_fr']?.toString() ??
                        cp['commodity_std']?.toString() ??
                        '',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  subtitle: Text(
                    'Prévu (${cp['forecast_month'] ?? 't+1'}) : ${cp['predicted_xaf_kg'] ?? '—'} XAF/kg',
                    style:
                        const TextStyle(fontSize: 12.5, color: AppColors.muted),
                  ),
                  trailing: FDBadge(
                    label: mape != null ? 'MAPE $mape %' : 'MAPE N/D',
                    color: AppColors.blue,
                    backgroundColor: AppColors.blueSoft,
                  ),
                );
              }),
            ],
          ),
        ),
        const SizedBox(height: 14),
      ],
      ..._buildNational(profile),
      const SizedBox(height: 14),
      _buildProvenance(profile),
      const SizedBox(height: 24),
    ];
  }

  Widget _legendDot(Color color, String text) {
    return Flexible(
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
              width: 10,
              height: 10,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Flexible(
            child: Text(text,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, color: AppColors.muted)),
          ),
        ],
      ),
    );
  }

  Widget _notice(IconData icon, String text, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text,
                style: const TextStyle(
                    fontSize: 13, color: AppColors.ink, height: 1.4)),
          ),
        ],
      ),
    );
  }

  Widget _alertCard(Map<String, dynamic> alert) {
    final severe = alert['level'] == 'severe';
    final color = severe ? AppColors.danger : AppColors.warning;
    final label =
        severe ? 'Déficit hydrique sévère' : 'Déficit hydrique modéré';
    final stale = alert['stale'] == true;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: _notice(
        Icons.water_drop_outlined,
        '$label (${_monthYear(alert['reference_date']?.toString())}) — ${alert['message'] ?? ''}'
        '${stale ? ' Relevé ancien.' : ''}\nRepère indicatif, à confirmer sur le terrain.',
        color,
      ),
    );
  }

  List<Widget> _buildNational(Map<String, dynamic> profile) {
    final national = profile['national'] is Map
        ? Map<String, dynamic>.from(profile['national'] as Map)
        : const <String, dynamic>{};
    final indicators = ((national['indicators'] as List?) ?? const [])
        .whereType<Map>()
        .map((i) => Map<String, dynamic>.from(i))
        .toList();
    if (indicators.isEmpty) return const [];
    return [
      const Text(
        'Indicateurs agricoles nationaux (World Bank)',
        style: TextStyle(
            fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
      ),
      const SizedBox(height: 4),
      const Text(
        'Dernière année disponible, valeurs annuelles pour l’ensemble du Tchad.',
        style: TextStyle(fontSize: 12.5, color: AppColors.muted),
      ),
      const SizedBox(height: 10),
      Wrap(
        spacing: 12,
        runSpacing: 12,
        children: indicators.map((ind) {
          final key = ind['key']?.toString() ?? '';
          final last = ind['latest'] is Map
              ? Map<String, dynamic>.from(ind['latest'] as Map)
              : const <String, dynamic>{};
          final value = last['value'];
          return SizedBox(
            width: 230,
            child: FDCard(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _nationalLabelsFr[key] ??
                        ind['indicator']?.toString() ??
                        key,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600,
                        color: AppColors.muted),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    value is num ? _formatNumber(value) : '—',
                    style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${_unit(ind['unit']?.toString())} · ${_year(last['reference_date']?.toString())}',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style:
                        const TextStyle(fontSize: 12, color: AppColors.muted),
                  ),
                ],
              ),
            ),
          );
        }).toList(),
      ),
    ];
  }

  String _joinMapped(dynamic raw, Map<String, String> mapping) {
    if (raw is! List) return '—';
    final items =
        raw.map((e) => mapping[e.toString()] ?? e.toString()).toList();
    return items.isEmpty ? '—' : items.join(', ');
  }

  Widget _buildProvenance(Map<String, dynamic> profile) {
    final prov = profile['provenance'] is Map
        ? Map<String, dynamic>.from(profile['provenance'] as Map)
        : const <String, dynamic>{};
    final natProv = (profile['national'] is Map &&
            (profile['national'] as Map)['provenance'] is Map)
        ? Map<String, dynamic>.from(
            (profile['national'] as Map)['provenance'] as Map)
        : const <String, dynamic>{};
    final period = prov['reference_period'] is Map
        ? Map<String, dynamic>.from(prov['reference_period'] as Map)
        : const <String, dynamic>{};
    final limitations = ((profile['limitations'] as List?) ?? const [])
        .map((e) => e.toString())
        .toList();

    Widget row(String label, String value) => Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 130,
                child: Text(label,
                    style: const TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600,
                        color: AppColors.muted)),
              ),
              Expanded(
                child: Text(value,
                    style: const TextStyle(
                        fontSize: 12.5, color: AppColors.ink, height: 1.35)),
              ),
            ],
          ),
        );

    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Sources, licences et limites',
            style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w700,
                color: AppColors.ink),
          ),
          const SizedBox(height: 10),
          row('Source zone', _joinMapped(prov['sources'], const {})),
          row('Licence', _joinMapped(prov['licenses'], const {})),
          row('Période',
              '${_monthYear(period['first']?.toString())} → ${_monthYear(period['last']?.toString())}'),
          row('Résolution',
              _joinMapped(prov['spatial_resolution'], _spatialFr)),
          row('Confiance',
              _joinMapped(prov['confidence_level'], _confidenceFr)),
          if (natProv.isNotEmpty) ...[
            const SizedBox(height: 6),
            row('Source nationale', _joinMapped(natProv['sources'], const {})),
            row('Licence nationale',
                _joinMapped(natProv['licenses'], const {})),
          ],
          const SizedBox(height: 6),
          row('Sources marchés',
              'WFP / FEWS NET · attribution requise ; réutilisation commerciale à confirmer selon les droits de la source primaire'),
          if (limitations.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Text('Limites méthodologiques & portée d’utilisation',
                style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: AppColors.ink)),
            const SizedBox(height: 4),
            ...limitations.map(
              (l) => Padding(
                padding: const EdgeInsets.only(bottom: 3),
                child: Text('• $l',
                    style: const TextStyle(
                        fontSize: 12, color: AppColors.muted, height: 1.4)),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _TrendPainter extends CustomPainter {
  final List<double?> values;
  final List<double?> normal;
  final String firstLabel;
  final String lastLabel;
  final Color lineColor;
  final Color normalColor;
  final Color gridColor;
  final Color textColor;
  final String Function(num) formatter;

  _TrendPainter({
    required this.values,
    required this.normal,
    required this.firstLabel,
    required this.lastLabel,
    required this.lineColor,
    required this.normalColor,
    required this.gridColor,
    required this.textColor,
    required this.formatter,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final all = <double>[
      ...values.whereType<double>(),
      ...normal.whereType<double>(),
    ];
    if (all.isEmpty || values.length < 2) return;
    var minV = all.reduce((a, b) => a < b ? a : b);
    var maxV = all.reduce((a, b) => a > b ? a : b);
    if (maxV - minV < 1e-9) {
      maxV += 0.5;
      minV -= 0.5;
    }
    final pad = (maxV - minV) * 0.08;
    minV -= pad;
    maxV += pad;

    const left = 48.0;
    const right = 8.0;
    const top = 8.0;
    const bottom = 22.0;
    final w = size.width - left - right;
    final h = size.height - top - bottom;
    if (w <= 0 || h <= 0) return;

    double dx(int i) => left + w * i / (values.length - 1);
    double dy(double v) => top + h * (1 - (v - minV) / (maxV - minV));

    final grid = Paint()
      ..color = gridColor
      ..strokeWidth = 1;
    for (var g = 0; g <= 3; g++) {
      final y = top + h * g / 3;
      canvas.drawLine(Offset(left, y), Offset(left + w, y), grid);
      final v = maxV - (maxV - minV) * g / 3;
      _text(canvas, formatter(v), Offset(0, y - 6), 10.5,
          maxWidth: left - 6, alignRight: true);
    }
    _text(canvas, firstLabel, Offset(left, size.height - 16), 10.5);
    _text(canvas, lastLabel, Offset(left + w - 48, size.height - 16), 10.5,
        maxWidth: 48, alignRight: true);

    void drawSeries(List<double?> data, Color color, double width) {
      final paint = Paint()
        ..color = color
        ..strokeWidth = width
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round
        ..strokeCap = StrokeCap.round;
      Path? path;
      for (var i = 0; i < data.length; i++) {
        final v = data[i];
        if (v == null) {
          if (path != null) canvas.drawPath(path, paint);
          path = null;
          continue;
        }
        final p = Offset(dx(i), dy(v));
        if (path == null) {
          path = Path()..moveTo(p.dx, p.dy);
        } else {
          path.lineTo(p.dx, p.dy);
        }
      }
      if (path != null) canvas.drawPath(path, paint);
    }

    drawSeries(normal, normalColor, 1.6);
    drawSeries(values, lineColor, 2.4);
  }

  void _text(Canvas canvas, String text, Offset offset, double fontSize,
      {double? maxWidth, bool alignRight = false}) {
    final tp = TextPainter(
      text: TextSpan(
          text: text, style: TextStyle(fontSize: fontSize, color: textColor)),
      textDirection: TextDirection.ltr,
      maxLines: 1,
    )..layout(maxWidth: maxWidth ?? double.infinity);
    final dxOffset = alignRight && maxWidth != null
        ? offset.dx + maxWidth - tp.width
        : offset.dx;
    tp.paint(canvas, Offset(dxOffset, offset.dy));
  }

  @override
  bool shouldRepaint(covariant _TrendPainter old) =>
      old.values != values ||
      old.normal != normal ||
      old.lineColor != lineColor;
}
