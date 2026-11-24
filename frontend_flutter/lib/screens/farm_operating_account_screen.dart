import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import '../core/utils/error_text.dart';

class FarmOperatingAccountScreen extends StatefulWidget {
  final ApiService apiService;
  final void Function(String prompt)? onSelectPrompt;
  final String? initialProvince;
  final String? initialCropId;
  final double? initialAreaHectares;
  final double? initialDiscountPct;

  const FarmOperatingAccountScreen({
    super.key,
    required this.apiService,
    this.onSelectPrompt,
    this.initialProvince,
    this.initialCropId,
    this.initialAreaHectares,
    this.initialDiscountPct,
  });

  @override
  State<FarmOperatingAccountScreen> createState() =>
      _FarmOperatingAccountScreenState();
}

class _FarmOperatingAccountScreenState
    extends State<FarmOperatingAccountScreen> {
  static const _provinces = <String>[
    "N'Djamena",
    'Logone Occidental',
    'Logone Oriental',
    'Moyen-Chari',
    'Mandoul',
    'Mayo-Kebbi Est',
    'Mayo-Kebbi Ouest',
    'Guera',
    'Ouaddai',
    'Batha',
    'Kanem',
    'Lac',
  ];

  static const _crops = <({String id, String label})>[
    (id: 'millet', label: 'Mil'),
    (id: 'sorghum', label: 'Sorgho'),
    (id: 'maize', label: 'Maïs'),
    (id: 'groundnut_raw', label: 'Arachide'),
    (id: 'cowpeas', label: 'Niébé'),
    (id: 'sesame', label: 'Sésame'),
    (id: 'rice_local', label: 'Riz local'),
  ];

  late String _province;
  late String _cropId;
  late final TextEditingController _areaCtrl;
  final _yieldCtrl = TextEditingController();
  late final TextEditingController _discCtrl;

  // Les charges restent vides tant que l'opérateur ne les a pas déclarées.
  final _seedCtrl = TextEditingController();
  final _fertCtrl = TextEditingController();
  final _laborCtrl = TextEditingController();
  final _prepCtrl = TextEditingController();
  final _harvestCtrl = TextEditingController();
  final _otherCtrl = TextEditingController();

  // CAPEX & Financement
  final _capexCtrl = TextEditingController(text: '0');
  final _loanCtrl = TextEditingController(text: '0');
  final _rateCtrl = TextEditingController(text: '12');

  bool _loading = false;
  String? _error;
  Map<String, dynamic>? _result;

  @override
  void initState() {
    super.initState();
    _province = _provinces.contains(widget.initialProvince)
        ? widget.initialProvince!
        : "N'Djamena";
    _cropId = _crops.any((c) => c.id == widget.initialCropId)
        ? widget.initialCropId!
        : 'millet';
    _areaCtrl = TextEditingController(
      text: (widget.initialAreaHectares != null &&
              widget.initialAreaHectares! > 0)
          ? widget.initialAreaHectares!.toString()
          : '2.0',
    );
    _discCtrl = TextEditingController(
      text: (widget.initialDiscountPct ?? 8.0).toStringAsFixed(0),
    );
  }

  @override
  void dispose() {
    _areaCtrl.dispose();
    _yieldCtrl.dispose();
    _discCtrl.dispose();
    _seedCtrl.dispose();
    _fertCtrl.dispose();
    _laborCtrl.dispose();
    _prepCtrl.dispose();
    _harvestCtrl.dispose();
    _otherCtrl.dispose();
    _capexCtrl.dispose();
    _loanCtrl.dispose();
    _rateCtrl.dispose();
    super.dispose();
  }

  double? _parseNumber(TextEditingController c) {
    final raw = c.text.trim();
    if (raw.isEmpty) return null;
    final value = double.tryParse(raw.replaceAll(',', '.'));
    return value != null && value.isFinite ? value : null;
  }

  double _num(TextEditingController c, [double fallback = 0]) =>
      _parseNumber(c) ?? fallback;

  Future<void> _compute() async {
    final area = _parseNumber(_areaCtrl);
    final discount = _parseNumber(_discCtrl);
    final opexFields = <String, TextEditingController>{
      'Semences': _seedCtrl,
      'Engrais & intrants': _fertCtrl,
      'Main-d’œuvre': _laborCtrl,
      'Préparation du sol & irrigation': _prepCtrl,
      'Récolte & sacs': _harvestCtrl,
      'Autres charges': _otherCtrl,
    };
    String? validationError;
    if (area == null || area <= 0 || area > 500000) {
      validationError = 'Saisissez une superficie valide, supérieure à 0 et inférieure ou égale à 500 000 ha.';
    } else if (discount == null || discount < 0 || discount > 50) {
      validationError = 'La décote bord-champ doit être comprise entre 0 et 50 %.';
    } else {
      for (final entry in opexFields.entries) {
        final value = _parseNumber(entry.value);
        if (value == null || value < 0 || value > 50000000) {
          validationError = 'Renseignez un montant valide pour « ${entry.key} » (0 à 50 000 000 FCFA/ha).';
          break;
        }
      }
    }
    final numericFields = <TextEditingController>[_capexCtrl, _loanCtrl, _rateCtrl];
    if (validationError == null) {
      for (final field in numericFields) {
        final value = _parseNumber(field);
        if (value == null || value < 0) {
          validationError = 'Vérifiez les montants de CAPEX, de prêt et le taux d’intérêt.';
          break;
        }
      }
    }
    final targetYield = _yieldCtrl.text.trim().isEmpty ? null : _parseNumber(_yieldCtrl);
    if (validationError == null && _yieldCtrl.text.trim().isNotEmpty &&
        (targetYield == null || targetYield <= 0 || targetYield > 50000)) {
      validationError = 'Le rendement cible doit être compris entre 0 et 50 000 kg/ha.';
    }
    if (validationError != null) {
      setState(() {
        _error = validationError;
        _result = null;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      setState(() {
        _loading = true;
        _error = null;
        _result = null;
      });
      final res = await widget.apiService.computeFarmOperatingAccount(
        province: _province,
        cropId: _cropId,
        areaHectares: area!,
        targetYieldKgHa: targetYield,
        farmgateDiscountPct: discount!,
        seedCostPerHaXaf: _num(_seedCtrl),
        fertilizerCostPerHaXaf: _num(_fertCtrl),
        laborCostPerHaXaf: _num(_laborCtrl),
        landPrepIrrigationPerHaXaf: _num(_prepCtrl),
        harvestPostharvestPerHaXaf: _num(_harvestCtrl),
        otherOpexPerHaXaf: _num(_otherCtrl),
        capexTotalXaf: _num(_capexCtrl),
        loanAmountXaf: _num(_loanCtrl),
        interestRatePct: _num(_rateCtrl, 12),
      );
      if (!mounted) return;
      setState(() {
        _result = res;
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

  void _askAssistantAboutFarmAccount({required bool createBusinessPlan}) {
    final result = _result;
    if (result == null || widget.onSelectPrompt == null) return;

    final scenarios = (result['scenarios'] as List? ?? const [])
        .whereType<Map>()
        .map((scenario) {
      final label = scenario['label'] ?? 'Scénario';
      final price = scenario['farmgate_price_xaf_kg'] ?? 'N/D';
      final revenue = scenario['gross_revenue_xaf'] ?? 'N/D';
      final ebitda = scenario['ebitda_margin_xaf'] ?? 'N/D';
      final net = scenario['net_profit_after_capex_xaf'] ?? 'N/D';
      final roi = scenario['roi_on_opex_pct'] ?? 'N/D';
      final dscr = scenario['dscr'] ?? 'N/D';
      return '- $label : prix bord-champ $price XAF/kg ; CA $revenue XAF ; '
          'marge EBITDA $ebitda XAF ; résultat net $net XAF ; ROI OPEX $roi % ; DSCR $dscr.';
    }).join('\n');

    final commonContext = <String>[
      'Province : ${result['province'] ?? _province}.',
      'Culture : ${result['label_fr'] ?? _cropId}.',
      'Superficie : ${result['area_hectares'] ?? _areaCtrl.text.trim()} ha.',
      'Rendement : ${result['yield_kg_ha'] ?? 'N/D'} kg/ha ; source : ${result['yield_source'] ?? 'non précisée'}.',
      'Production estimée : ${result['production_kg'] ?? 'N/D'} kg.',
      'OPEX total : ${result['opex_total_xaf'] ?? 'N/D'} XAF.',
      'CAPEX initial saisi : ${result['capex_total_xaf'] ?? 'N/D'} XAF.',
      'Investissement total : ${result['total_investment_xaf'] ?? 'N/D'} XAF.',
      'Prêt demandé : ${_num(_loanCtrl)} XAF ; taux saisi : ${_num(_rateCtrl, 12)} %. ',
      'Seuil de rentabilité OPEX : ${result['breakeven_price_opex_xaf_kg'] ?? 'N/D'} XAF/kg.',
      'Rendement au point mort : ${result['breakeven_yield_kg_ha'] ?? 'N/D'} kg/ha.',
      'Scénarios calculés :',
      scenarios.isEmpty ? 'Aucun scénario détaillé disponible.' : scenarios,
      'Notes de transparence : ${(result['investor_readiness_notes'] as List? ?? const []).join('; ')}',
    ].join('\n');

    final prompt = createBusinessPlan
        ? <String>[
            'Prépare un business plan agricole et un dossier de financement pour cette exploitation.',
            commonContext,
            if ((_num(_capexCtrl) <= 0) && (_num(_loanCtrl) <= 0))
              'Le capital initial et le financement ne sont pas renseignés : demande le capital réellement disponible et les besoins de financement avant toute projection financière.',
            'Utilise les résultats du compte d’exploitation comme données de départ, pas comme preuves indépendantes. '
                'Distingue les coûts déclarés, les données de marché observées, les prévisions et les hypothèses.',
            'Ne fabrique aucun prix, rendement, coût, taux, calendrier ou source. Signale les informations manquantes et les risques agronomiques, commerciaux et financiers.',
          ].join('\n')
        : <String>[
            'Explique le compte d’exploitation agricole et la rentabilité de cette parcelle.',
            commonContext,
            'Explique la différence entre chiffre d’affaires, OPEX, marge EBITDA, résultat net après CAPEX, ROI, DSCR et seuil de rentabilité.',
            'Analyse les écarts entre scénarios, les postes de coûts qui pèsent le plus et la sensibilité au prix bord-champ et au rendement.',
            'Ne modifie pas les chiffres du simulateur. Sépare clairement les valeurs saisies, les références de marché, les prévisions et les limites de calcul.',
          ].join('\n');

    widget.onSelectPrompt!(prompt);
  }

  String _fmtXaf(dynamic val) {
    if (val is num) {
      final s = val.round().toString();
      final buf = StringBuffer();
      for (var i = 0; i < s.length; i++) {
        if (i > 0 && (s.length - i) % 3 == 0 && s[i - 1] != '-') {
          buf.write(' ');
        }
        buf.write(s[i]);
      }
      return '$buf FCFA';
    }
    return '—';
  }

  Widget _numField(TextEditingController ctrl, String label, {double w = 175}) {
    return SizedBox(
      width: w,
      child: TextField(
        controller: ctrl,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(labelText: label, isDense: true),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final res = _result;
    final breakdown = (res?['opex_breakdown'] as List?) ?? const [];
    final scenarios = (res?['scenarios'] as List?) ?? const [];
    final notes = (res?['investor_readiness_notes'] as List?) ?? const [];
    final opexTotal = (res?['opex_total_xaf'] as num?)?.toDouble() ?? 0.0;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Compte d’Exploitation Agricole (OPEX / CAPEX & Rentabilité Nette)',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'Estimez la rentabilité de votre parcelle avant d’engager vos dépenses. Saisissez vos coûts réels ; les références de marché et les rendements indicatifs sont signalés séparément.',
                      style: TextStyle(fontSize: 12.5, color: AppColors.muted),
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      '1. Paramètres de la parcelle & rendement',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.blue,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        SizedBox(
                          width: 195,
                          child: DropdownButtonFormField<String>(
                            isExpanded: true,
                            initialValue: _province,
                            decoration: const InputDecoration(
                              labelText: 'Province',
                              isDense: true,
                            ),
                            items: _provinces
                                .map((p) => DropdownMenuItem(
                                      value: p,
                                      child: Text(p,
                                          overflow: TextOverflow.ellipsis),
                                    ))
                                .toList(),
                            onChanged: (v) {
                              if (v != null) setState(() => _province = v);
                            },
                          ),
                        ),
                        SizedBox(
                          width: 165,
                          child: DropdownButtonFormField<String>(
                            isExpanded: true,
                            initialValue: _cropId,
                            decoration: const InputDecoration(
                              labelText: 'Culture',
                              isDense: true,
                            ),
                            items: _crops
                                .map((c) => DropdownMenuItem(
                                      value: c.id,
                                      child: Text(c.label,
                                          overflow: TextOverflow.ellipsis),
                                    ))
                                .toList(),
                            onChanged: (v) {
                              if (v != null) setState(() => _cropId = v);
                            },
                          ),
                        ),
                        _numField(_areaCtrl, 'Superficie (ha)', w: 135),
                        _numField(_yieldCtrl, 'Rendement cible (kg/ha, opt.)',
                            w: 210),
                        _numField(_discCtrl, 'Décote bord-champ (%)', w: 165),
                      ],
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      '2. Charges opérationnelles OPEX (FCFA / hectare)',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.blue,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'Renseignez chaque poste. Saisissez 0 uniquement si vous confirmez que cette charge est réellement nulle ; une case vide bloque le calcul.',
                      style: TextStyle(fontSize: 11.5, color: AppColors.muted),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        _numField(_seedCtrl, 'Semences / ha (FCFA)'),
                        _numField(_fertCtrl, 'Engrais & phyto / ha (FCFA)'),
                        _numField(_laborCtrl, 'Main-d’œuvre / ha (FCFA)'),
                        _numField(_prepCtrl, 'Labour & irrigation / ha (FCFA)'),
                        _numField(_harvestCtrl, 'Récolte & sacs / ha (FCFA)'),
                        _numField(_otherCtrl, 'Autres charges / ha (FCFA)'),
                      ],
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      '3. Investissement CAPEX & Financement (optionnel)',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.blue,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        _numField(_capexCtrl, 'CAPEX initial total (FCFA)',
                            w: 210),
                        _numField(_loanCtrl, 'Montant prêt demandé (FCFA)',
                            w: 210),
                        _numField(_rateCtrl, 'Taux intérêt (%)', w: 140),
                      ],
                    ),
                    const SizedBox(height: 14),
                    FDPrimaryButton(
                      label: _loading
                          ? 'Calcul en cours…'
                          : 'Calculer le Compte d’Exploitation',
                      icon: Icons.assessment_outlined,
                      onPressed: _loading ? null : _compute,
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 8),
                      Text(
                        _error!,
                        style: const TextStyle(
                          color: AppColors.danger,
                          fontSize: 12.5,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (res != null) ...[
                const SizedBox(height: 14),
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Compte de Résultat Prévisionnel — ${res['label_fr']} · ${res['province']} (${res['area_hectares']} ha)',
                        style: const TextStyle(
                          fontSize: 15.5,
                          fontWeight: FontWeight.w800,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Production : ${res['production_kg']} kg (${res['yield_kg_ha']} kg/ha · ${res['yield_source']})',
                        style: const TextStyle(
                            fontSize: 12.5, color: AppColors.muted),
                      ),
                      const SizedBox(height: 10),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: AppColors.canvas,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: AppColors.line),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Traçabilité des données de marché',
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w700,
                                color: AppColors.ink,
                              ),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              'Historique : ${res['history_reference_month'] ?? 'indisponible'} · ${res['history_data_scope'] == 'province' ? 'province sélectionnée' : res['history_data_scope'] == 'national_fallback' ? 'repli national' : 'aucune donnée'} · ${res['history_rows_used'] ?? 0} observations.',
                              style: const TextStyle(fontSize: 11.5, color: AppColors.muted),
                            ),
                            Text(
                              'Prévision : ${res['forecast_reference_month'] ?? 'indisponible'} · ${res['forecast_data_scope'] == 'province' ? 'province sélectionnée' : res['forecast_data_scope'] == 'national_fallback' ? 'repli national' : 'aucune donnée'} · ${res['forecast_rows_used'] ?? 0} lignes.',
                              style: const TextStyle(fontSize: 11.5, color: AppColors.muted),
                            ),
                            Text(
                              'Sources historiques : ${(res['history_sources'] as List? ?? const []).join(', ').isEmpty ? 'non précisées' : (res['history_sources'] as List).join(', ')}',
                              style: const TextStyle(fontSize: 11.5, color: AppColors.muted),
                            ),
                            Text(
                              'Sources des prévisions : ${(res['forecast_sources'] as List? ?? const []).join(', ').isEmpty ? 'non précisées' : (res['forecast_sources'] as List).join(', ')}',
                              style: const TextStyle(fontSize: 11.5, color: AppColors.muted),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 10,
                        runSpacing: 8,
                        children: [
                          _kpiChip(
                              'OPEX Total', _fmtXaf(res['opex_total_xaf'])),
                          _kpiChip(
                              'CAPEX Initial', _fmtXaf(res['capex_total_xaf'])),
                          _kpiChip('Invest. Total',
                              _fmtXaf(res['total_investment_xaf'])),
                          _kpiChip('Point Mort OPEX',
                              '${res['breakeven_price_opex_xaf_kg'] ?? '—'} F/kg'),
                          _kpiChip('Rendement Point Mort',
                              '${res['breakeven_yield_kg_ha'] ?? '—'} kg/ha'),
                        ],
                      ),
                      if (breakdown.isNotEmpty && opexTotal > 0) ...[
                        const SizedBox(height: 14),
                        const Text(
                          'Structure des coûts OPEX',
                          style: TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 6),
                        for (final b in breakdown.whereType<Map>()) ...[
                          Builder(builder: (_) {
                            final tot =
                                (b['total_xaf'] as num?)?.toDouble() ?? 0;
                            final pct = (tot / opexTotal).clamp(0.0, 1.0);
                            return Padding(
                              padding: const EdgeInsets.only(bottom: 6),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    mainAxisAlignment:
                                        MainAxisAlignment.spaceBetween,
                                    children: [
                                      Text(
                                        b['category']?.toString() ?? '',
                                        style: const TextStyle(fontSize: 12),
                                      ),
                                      Text(
                                        '${_fmtXaf(tot)} (${(pct * 100).toStringAsFixed(0)}%)',
                                        style: const TextStyle(
                                          fontSize: 12,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 3),
                                  ClipRRect(
                                    borderRadius: BorderRadius.circular(99),
                                    child: LinearProgressIndicator(
                                      value: pct,
                                      minHeight: 6,
                                      backgroundColor: AppColors.canvasSoft,
                                      color: AppColors.blue,
                                    ),
                                  ),
                                ],
                              ),
                            );
                          }),
                        ],
                      ],
                      const SizedBox(height: 14),
                      const Text(
                        'Résultat Net sous 3 Scénarios de Marché',
                        style: TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 6),
                      for (final sc in scenarios.whereType<Map>())
                        Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: AppColors.canvas,
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: AppColors.line),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      '${sc['label']} · Bord-champ : ${sc['farmgate_price_xaf_kg'] ?? '—'} F/kg',
                                      style: const TextStyle(
                                        fontSize: 12.5,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                  ),
                                  Text(
                                    'Net : ${_fmtXaf(sc['net_profit_after_capex_xaf'])}',
                                    style: TextStyle(
                                      fontSize: 12.5,
                                      fontWeight: FontWeight.w800,
                                      color: (sc['net_profit_after_capex_xaf']
                                                      as num? ??
                                                  0) >=
                                              0
                                          ? AppColors.greenDark
                                          : AppColors.danger,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 3),
                              Text(
                                'CA Brut : ${_fmtXaf(sc['gross_revenue_xaf'])} · Marge OPEX (EBITDA) : ${_fmtXaf(sc['ebitda_margin_xaf'])} · ROI OPEX : ${sc['roi_on_opex_pct'] ?? '—'}%${sc['dscr'] != null ? ' · DSCR : ${sc['dscr']}' : ''}',
                                style: const TextStyle(
                                  fontSize: 12,
                                  color: AppColors.muted,
                                ),
                              ),
                            ],
                          ),
                        ),
                      if (notes.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        const Text(
                          'Transparence Comité d’Investissement',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 4),
                        for (final n in notes)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 3),
                            child: Text('• $n',
                                style: const TextStyle(
                                    fontSize: 12, color: AppColors.muted)),
                          ),
                      ],
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          if (widget.onSelectPrompt != null)
                            FDSecondaryButton(
                              label: 'Expliquer avec l’IA',
                              icon: Icons.auto_awesome_outlined,
                              onPressed: () => _askAssistantAboutFarmAccount(
                                createBusinessPlan: false,
                              ),
                            ),
                          if (widget.onSelectPrompt != null)
                            FDSecondaryButton(
                              label: 'Créer un business plan',
                              icon: Icons.description_outlined,
                              onPressed: () => _askAssistantAboutFarmAccount(
                                createBusinessPlan: true,
                              ),
                            ),
                          FDSecondaryButton(
                            label: 'Copier la synthèse investisseur',
                            icon: Icons.copy_rounded,
                            onPressed: () async {
                              final cScen =
                                  scenarios.length > 1 && scenarios[1] is Map
                                      ? scenarios[1] as Map
                                      : const {};
                              final summary =
                                  'Compte d’Exploitation FreeData.td — ${res['label_fr']} (${res['province']}, ${res['area_hectares']} ha)\n'
                                  '• Production : ${res['production_kg']} kg (${res['yield_kg_ha']} kg/ha)\n'
                                  '• OPEX Total : ${_fmtXaf(res['opex_total_xaf'])} | CAPEX : ${_fmtXaf(res['capex_total_xaf'])}\n'
                                  '• Point Mort OPEX : ${res['breakeven_price_opex_xaf_kg'] ?? '—'} F/kg\n'
                                  '• Scénario Central ML : CA ${_fmtXaf(cScen['gross_revenue_xaf'])} | Net ${_fmtXaf(cScen['net_profit_after_capex_xaf'])} (ROI ${cScen['roi_on_opex_pct'] ?? '—'}%)';
                              await Clipboard.setData(
                                  ClipboardData(text: summary));
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content:
                                      Text('Synthèse investisseur copiée !'),
                                ),
                              );
                            },
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _kpiChip(String label, String value) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: AppColors.blueSoft,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          '$label : $value',
          style: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: AppColors.blueDark,
          ),
        ),
      );
}
