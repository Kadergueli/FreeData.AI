import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/pdf_download.dart';
import '../services/api_service.dart';
import '../core/utils/error_text.dart';

/// Espace Marché PRO (P3) : Prévisions 4 cultures avec MAPE, Arbitrage inter-provinces,
/// Watchlists & Alertes de prix, et Export CSV institutionnel.
class MarketProScreen extends StatefulWidget {
  final ApiService apiService;
  final bool embedded;
  final void Function(String prompt)? onAskAssistant;

  const MarketProScreen({
    super.key,
    required this.apiService,
    this.embedded = false,
    this.onAskAssistant,
  });

  @override
  State<MarketProScreen> createState() => _MarketProScreenState();
}

class _MarketProScreenState extends State<MarketProScreen> {
  static const Map<String, String> _cropLabels = {
    'millet': 'Mil',
    'sorghum': 'Sorgho rouge',
    'maize': 'Maïs blanc',
    'groundnut_raw': 'Arachide',
    'rice_local': 'Riz local',
    'sesame': 'Sésame',
    'cowpeas': 'Niébé (Haricot)',
  };

  Map<String, dynamic>? _overview;
  Map<String, dynamic>? _radar;
  bool _loading = true;
  bool _creatingWatch = false;
  bool _exportingCsv = false;
  String? _error;

  String _watchCrop = 'millet';
  String _watchDirection = 'above';
  final _thresholdCtrl = TextEditingController();
  final _provinceCtrl = TextEditingController();

  String _arbCrop = 'millet';
  final _arbTransportCtrl = TextEditingController();
  final _arbTonnageCtrl = TextEditingController();
  Map<String, dynamic>? _arbResult;
  bool _loadingArb = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _thresholdCtrl.dispose();
    _provinceCtrl.dispose();
    _arbTransportCtrl.dispose();
    _arbTonnageCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await Future.wait([
        widget.apiService.getMarketProOverview(),
        widget.apiService
            .getAgroCampaignRadar()
            .catchError((_) => const <String, dynamic>{}),
      ]);
      if (!mounted) return;
      setState(() {
        _overview = results[0];
        _radar = results[1].isNotEmpty ? results[1] : null;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = errText(e);
        _loading = false;
      });
    }
  }

  Future<void> _addWatch() async {
    if (_creatingWatch) return;
    final val =
        double.tryParse(_thresholdCtrl.text.trim().replaceAll(',', '.'));
    if (val == null || val <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Saisissez un seuil en XAF/kg valide.')),
      );
      return;
    }
    setState(() => _creatingWatch = true);
    try {
      await widget.apiService.createMarketWatchlist(
        cropId: _watchCrop,
        thresholdXafKg: val,
        direction: _watchDirection,
        province: _provinceCtrl.text.trim(),
      );
      _thresholdCtrl.clear();
      _provinceCtrl.clear();
      await _load();
    } catch (e) {
      if (!mounted) return;
      final userError = errText(e);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(userError)));
    } finally {
      if (mounted) setState(() => _creatingWatch = false);
    }
  }

  Future<void> _deleteWatch(String watchId) async {
    try {
      await widget.apiService.deleteMarketWatchlist(watchId);
      await _load();
    } catch (e) {
      if (!mounted) return;
      final userError = errText(e);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(userError)));
    }
  }

  Future<void> _exportCsv() async {
    if (_exportingCsv) return;
    setState(() => _exportingCsv = true);
    try {
      final bytes = await widget.apiService.downloadMarketProCsv();
      triggerFileDownload(
        bytes,
        'freedata_market_pro.csv',
        'text/csv;charset=utf-8',
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Export CSV institutionnel téléchargé.')),
      );
    } catch (e) {
      if (!mounted) return;
      final userError = errText(e);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(userError)));
    } finally {
      if (mounted) setState(() => _exportingCsv = false);
    }
  }

  void _askAssistantAboutArbitrage({required bool createBusinessPlan}) {
    final result = _arbResult;
    if (result == null || widget.onAskAssistant == null) return;

    final routes = ((result['routes'] as List?) ?? const [])
        .whereType<Map>()
        .take(3)
        .toList();
    if (routes.isEmpty) return;

    final first = routes.first;
    final origin = first['origin_province']?.toString() ?? '';
    final destination = first['dest_province']?.toString() ?? '';
    final routeSummary = routes.map((route) {
      final routeOrigin = route['origin_province'] ?? 'Origine';
      final routeDestination = route['dest_province'] ?? 'Destination';
      final margin =
          route['net_margin_xaf_kg'] ?? route['spread_xaf_kg'] ?? 'N/D';
      final total = route['estimated_net_margin_xaf'] ?? 'N/D';
      final roi = route['roi_pct'] ?? 'N/D';
      return '- $routeOrigin → $routeDestination : '
          'marge nette affichée $margin XAF/kg ; résultat estimé $total XAF ; '
          'ROI $roi %.';
    }).join('\n');

    final commonContext = <String>[
      'Culture : ${_cropLabels[_arbCrop] ?? _arbCrop}.',
      'Transport saisi : ${_arbTransportCtrl.text.trim()} XAF/kg.',
      'Volume saisi : ${_arbTonnageCtrl.text.trim()} tonne(s).',
      "MAPE historique affichée : ${result['historical_mape_pct'] ?? 'N/D'} %.",
      'Résultats du simulateur :',
      routeSummary,
    ].join('\n');

    final prompt = createBusinessPlan
        ? <String>[
            'Prépare un business plan agricole professionnel pour la commercialisation de '
                '${_cropLabels[_arbCrop] ?? _arbCrop}, sur le corridor $origin vers $destination.',
            commonContext,
            'Utilise ces paramètres comme contexte de la simulation affichée, puis recoupe les prix '
                'avec les données observées et les prévisions disponibles dans FreeData.AI. '
                'Distingue les données vérifiées des hypothèses.',
            'Le capital initial ne m’a pas encore été fourni : demande-le avant de produire les '
                'projections financières. Ne suppose aucun capital, coût ou prix manquant.',
          ].join('\n')
        : <String>[
            'Explique les résultats du simulateur d’arbitrage inter-provinces de FreeData.AI.',
            commonContext,
            'Explique clairement la différence entre écart brut, marge nette, résultat total et ROI ; '
                'décris les principaux coûts et risques, explique ce que signifie le MAPE historique, '
                'et distingue les données observées, les prévisions et les hypothèses.',
            'Ne modifie pas les résultats affichés et signale toute limite ou donnée manquante.',
          ].join('\n');

    widget.onAskAssistant!(prompt);
  }

  Future<void> _runArbitrageSim() async {
    if (_loadingArb) return;
    setState(() => _loadingArb = true);
    try {
      final transport =
          double.tryParse(_arbTransportCtrl.text.trim().replaceAll(',', '.'));
      final tonnage =
          double.tryParse(_arbTonnageCtrl.text.trim().replaceAll(',', '.'));
      final res = await widget.apiService.getSpatialArbitrage(
        cropId: _arbCrop,
        transportCostXafKg: transport,
        tonnage: tonnage,
      );
      if (mounted) setState(() => _arbResult = res);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(errText(e))));
      }
    } finally {
      if (mounted) setState(() => _loadingArb = false);
    }
  }

  Future<void> _openCreditPassportAgroDialog() async {
    final provCtrl = TextEditingController(text: 'Logone Occidental');
    final areaCtrl = TextEditingController();
    final loanCtrl = TextEditingController(text: '500000');
    String cropId = 'millet';
    Map<String, dynamic>? result;
    bool loading = false;
    String? err;

    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Credit Passport Agro (3 scénarios DSCR)'),
          content: SizedBox(
            width: 440,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  TextField(
                    controller: provCtrl,
                    decoration: const InputDecoration(labelText: 'Province'),
                  ),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    initialValue: cropId,
                    decoration: const InputDecoration(labelText: 'Culture'),
                    items: _cropLabels.entries
                        .map((e) => DropdownMenuItem(
                            value: e.key, child: Text(e.value)))
                        .toList(),
                    onChanged: (v) =>
                        setDialogState(() => cropId = v ?? 'millet'),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: areaCtrl,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration:
                        const InputDecoration(labelText: 'Superficie (ha)'),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: loanCtrl,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        labelText: 'Montant du prêt demandé (XAF)'),
                  ),
                  if (err != null) ...[
                    const SizedBox(height: 8),
                    Text(err!, style: const TextStyle(color: AppColors.danger)),
                  ],
                  if (result != null) ...[
                    const Divider(height: 20),
                    Text(
                      'Rendement réf. World Bank : ${result!['cereal_yield_mean_2020_2024_kg_ha'] ?? '—'} kg/ha',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    if (result!['dry_years_count'] != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text(
                          'Années sèches historiques : ${result!['dry_years_count']} (${result!['dry_years_frequency'] ?? '—'})',
                          style: const TextStyle(
                              fontSize: 12.5, color: AppColors.muted),
                        ),
                      ),
                    const SizedBox(height: 6),
                    ...(((result!['scenarios'] as List?) ?? const [])
                        .whereType<Map>()
                        .map((s) => Padding(
                              padding: const EdgeInsets.only(bottom: 4),
                              child: Text(
                                '• ${s['description']} : ${s['price_xaf_kg'] ?? '—'} XAF/kg · DSCR ${s['dscr'] ?? '—'}',
                                style: const TextStyle(fontSize: 12.5),
                              ),
                            ))),
                    if ((result!['disclaimer']?.toString() ?? '')
                        .isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text(
                        result!['disclaimer'].toString(),
                        style: const TextStyle(
                            fontSize: 11.5, color: AppColors.muted),
                      ),
                    ],
                  ],
                ],
              ),
            ),
          ),
          actions: [
            if (result != null)
              TextButton.icon(
                icon: const Icon(Icons.copy_rounded, size: 17),
                label: const Text('Copier le résumé'),
                onPressed: () {
                  final scenarios = ((result!['scenarios'] as List?) ??
                          const [])
                      .whereType<Map>()
                      .map((s) =>
                          '- ${s['description']} : ${s['price_xaf_kg'] ?? '—'} XAF/kg · DSCR ${s['dscr'] ?? '—'}')
                      .join('\n');
                  final summary =
                      'Credit Passport Agro — ${provCtrl.text.trim()} ($cropId, ${areaCtrl.text.trim()} ha, prêt ${loanCtrl.text.trim()} XAF)\n'
                      'Rendement réf. World Bank : ${result!['cereal_yield_mean_2020_2024_kg_ha'] ?? '—'} kg/ha\n'
                      '$scenarios\n'
                      '${result!['disclaimer'] ?? ''}';
                  Clipboard.setData(ClipboardData(text: summary));
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                        content: Text('Résumé Credit Passport Agro copié.')),
                  );
                },
              ),
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Fermer'),
            ),
            ElevatedButton(
              onPressed: loading
                  ? null
                  : () async {
                      final area = double.tryParse(
                          areaCtrl.text.trim().replaceAll(',', '.'));
                      final loan = double.tryParse(
                          loanCtrl.text.trim().replaceAll(',', '.'));
                      if (area == null ||
                          area <= 0 ||
                          loan == null ||
                          loan <= 0) {
                        setDialogState(() =>
                            err = 'Superficie et montant valides requis.');
                        return;
                      }
                      setDialogState(() {
                        loading = true;
                        err = null;
                      });
                      try {
                        final res =
                            await widget.apiService.computeAgroCreditPassport(
                          province: provCtrl.text,
                          cropId: cropId,
                          areaHectares: area,
                          loanAmountXaf: loan,
                        );
                        setDialogState(() {
                          result = res;
                          loading = false;
                        });
                      } catch (e) {
                        setDialogState(() {
                          err = errText(e);
                          loading = false;
                        });
                      }
                    },
              child: Text(loading ? 'Calcul…' : 'Calculer DSCR'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final forecasts = ((_overview?['validated_forecasts'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final arbitrage = ((_overview?['arbitrage'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final watchlists = ((_overview?['watchlists'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();

    final body = _loading
        ? const FDLoadingState(message: 'Chargement de l’espace Marché PRO…')
        : _error != null
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 440),
                    child: FDErrorState(message: _error!, onRetry: _load),
                  ),
                ),
              )
            : Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 920),
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      Wrap(
                        spacing: 12,
                        runSpacing: 10,
                        alignment: WrapAlignment.spaceBetween,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          const Text(
                            'Prévisions Delta-Ridge ML (4 cultures validées)',
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink,
                            ),
                          ),
                          Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: [
                              FDSecondaryButton(
                                label: _exportingCsv
                                    ? 'Export…'
                                    : 'Export CSV institutionnel',
                                icon: Icons.download_outlined,
                                onPressed: _exportingCsv ? null : _exportCsv,
                              ),
                              FDPrimaryButton(
                                label: 'Générer Credit Passport Agro',
                                icon: Icons.shield_outlined,
                                onPressed: _openCreditPassportAgroDialog,
                              ),
                            ],
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      LayoutBuilder(
                        builder: (context, constraints) {
                          final w = constraints.maxWidth;
                          final cardW = w >= 760
                              ? (w - 36) / 4
                              : (w >= 340 ? (w - 12) / 2 : w);
                          return Wrap(
                            spacing: 12,
                            runSpacing: 12,
                            children: forecasts.map((f) {
                              final mape = f['historical_mape_pct'];
                              return SizedBox(
                                width: cardW,
                                child: FDCard(
                                  padding: const EdgeInsets.all(14),
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        f['label_fr']?.toString() ?? '',
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w700,
                                          color: AppColors.ink,
                                        ),
                                      ),
                                      const SizedBox(height: 6),
                                      Text(
                                        '${f['predicted_xaf_kg'] ?? '—'} XAF/kg',
                                        style: const TextStyle(
                                          fontSize: 18,
                                          fontWeight: FontWeight.w800,
                                          color: AppColors.blue,
                                        ),
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        mape != null
                                            ? 'MAPE historique : $mape %'
                                            : 'MAPE historique : N/D',
                                        style: const TextStyle(
                                          fontSize: 12,
                                          fontWeight: FontWeight.w600,
                                          color: AppColors.muted,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              );
                            }).toList(),
                          );
                        },
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'Simulateur Arbitrage Inter-Provinces (marge nette & ROI)',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 8),
                      FDCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Wrap(
                              spacing: 10,
                              runSpacing: 10,
                              children: [
                                SizedBox(
                                  width: 180,
                                  child: DropdownButtonFormField<String>(
                                    isExpanded: true,
                                    key: ValueKey(_arbCrop),
                                    initialValue: _arbCrop,
                                    decoration: const InputDecoration(
                                        labelText: 'Culture'),
                                    items: _cropLabels.entries
                                        .map((e) => DropdownMenuItem(
                                            value: e.key, child: Text(e.value)))
                                        .toList(),
                                    onChanged: (v) => setState(
                                        () => _arbCrop = v ?? 'millet'),
                                  ),
                                ),
                                SizedBox(
                                  width: 170,
                                  child: TextField(
                                    controller: _arbTransportCtrl,
                                    keyboardType:
                                        const TextInputType.numberWithOptions(
                                            decimal: true),
                                    decoration: const InputDecoration(
                                        labelText: 'Transport réel (XAF/kg)'),
                                  ),
                                ),
                                SizedBox(
                                  width: 150,
                                  child: TextField(
                                    controller: _arbTonnageCtrl,
                                    keyboardType:
                                        const TextInputType.numberWithOptions(
                                            decimal: true),
                                    decoration: const InputDecoration(
                                        labelText: 'Tonnage prévu (t)'),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 10),
                            FDPrimaryButton(
                              label: _loadingArb
                                  ? 'Calcul…'
                                  : 'Calculer écart / marge',
                              icon: Icons.calculate_outlined,
                              onPressed: _loadingArb ? null : _runArbitrageSim,
                            ),
                            if (_arbResult != null) ...[
                              const SizedBox(height: 10),
                              Text(
                                'MAPE historique modèle : ${_arbResult!['historical_mape_pct'] ?? 'N/D'} %',
                                style: const TextStyle(
                                    fontSize: 12.5,
                                    fontWeight: FontWeight.w600,
                                    color: AppColors.muted),
                              ),
                              const SizedBox(height: 6),
                              ...(((_arbResult!['routes'] as List?) ?? const [])
                                  .take(3)
                                  .whereType<Map>()
                                  .map((r) => Padding(
                                        padding:
                                            const EdgeInsets.only(bottom: 4),
                                        child: Text(
                                          '• ${r['origin_province']} → ${r['dest_province']} : '
                                          '${r['net_margin_xaf_kg'] == null ? 'écart brut' : 'marge après transport saisi'} '
                                          '${r['net_margin_xaf_kg'] ?? r['spread_xaf_kg']} XAF/kg'
                                          ' · Résultat total ${r['estimated_net_margin_xaf'] ?? 'non calculé'} XAF'
                                          ' · ROI ${r['roi_pct'] == null ? 'non calculé' : '${r['roi_pct']} %'}'
                                          ' · ${r['commercial_signal'] ?? 'signal non évalué'}',
                                          style: const TextStyle(
                                              fontSize: 12.5,
                                              color: AppColors.ink),
                                        ),
                                      ))),
                              if ((_arbResult!['recommendations'] as List?)?.isNotEmpty == true) ...[
                                const SizedBox(height: 6),
                                Text(
                                  ((_arbResult!['recommendations'] as List).take(3)).join(' '),
                                  style: const TextStyle(fontSize: 11.5, color: AppColors.muted),
                                ),
                              ],
                              if (widget.onAskAssistant != null &&
                                  (((_arbResult!['routes'] as List?) ??
                                          const [])
                                      .isNotEmpty)) ...[
                                const SizedBox(height: 8),
                                Wrap(
                                  spacing: 8,
                                  runSpacing: 8,
                                  children: [
                                    FDSecondaryButton(
                                      label: 'Expliquer avec l’IA',
                                      icon: Icons.auto_awesome_outlined,
                                      onPressed: () =>
                                          _askAssistantAboutArbitrage(
                                        createBusinessPlan: false,
                                      ),
                                    ),
                                    FDSecondaryButton(
                                      label: 'Créer un business plan',
                                      icon: Icons.description_outlined,
                                      onPressed: () =>
                                          _askAssistantAboutArbitrage(
                                        createBusinessPlan: true,
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ],
                          ],
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'Arbitrage inter-provinces (écarts bruts)',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 8),
                      if (arbitrage.isEmpty)
                        const FDCard(
                          child: Text(
                            'Aucun écart inter-provinces significatif détecté.',
                            style: TextStyle(color: AppColors.muted),
                          ),
                        )
                      else
                        ...arbitrage.map((a) => Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: FDCard(
                                padding: const EdgeInsets.all(14),
                                child: Row(
                                  children: [
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            '${a['label_fr']} : ${a['origin_province']} → ${a['dest_province']}',
                                            style: const TextStyle(
                                              fontWeight: FontWeight.w700,
                                              color: AppColors.ink,
                                            ),
                                          ),
                                          const SizedBox(height: 3),
                                          Text(
                                            '${a['origin_predicted_xaf_kg']} → ${a['dest_predicted_xaf_kg']} XAF/kg (${a['forecast_month'] ?? ''})',
                                            style: const TextStyle(
                                              fontSize: 12.5,
                                              color: AppColors.muted,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                    FDBadge(
                                      label: '+${a['spread_xaf_kg']} XAF',
                                      color: AppColors.greenDark,
                                      backgroundColor: AppColors.greenSoft,
                                    ),
                                  ],
                                ),
                              ),
                            )),
                      const SizedBox(height: 16),
                      const Text(
                        'Watchlists & Alertes de seuils de prix',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 8),
                      FDCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Wrap(
                              spacing: 10,
                              runSpacing: 10,
                              children: [
                                SizedBox(
                                  width: 180,
                                  child: DropdownButtonFormField<String>(
                                    isExpanded: true,
                                    key: ValueKey(_watchCrop),
                                    initialValue: _watchCrop,
                                    decoration: const InputDecoration(
                                        labelText: 'Culture'),
                                    items: _cropLabels.entries
                                        .map((e) => DropdownMenuItem(
                                            value: e.key, child: Text(e.value)))
                                        .toList(),
                                    onChanged: (v) => setState(
                                        () => _watchCrop = v ?? 'millet'),
                                  ),
                                ),
                                SizedBox(
                                  width: 170,
                                  child: DropdownButtonFormField<String>(
                                    isExpanded: true,
                                    key: ValueKey(_watchDirection),
                                    initialValue: _watchDirection,
                                    decoration: const InputDecoration(
                                        labelText: 'Condition'),
                                    items: const [
                                      DropdownMenuItem(
                                          value: 'above',
                                          child: Text('Supérieur ou égal')),
                                      DropdownMenuItem(
                                          value: 'below',
                                          child: Text('Inférieur ou égal')),
                                    ],
                                    onChanged: (v) => setState(
                                        () => _watchDirection = v ?? 'above'),
                                  ),
                                ),
                                SizedBox(
                                  width: 160,
                                  child: TextField(
                                    controller: _thresholdCtrl,
                                    keyboardType:
                                        const TextInputType.numberWithOptions(
                                            decimal: true),
                                    decoration: const InputDecoration(
                                        labelText: 'Seuil (XAF/kg)'),
                                  ),
                                ),
                                SizedBox(
                                  width: 180,
                                  child: TextField(
                                    controller: _provinceCtrl,
                                    decoration: const InputDecoration(
                                        labelText: 'Province (opt.)'),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            FDPrimaryButton(
                              label: _creatingWatch
                                  ? 'Ajout…'
                                  : 'Ajouter l’alerte',
                              icon: Icons.notifications_active_outlined,
                              onPressed: _creatingWatch ? null : _addWatch,
                            ),
                            if (watchlists.isNotEmpty) ...[
                              const Divider(height: 24),
                              ...watchlists.map((w) {
                                final trig = w['triggered'] == true;
                                return ListTile(
                                  dense: true,
                                  contentPadding: EdgeInsets.zero,
                                  leading: Icon(
                                    trig
                                        ? Icons.notifications_active_rounded
                                        : Icons.notifications_none_rounded,
                                    color: trig
                                        ? AppColors.danger
                                        : AppColors.muted,
                                  ),
                                  title: Text(
                                    '${w['label_fr']} ${w['direction'] == 'above' ? '≥' : '≤'} ${w['threshold_xaf_kg']} XAF/kg'
                                    '${(w['province']?.toString().isNotEmpty ?? false) ? ' · ${w['province']}' : ''}',
                                    style: const TextStyle(
                                        fontWeight: FontWeight.w600),
                                  ),
                                  subtitle: Text(
                                    'Prévu : ${w['predicted_xaf_kg'] ?? '—'} XAF/kg · ${trig ? 'ALERTE DÉCLENCHÉE' : 'Sous surveillance'}',
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: trig
                                          ? AppColors.danger
                                          : AppColors.muted,
                                    ),
                                  ),
                                  trailing: IconButton(
                                    icon: const Icon(
                                        Icons.delete_outline_rounded,
                                        color: AppColors.danger,
                                        size: 19),
                                    onPressed: () =>
                                        _deleteWatch(w['watch_id'].toString()),
                                  ),
                                );
                              }),
                            ],
                          ],
                        ),
                      ),
                      if (_radar != null &&
                          ((_radar!['hubs'] as List?) ?? const [])
                              .isNotEmpty) ...[
                        const SizedBox(height: 16),
                        _buildCampaignRadarCard(_radar!),
                      ],
                      const SizedBox(height: 14),
                      const FDCard(
                        padding: EdgeInsets.all(14),
                        child: Text(
                          'Sources & Licences : WFP (CC BY-IGO 3.0) · FEWS NET (Attribution Required) · NASA POWER Agro (Public Domain) · World Bank (CC BY 4.0)',
                          style: TextStyle(
                            fontSize: 12,
                            color: AppColors.muted,
                            height: 1.4,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              );
    if (widget.embedded) {
      return Container(color: AppColors.canvas, child: body);
    }
    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
        title: const Text(
          'Marché PRO — Watchlists & Arbitrage',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      body: body,
    );
  }

  Widget _buildCampaignRadarCard(Map<String, dynamic> radar) {
    final summary = radar['summary'] is Map
        ? Map<String, dynamic>.from(radar['summary'] as Map)
        : const <String, dynamic>{};
    final hubs = ((radar['hubs'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Wrap(
            spacing: 8,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                'Radar National Agro-Marché (Alerte Précoce & Campagne)',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppColors.ink,
                ),
              ),
              FDBadge(
                label: 'NASA POWER + DELTA-RIDGE ML',
                color: AppColors.greenDark,
                backgroundColor: AppColors.greenSoft,
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              FDBadge(
                label:
                    'Pôles analysés : ${summary['hubs_count'] ?? hubs.length}',
                color: AppColors.blue,
                backgroundColor: AppColors.blueSoft,
              ),
              FDBadge(
                label:
                    'Double vulnérabilité : ${summary['double_vulnerability_count'] ?? 0}',
                color:
                    ((summary['double_vulnerability_count'] as num?) ?? 0) > 0
                        ? AppColors.danger
                        : AppColors.greenDark,
                backgroundColor:
                    ((summary['double_vulnerability_count'] as num?) ?? 0) > 0
                        ? const Color(0xFFFEE2E2)
                        : AppColors.greenSoft,
              ),
              if (summary['top_opportunity_hub'] != null)
                FDBadge(
                  label:
                      'Top opportunité : ${summary['top_opportunity_hub']} (${summary['top_opportunity_crop'] ?? ''})',
                  color: AppColors.greenDark,
                  backgroundColor: AppColors.greenSoft,
                ),
            ],
          ),
          const SizedBox(height: 12),
          LayoutBuilder(
            builder: (context, constraints) {
              if (constraints.maxWidth < 760) {
                return Column(
                  children: hubs
                      .map((hub) => Padding(
                            padding: const EdgeInsets.only(bottom: 10),
                            child: _buildCampaignRadarHubCard(hub),
                          ))
                      .toList(),
                );
              }
              return SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Container(
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: const Color(0xFFCBD5E1)),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: DataTable(
                    headingRowColor:
                        WidgetStateProperty.all(const Color(0xFFF0F9FF)),
                    columnSpacing: 16,
                    horizontalMargin: 12,
                    columns: const [
                      DataColumn(label: Text('Pôle / Province')),
                      DataColumn(label: Text('Anomalie Eau')),
                      DataColumn(label: Text('Années sèches')),
                      DataColumn(label: Text('Meilleure Culture')),
                      DataColumn(label: Text('CA / ha (ML t+1)')),
                      DataColumn(label: Text('Risque Crédit')),
                      DataColumn(label: Text('Alerte')),
                    ],
                    rows: hubs.map((h) {
                      final best = h['best_crop'] is Map
                          ? h['best_crop'] as Map
                          : const {};
                      final anom = h['root_anomaly_pct'];
                      final dbl = h['double_vulnerability'] == true;
                      final risk = h['credit_risk_level']?.toString() ?? '—';
                      return DataRow(cells: [
                        DataCell(Text(
                            '${h['region']} (${h['province'] ?? '—'})',
                            style:
                                const TextStyle(fontWeight: FontWeight.w600))),
                        DataCell(Text(anom != null ? '$anom %' : '—')),
                        DataCell(Text(
                            '${h['critical_july_aug_years'] ?? 0} (${h['dry_year_freq_pct'] ?? 0}%)')),
                        DataCell(Text('${best['label_fr'] ?? '—'}')),
                        DataCell(Text(best['ca_per_ha_xaf'] != null
                            ? '${best['ca_per_ha_xaf']} F'
                            : '—')),
                        DataCell(Text(risk,
                            style: TextStyle(
                              fontWeight: FontWeight.w700,
                              color: risk == 'Élevé'
                                  ? AppColors.danger
                                  : (risk == 'Modéré'
                                      ? AppColors.warning
                                      : AppColors.greenDark),
                            ))),
                        DataCell(dbl
                            ? const FDBadge(
                                label: 'DOUBLE VULNÉRABILITÉ',
                                color: AppColors.danger,
                                backgroundColor: Color(0xFFFEE2E2),
                              )
                            : const Text('Normal',
                                style: TextStyle(color: AppColors.muted))),
                      ]);
                    }).toList(),
                  ),
                ),
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _buildCampaignRadarHubCard(Map<String, dynamic> hub) {
    final best = hub['best_crop'] is Map
        ? Map<String, dynamic>.from(hub['best_crop'] as Map)
        : const <String, dynamic>{};
    final anomaly = hub['root_anomaly_pct'];
    final dryYears = hub['critical_july_aug_years'] ?? 0;
    final dryFrequency = hub['dry_year_freq_pct'] ?? 0;
    final revenue = best['ca_per_ha_xaf'];
    final risk = hub['credit_risk_level']?.toString() ?? '—';
    final doubleVulnerability = hub['double_vulnerability'] == true;
    final riskColor = risk == 'Élevé'
        ? AppColors.danger
        : (risk == 'Modéré' ? AppColors.warning : AppColors.greenDark);

    Widget metric(String label, String value) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 9),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label,
                style: const TextStyle(
                    fontSize: 11.5,
                    color: AppColors.muted,
                    fontWeight: FontWeight.w500)),
            const SizedBox(height: 2),
            Text(value,
                style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.ink,
                    fontWeight: FontWeight.w600)),
          ],
        ),
      );
    }

    return FDCard(
      padding: const EdgeInsets.all(13),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${hub['region'] ?? 'Pôle non renseigné'}',
            style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: AppColors.ink),
          ),
          Text(
            'Province : ${hub['province'] ?? '—'}',
            style: const TextStyle(fontSize: 12, color: AppColors.muted),
          ),
          const Divider(height: 18),
          Wrap(
            spacing: 18,
            runSpacing: 4,
            children: [
              SizedBox(
                width: 125,
                child: metric(
                    'Anomalie Eau', anomaly != null ? '$anomaly %' : '—'),
              ),
              SizedBox(
                width: 125,
                child: metric('Années sèches', '$dryYears ($dryFrequency %)'),
              ),
              SizedBox(
                width: 125,
                child:
                    metric('Meilleure Culture', '${best['label_fr'] ?? '—'}'),
              ),
              SizedBox(
                width: 125,
                child: metric(
                    'CA / ha (ML t+1)', revenue != null ? '$revenue F' : '—'),
              ),
            ],
          ),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text('Risque Crédit : $risk',
                  style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w700,
                      color: riskColor)),
              if (doubleVulnerability)
                const FDBadge(
                  label: 'DOUBLE VULNÉRABILITÉ',
                  color: AppColors.danger,
                  backgroundColor: Color(0xFFFEE2E2),
                )
              else
                const Text('Alerte : Normal',
                    style: TextStyle(fontSize: 12, color: AppColors.muted)),
            ],
          ),
        ],
      ),
    );
  }
}
