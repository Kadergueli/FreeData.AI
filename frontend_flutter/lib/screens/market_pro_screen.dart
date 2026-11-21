import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/pdf_download.dart';
import '../services/api_service.dart';

/// Espace Marché PRO (P3) : Prévisions 4 cultures avec MAPE, Arbitrage inter-provinces,
/// Watchlists & Alertes de prix, et Export CSV institutionnel.
class MarketProScreen extends StatefulWidget {
  final ApiService apiService;
  final bool embedded;

  const MarketProScreen({
    super.key,
    required this.apiService,
    this.embedded = false,
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
  };

  Map<String, dynamic>? _overview;
  bool _loading = true;
  bool _creatingWatch = false;
  bool _exportingCsv = false;
  String? _error;

  String _watchCrop = 'millet';
  String _watchDirection = 'above';
  final _thresholdCtrl = TextEditingController();
  final _provinceCtrl = TextEditingController();

  String _arbCrop = 'millet';
  final _arbTransportCtrl = TextEditingController(text: '35');
  final _arbTonnageCtrl = TextEditingController(text: '10');
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
      final data = await widget.apiService.getMarketProOverview();
      if (!mounted) return;
      setState(() {
        _overview = data;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
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
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
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
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _exportCsv() async {
    if (_exportingCsv) return;
    setState(() => _exportingCsv = true);
    try {
      final bytes = await widget.apiService.downloadMarketProCsv();
      triggerPdfDownload(bytes, 'freedata_market_pro.csv');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Export CSV institutionnel téléchargé.')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _exportingCsv = false);
    }
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
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _loadingArb = false);
    }
  }

  Future<void> _openCreditPassportAgroDialog() async {
    final provCtrl = TextEditingController(text: 'Logone Occidental');
    final areaCtrl = TextEditingController(text: '5');
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
                    if ((result!['disclaimer']?.toString() ?? '').isNotEmpty) ...[
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
                  final scenarios = ((result!['scenarios'] as List?) ?? const [])
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
                          err = '$e';
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
                      if (widget.embedded)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Align(
                            alignment: Alignment.centerRight,
                            child: FDSecondaryButton(
                              label: _exportingCsv
                                  ? 'Export…'
                                  : 'Export CSV institutionnel',
                              icon: Icons.download_outlined,
                              onPressed: _exportingCsv ? null : _exportCsv,
                            ),
                          ),
                        ),
                      Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Expanded(
                              child: Text(
                                'Prévisions Delta-Ridge ML (4 cultures validées)',
                                style: TextStyle(
                                  fontSize: 15,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.ink,
                                ),
                              ),
                            ),
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                FDSecondaryButton(
                                  label:
                                      _exportingCsv ? 'Export…' : 'Export CSV',
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
                        const SizedBox(height: 10),
                        Wrap(
                          spacing: 12,
                          runSpacing: 12,
                          children: forecasts.map((f) {
                            final mape = f['historical_mape_pct'];
                            return SizedBox(
                              width: 210,
                              child: FDCard(
                                padding: const EdgeInsets.all(14),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
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
                                        fontSize: 19,
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
                                      key: ValueKey(_arbCrop),
                                      initialValue: _arbCrop,
                                      decoration: const InputDecoration(
                                          labelText: 'Culture'),
                                      items: _cropLabels.entries
                                          .map((e) => DropdownMenuItem(
                                              value: e.key,
                                              child: Text(e.value)))
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
                                          labelText: 'Transport (XAF/kg)'),
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
                                          labelText: 'Tonnage (t)'),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 10),
                              FDPrimaryButton(
                                label: _loadingArb
                                    ? 'Calcul…'
                                    : 'Simuler marge & ROI',
                                icon: Icons.calculate_outlined,
                                onPressed:
                                    _loadingArb ? null : _runArbitrageSim,
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
                                ...(((_arbResult!['routes'] as List?) ??
                                        const [])
                                    .take(3)
                                    .whereType<Map>()
                                    .map((r) => Padding(
                                          padding:
                                              const EdgeInsets.only(bottom: 4),
                                          child: Text(
                                            '• ${r['origin_province']} → ${r['dest_province']} : marge nette ${r['net_margin_xaf_kg'] ?? r['spread_xaf_kg']} XAF/kg · Total ${r['estimated_net_margin_xaf'] ?? '—'} XAF · ROI ${r['roi_pct'] ?? '—'} %',
                                            style: const TextStyle(
                                                fontSize: 12.5,
                                                color: AppColors.ink),
                                          ),
                                        ))),
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
                                      key: ValueKey(_watchCrop),
                                      initialValue: _watchCrop,
                                      decoration: const InputDecoration(
                                          labelText: 'Culture'),
                                      items: _cropLabels.entries
                                          .map((e) => DropdownMenuItem(
                                              value: e.key,
                                              child: Text(e.value)))
                                          .toList(),
                                      onChanged: (v) => setState(
                                          () => _watchCrop = v ?? 'millet'),
                                    ),
                                  ),
                                  SizedBox(
                                    width: 170,
                                    child: DropdownButtonFormField<String>(
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
                                      onPressed: () => _deleteWatch(
                                          w['watch_id'].toString()),
                                    ),
                                  );
                                }),
                              ],
                            ],
                          ),
                        ),
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
        actions: [
          IconButton(
            tooltip: 'Export CSV institutionnel',
            icon: const Icon(Icons.download_outlined),
            onPressed: _exportingCsv ? null : _exportCsv,
          ),
        ],
      ),
      body: body,
    );
  }
}
