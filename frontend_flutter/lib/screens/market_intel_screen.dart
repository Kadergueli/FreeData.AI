import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/error_text.dart';
import '../services/api_service.dart';

const List<List<String>> _kProducts = [
  ['millet', 'Mil'],
  ['sorghum', 'Sorgho rouge'],
  ['maize', 'Maïs blanc'],
  ['groundnut', 'Arachide'],
  ['rice_local', 'Riz local'],
  ['rice_imported', 'Riz importé'],
  ['sesame', 'Sésame'],
  ['cowpea', 'Niébé'],
  ['onion', 'Oignon rouge'],
  ['sugar', 'Sucre'],
  ['wheat_flour', 'Farine de blé'],
];

Map<String, dynamic> _asMap(dynamic value) {
  if (value is Map) return Map<String, dynamic>.from(value);
  return <String, dynamic>{};
}

List<Map<String, dynamic>> _asList(dynamic value) {
  if (value is! List) return <Map<String, dynamic>>[];
  final out = <Map<String, dynamic>>[];
  for (final item in value) {
    if (item is Map) out.add(Map<String, dynamic>.from(item));
  }
  return out;
}

String _pct(dynamic value) {
  if (value is! num) return '—';
  final sign = value > 0 ? '+' : '';
  return '$sign${value.toStringAsFixed(1)} %';
}

String _xaf(dynamic value) {
  if (value is! num) return '—';
  final digits = value.round().abs().toString();
  final buf = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buf.write(' ');
    buf.write(digits[i]);
  }
  return '$buf XAF/kg';
}

Widget _sectionTitle(String text) {
  return Padding(
    padding: const EdgeInsets.only(top: 22, bottom: 8),
    child: Text(
      text,
      style: const TextStyle(
        fontSize: 15.5,
        fontWeight: FontWeight.w800,
        color: AppColors.ink,
      ),
    ),
  );
}

Widget _note(String text) {
  return Padding(
    padding: const EdgeInsets.only(top: 6),
    child: Text(
      text,
      style: const TextStyle(
        fontSize: 12.5,
        color: AppColors.muted,
        height: 1.4,
      ),
    ),
  );
}

Widget _bullets(List<dynamic> items) {
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      for (final item in items)
        Padding(
          padding: const EdgeInsets.only(top: 5),
          child: Text(
            '• $item',
            style: const TextStyle(
              fontSize: 13,
              color: AppColors.body,
              height: 1.4,
            ),
          ),
        ),
    ],
  );
}

Widget _statTile(String label, String value) {
  return Container(
    width: 150,
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: AppColors.canvasSoft,
      borderRadius: BorderRadius.circular(10),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(fontSize: 11.5, color: AppColors.subtle),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w800,
            color: AppColors.ink,
          ),
        ),
      ],
    ),
  );
}

Widget _row(String left, String right, {Color? rightColor}) {
  return Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(
      children: [
        Expanded(
          child: Text(
            left,
            style: const TextStyle(fontSize: 13, color: AppColors.body),
          ),
        ),
        Text(
          right,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: rightColor ?? AppColors.ink,
          ),
        ),
      ],
    ),
  );
}

Widget _spark(List<Map<String, dynamic>> series) {
  final values = <double>[];
  for (final point in series) {
    final v = point['value'];
    if (v is num) values.add(v.toDouble());
  }
  if (values.length < 2) return const SizedBox.shrink();
  final lo = values.reduce(math.min);
  final hi = values.reduce(math.max);
  final span = hi > lo ? hi - lo : 1.0;
  return SizedBox(
    height: 60,
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        for (final v in values)
          Expanded(
            child: Container(
              margin: const EdgeInsets.symmetric(horizontal: 1),
              height: 8 + 50 * (v - lo) / span,
              color: AppColors.blue,
            ),
          ),
      ],
    ),
  );
}

/// Intelligence marché : comprendre un marché avant de s'y engager.
/// Fiche produit (Standard) ; brief d'entrée, comparateur, pouls, panier,
/// contexte mondial et alertes (PRO).
class MarketIntelScreen extends StatefulWidget {
  final ApiService apiService;
  final VoidCallback? onRequestPro;

  const MarketIntelScreen({
    super.key,
    required this.apiService,
    this.onRequestPro,
  });

  @override
  State<MarketIntelScreen> createState() => _MarketIntelScreenState();
}

class _MarketIntelScreenState extends State<MarketIntelScreen> {
  String _product = 'millet';
  bool _loading = true;
  String? _error;
  Map<String, dynamic>? _brief;
  Map<String, dynamic>? _entry;
  Map<String, dynamic>? _compare;
  Map<String, dynamic>? _pulse;
  Map<String, dynamic>? _basket;
  Map<String, dynamic>? _world;
  Map<String, dynamic>? _alerts;

  String _alertKind = 'threshold';
  String _alertDirection = 'above';
  final _alertValueCtrl = TextEditingController();
  final _alertMarketCtrl = TextEditingController();
  String? _alertError;

  bool get _isPro => widget.apiService.hasPremiumKey;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _alertValueCtrl.dispose();
    _alertMarketCtrl.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>?> _safe(
    Future<Map<String, dynamic>> request,
  ) async {
    try {
      return await request;
    } catch (_) {
      return null;
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final api = widget.apiService;
    try {
      final brief = await api.getMarketIntelProduct(_product);
      Map<String, dynamic>? entry;
      Map<String, dynamic>? compare;
      Map<String, dynamic>? pulse;
      Map<String, dynamic>? basket;
      Map<String, dynamic>? world;
      Map<String, dynamic>? alerts;
      if (_isPro) {
        entry = await _safe(api.getMarketIntelEntryBrief(_product));
        compare = await _safe(api.getMarketIntelCompare(_product));
        pulse = await _safe(api.getMarketIntelPulse());
        basket = await _safe(api.getMarketIntelBasket());
        world = await _safe(api.getMarketIntelWorld(_product));
        alerts = await _safe(api.getMarketIntelAlerts());
      }
      if (!mounted) return;
      setState(() {
        _brief = brief;
        _entry = entry;
        _compare = compare;
        _pulse = pulse;
        _basket = basket;
        _world = world;
        _alerts = alerts;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      final message = errText(e);
      setState(() {
        _error = message;
        _loading = false;
      });
    }
  }

  Future<void> _createAlert() async {
    final value = double.tryParse(_alertValueCtrl.text.replaceAll(',', '.'));
    final needsValue = _alertKind != 'new_data';
    if (needsValue && (value == null || value <= 0)) {
      setState(() => _alertError = 'Saisissez une valeur positive.');
      return;
    }
    setState(() => _alertError = null);
    try {
      await widget.apiService.createMarketIntelAlert(
        kind: _alertKind,
        productId: _product,
        value: value ?? 0,
        direction: _alertDirection,
        marketName: _alertMarketCtrl.text,
      );
      _alertValueCtrl.clear();
      final alerts = await widget.apiService.getMarketIntelAlerts();
      if (!mounted) return;
      setState(() => _alerts = alerts);
    } catch (e) {
      if (!mounted) return;
      final message = errText(e);
      setState(() => _alertError = message);
    }
  }

  Future<void> _alertAction(Future<void> Function() action) async {
    try {
      await action();
      final alerts = await widget.apiService.getMarketIntelAlerts();
      if (!mounted) return;
      setState(() => _alerts = alerts);
    } catch (e) {
      if (!mounted) return;
      final message = errText(e);
      setState(() => _alertError = message);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.canvas,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1040),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: _content(),
              ),
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _content() {
    return [
      const Text(
        'Comprendre le marché avant de s’y engager',
        style: TextStyle(
          fontSize: 18,
          fontWeight: FontWeight.w800,
          color: AppColors.ink,
        ),
      ),
      _note(
        'Suivi et explication des prix de détail observés. '
        'Ce n’est ni une prévision ni un conseil d’investissement.',
      ),
      const SizedBox(height: 12),
      _productChips(),
      if (_loading)
        const Padding(
          padding: EdgeInsets.all(32),
          child: Center(child: CircularProgressIndicator()),
        )
      else if (_error != null)
        _errorCard(_error!)
      else ...[
        ..._briefSection(),
        if (_isPro) ..._proSections() else _proLock(),
      ],
    ];
  }

  Widget _productChips() {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final p in _kProducts)
          ChoiceChip(
            label: Text(p[1]),
            selected: _product == p[0],
            onSelected: (_) {
              setState(() => _product = p[0]);
              _load();
            },
          ),
      ],
    );
  }

  Widget _errorCard(String message) {
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              message,
              style: const TextStyle(color: AppColors.dangerDark),
            ),
            const SizedBox(height: 12),
            FDPrimaryButton(
              label: 'Réessayer',
              icon: Icons.refresh_rounded,
              onPressed: _load,
            ),
          ],
        ),
      ),
    );
  }

  Widget _proLock() {
    return Padding(
      padding: const EdgeInsets.only(top: 20),
      child: FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const FDBadge(
              label: 'FONCTIONNALITÉ PRO',
              color: AppColors.blue,
              backgroundColor: AppColors.blueSoft,
            ),
            const SizedBox(height: 10),
            const Text(
              'Brief d’entrée marché, comparateur de marchés, fenêtre de '
              'stockage, pouls du marché, panier, contexte mondial et alertes.',
              style: TextStyle(fontSize: 13.5, color: AppColors.body),
            ),
            if (widget.onRequestPro != null) ...[
              const SizedBox(height: 14),
              FDPrimaryButton(
                label: 'Activer l’accès PRO',
                icon: Icons.workspace_premium_outlined,
                onPressed: widget.onRequestPro,
              ),
            ],
          ],
        ),
      ),
    );
  }

  List<Widget> _briefSection() {
    final b = _brief ?? <String, dynamic>{};
    if (b['status'] != 'ok') {
      return [
        _sectionTitle('Fiche produit'),
        _note('Données insuffisantes pour ce produit.'),
        _bullets(b['limits'] is List ? b['limits'] as List : const []),
      ];
    }
    final vol = _asMap(b['volatility']);
    final range = _asMap(b['range_12m']);
    final seas = _asMap(b['seasonality']);
    return [
      _sectionTitle('Fiche produit · ${b['label_fr']} (${b['as_of']})'),
      FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _statTile('Prix médian', _xaf(b['national_median_xaf_kg'])),
                _statTile('Sur 1 mois', _pct(b['mom_pct'])),
                _statTile('Sur 3 mois', _pct(b['three_month_pct'])),
                _statTile('Sur 1 an', _pct(b['yoy_pct'])),
                _statTile('Marchés observés', '${b['n_markets']}'),
              ],
            ),
            const SizedBox(height: 12),
            _spark(_asList(b['series'])),
            _row('Tendance', '${b['direction']}'),
            _row('Mouvement du mois', '${vol['label']}'),
            _row(
              'Variation mensuelle typique',
              '± ${vol['typical_monthly_move_pct']} %',
            ),
            _row(
              'Fourchette 12 mois',
              '${_xaf(range['min'])} – ${_xaf(range['max'])}',
            ),
            _row(
              'Position dans l’historique',
              '${b['percentile_vs_history']} %',
            ),
            if (seas['status'] == 'ok') ...[
              _row('Mois les moins chers', '${seas['buy_months']}'),
              _row('Mois les plus chers', '${seas['sell_months']}'),
              _note('Saisonnalité ${seas['label']}.'),
            ],
            const SizedBox(height: 8),
            _bullets(b['limits'] is List ? b['limits'] as List : const []),
          ],
        ),
      ),
    ];
  }

  List<Widget> _proSections() {
    return [
      ..._entrySection(),
      ..._compareSection(),
      ..._pulseSection(),
      ..._basketSection(),
      ..._worldSection(),
      ..._alertsSection(),
    ];
  }

  List<Widget> _entrySection() {
    final e = _entry;
    if (e == null || e['status'] != 'ok') return const [];
    final where = _asMap(e['where']);
    final storage = _asMap(e['storage_window']);
    return [
      _sectionTitle('Brief d’entrée marché'),
      FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Où acheter le moins cher',
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
            for (final m in _asList(where['cheapest']))
              _row(
                  '${m['market']} (${m['province']})', _xaf(m['price_xaf_kg'])),
            const SizedBox(height: 10),
            const Text(
              'Où le prix est le plus haut',
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
            for (final m in _asList(where['dearest']))
              _row(
                  '${m['market']} (${m['province']})', _xaf(m['price_xaf_kg'])),
            if (storage['status'] == 'ok') ...[
              const SizedBox(height: 10),
              const Text(
                'Fenêtre de stockage',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
              _row(
                'Acheter en ${storage['buy_month']}, '
                'vendre en ${storage['sell_month']}',
                _pct(storage['gross_gain_pct']),
              ),
              _note('${storage['note']}'),
            ],
            const SizedBox(height: 10),
            const Text(
              'Risques à surveiller',
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
            _bullets(e['risks'] is List ? e['risks'] as List : const []),
            const SizedBox(height: 10),
            const Text(
              'Questions à vous poser avant de vous engager',
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
            _bullets(
              e['questions_before_committing'] is List
                  ? e['questions_before_committing'] as List
                  : const [],
            ),
          ],
        ),
      ),
    ];
  }

  List<Widget> _compareSection() {
    final c = _compare;
    if (c == null || c['status'] != 'ok') return const [];
    final markets = _asList(c['markets']);
    final spread = _asMap(c['spread']);
    return [
      _sectionTitle('Comparateur de marchés'),
      FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _row('Médiane nationale', _xaf(c['national_median_xaf_kg'])),
            if (spread.isNotEmpty) ...[
              _row('Écart brut entre marchés', _pct(spread['gross_gap_pct'])),
              _note('${spread['note']}'),
            ],
            const SizedBox(height: 8),
            for (final m in markets.take(15))
              _row(
                '${m['market']} (${m['province']})',
                '${_xaf(m['price_xaf_kg'])}  ${_pct(m['gap_vs_median_pct'])}',
              ),
          ],
        ),
      ),
    ];
  }

  List<Widget> _pulseSection() {
    final p = _pulse;
    if (p == null || p['status'] != 'ok') return const [];
    final summary = _asMap(p['summary']);
    return [
      _sectionTitle('Pouls du marché'),
      FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _note(
              '${summary['rising']} en hausse · ${summary['falling']} en '
              'baisse · ${summary['stable']} stables',
            ),
            const SizedBox(height: 6),
            for (final i in _asList(p['items']))
              _row(
                '${i['label_fr']} · ${i['volatility_label']}',
                '${_pct(i['mom_pct'])} / mois',
              ),
          ],
        ),
      ),
    ];
  }

  List<Widget> _basketSection() {
    final b = _basket;
    if (b == null || b['status'] != 'ok') return const [];
    return [
      _sectionTitle('Panier de matières premières'),
      FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _row('Indice (base 100)', '${b['index']}'),
            _row('Sur 1 mois', _pct(b['mom_pct'])),
            _row('Sur 1 an', _pct(b['yoy_pct'])),
            _spark(_asList(b['series'])),
            for (final c in _asList(b['components']))
              _row(
                '${c['label_fr']}',
                '${_pct(c['change_12m_pct'])} sur 12 mois',
              ),
            _note('${b['note']}'),
          ],
        ),
      ),
    ];
  }

  List<Widget> _worldSection() {
    final w = _world;
    if (w == null) return const [];
    if (w['status'] != 'ok') {
      return [
        _sectionTitle('Contexte mondial et intrants'),
        _note('${w['reason'] ?? 'Indisponible pour le moment.'}'),
      ];
    }
    final inputs = _asMap(w['inputs']);
    final product = _asMap(w['product']);
    final world = _asMap(product['world']);
    return [
      _sectionTitle('Contexte mondial et intrants'),
      FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (world.isNotEmpty)
              _row(
                'Prix mondial du produit',
                '${world['value']} ${world['unit']} (${_pct(world['yoy_pct'])})',
              ),
            if (product['message'] != null) _note('${product['message']}'),
            for (final key in inputs.keys)
              _row(
                key == 'dap'
                    ? 'Engrais DAP'
                    : (key == 'urea' ? 'Engrais urée' : 'Pétrole brut'),
                '${_asMap(inputs[key])['value']} '
                '(${_pct(_asMap(inputs[key])['yoy_pct'])})',
              ),
            _note('${w['note']}'),
          ],
        ),
      ),
    ];
  }

  List<Widget> _alertsSection() {
    final a = _alerts;
    final rules = a == null ? <Map<String, dynamic>>[] : _asList(a['rules']);
    return [
      _sectionTitle('Mes alertes'),
      FDCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (rules.isEmpty) _note('Aucune alerte pour le moment.'),
            for (final r in rules) _alertRow(r),
            const Divider(height: 24),
            _alertForm(),
          ],
        ),
      ),
    ];
  }

  Widget _alertRow(Map<String, dynamic> rule) {
    final triggered = rule['triggered'] == true;
    final id = '${rule['rule_id']}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Icon(
            triggered
                ? Icons.notifications_active_rounded
                : Icons.notifications_none_rounded,
            size: 18,
            color: triggered ? AppColors.warningDark : AppColors.subtle,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '${rule['message']}',
              style: const TextStyle(fontSize: 13, color: AppColors.body),
            ),
          ),
          if (triggered && rule['kind'] == 'new_data')
            IconButton(
              tooltip: 'Marquer comme lu',
              icon: const Icon(Icons.done_rounded, size: 18),
              onPressed: () {
                _alertAction(() => widget.apiService.ackMarketIntelAlert(id));
              },
            ),
          IconButton(
            tooltip: 'Supprimer',
            icon: const Icon(Icons.delete_outline_rounded, size: 18),
            onPressed: () {
              _alertAction(() => widget.apiService.deleteMarketIntelAlert(id));
            },
          ),
        ],
      ),
    );
  }

  Widget _alertForm() {
    final isPriceKind = _alertKind == 'threshold' || _alertKind == 'gap';
    final directions = isPriceKind ? ['above', 'below'] : ['up', 'down', 'any'];
    if (_alertKind == 'new_data') {
      _alertDirection = 'any';
    } else if (!directions.contains(_alertDirection)) {
      _alertDirection = directions.first;
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Nouvelle alerte sur ce produit',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            DropdownButton<String>(
              value: _alertKind,
              items: const [
                DropdownMenuItem(value: 'threshold', child: Text('Seuil')),
                DropdownMenuItem(
                    value: 'variation', child: Text('Variation %')),
                DropdownMenuItem(value: 'gap', child: Text('Écart médiane %')),
                DropdownMenuItem(
                    value: 'new_data', child: Text('Nouveau mois')),
              ],
              onChanged: (v) => setState(() => _alertKind = v ?? 'threshold'),
            ),
            if (_alertKind != 'new_data')
              DropdownButton<String>(
                value: _alertDirection,
                items: [
                  for (final d in directions)
                    DropdownMenuItem(value: d, child: Text(_directionLabel(d))),
                ],
                onChanged: (v) {
                  setState(() => _alertDirection = v ?? directions.first);
                },
              ),
            if (_alertKind != 'new_data')
              SizedBox(
                width: 130,
                child: TextField(
                  controller: _alertValueCtrl,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(
                    labelText: isPriceKind && _alertKind == 'threshold'
                        ? 'XAF/kg'
                        : '%',
                  ),
                ),
              ),
            if (_alertKind == 'gap')
              SizedBox(
                width: 180,
                child: TextField(
                  controller: _alertMarketCtrl,
                  decoration: const InputDecoration(labelText: 'Marché'),
                ),
              ),
          ],
        ),
        if (_alertError != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              _alertError!,
              style: const TextStyle(color: AppColors.dangerDark),
            ),
          ),
        const SizedBox(height: 10),
        FDPrimaryButton(
          label: 'Créer l’alerte',
          icon: Icons.add_alert_outlined,
          onPressed: _createAlert,
        ),
      ],
    );
  }

  String _directionLabel(String direction) {
    switch (direction) {
      case 'above':
        return 'au-dessus';
      case 'below':
        return 'en dessous';
      case 'up':
        return 'hausse';
      case 'down':
        return 'baisse';
      default:
        return 'les deux';
    }
  }
}
