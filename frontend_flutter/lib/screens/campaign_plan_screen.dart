import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import '../core/utils/error_text.dart';

class CampaignPlanScreen extends StatefulWidget {
  final ApiService apiService;
  final void Function(String prompt)? onSelectPrompt;

  const CampaignPlanScreen({
    super.key,
    required this.apiService,
    this.onSelectPrompt,
  });

  @override
  State<CampaignPlanScreen> createState() => _CampaignPlanScreenState();
}

class _CampaignPlanScreenState extends State<CampaignPlanScreen> {
  static const _profiles = <({
    String id,
    String label,
    int defaultMonths,
    IconData icon,
  })>[
    (
      id: 'petit_commercant',
      label: 'Petit commerçant',
      defaultMonths: 1,
      icon: Icons.storefront_outlined,
    ),
    (
      id: 'stockeur_saisonnier',
      label: 'Stockeur saisonnier',
      defaultMonths: 6,
      icon: Icons.warehouse_outlined,
    ),
    (
      id: 'grossiste_arbitragiste',
      label: 'Grossiste / Coop',
      defaultMonths: 2,
      icon: Icons.local_shipping_outlined,
    ),
    (
      id: 'investisseur',
      label: 'Investisseur',
      defaultMonths: 6,
      icon: Icons.trending_up_rounded,
    ),
  ];

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
    (id: '', label: 'Auto (meilleure opportunité)'),
    (id: 'millet', label: 'Mil'),
    (id: 'sorghum', label: 'Sorgho'),
    (id: 'maize', label: 'Maïs'),
    (id: 'groundnut_raw', label: 'Arachide'),
    (id: 'cowpeas', label: 'Niébé'),
    (id: 'sesame', label: 'Sésame'),
    (id: 'rice_local', label: 'Riz local'),
  ];

  String _status = 'petit_commercant';
  String _province = "N'Djamena";
  String _cropId = '';
  final _capitalCtrl = TextEditingController();
  bool _capitalEdited = false;
  final _monthsCtrl = TextEditingController(text: '1');
  final _coroCtrl = TextEditingController(text: '2.5');
  final _transportCtrl = TextEditingController(text: '0');
  final _storageCtrl = TextEditingController(text: '0');
  final _lossCtrl = TextEditingController(text: '0');

  bool _loading = false;
  String? _error;
  Map<String, dynamic>? _result;

  @override
  void dispose() {
    _capitalCtrl.dispose();
    _monthsCtrl.dispose();
    _coroCtrl.dispose();
    _transportCtrl.dispose();
    _storageCtrl.dispose();
    _lossCtrl.dispose();
    super.dispose();
  }

  double? _parseNumber(TextEditingController controller) =>
      double.tryParse(controller.text.trim().replaceAll(',', '.'));

  Future<void> _runSimulation() async {
    final cap = _parseNumber(_capitalCtrl);
    final months = int.tryParse(_monthsCtrl.text.trim());
    final coro = _parseNumber(_coroCtrl);
    final transport = _parseNumber(_transportCtrl);
    final storage = _parseNumber(_storageCtrl);
    final losses = _parseNumber(_lossCtrl);

    String? validationError;
    if (cap == null || !cap.isFinite || cap <= 0) {
      validationError = 'Saisissez un capital valide supérieur à 0 FCFA.';
    } else if (months == null || months < 1 || months > 12) {
      validationError = 'L’horizon doit être un nombre entier entre 1 et 12 mois.';
    } else if (coro == null || !coro.isFinite || coro < 0.5 || coro > 10) {
      validationError = 'Le poids du coro doit être compris entre 0,5 et 10 kg.';
    } else if (transport == null || !transport.isFinite || transport < 0) {
      validationError = 'Le transport par sac doit être un montant positif ou nul.';
    } else if (storage == null || !storage.isFinite || storage < 0) {
      validationError = 'Le stockage par sac et par mois doit être positif ou nul.';
    } else if (losses == null || !losses.isFinite || losses < 0 || losses > 40) {
      validationError = 'Les pertes doivent être comprises entre 0 et 40 %.';
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
      _result = null;
    });
    try {
      final res = await widget.apiService.computeCampaignPlan(
        capitalXaf: cap!,
        originProvince: _province,
        entrepreneurStatus: _status,
        cropId: _cropId.isEmpty ? null : _cropId,
        holdingMonths: months,
        coroWeightKg: coro!,
        transportPerBagXaf: transport!,
        storagePerBagMonthXaf: storage!,
        lossPct: losses!,
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

  void _askAssistantAboutCampaign({required bool createBusinessPlan}) {
    final result = _result;
    final recommendation = result?['recommended_plan'] as Map<String, dynamic>?;
    if (result == null ||
        recommendation == null ||
        widget.onSelectPrompt == null) {
      return;
    }

    final profile = _profiles
        .firstWhere(
          (item) => item.id == _status,
          orElse: () => _profiles.first,
        )
        .label;
    final crop = _crops
        .firstWhere(
          (item) => item.id == _cropId,
          orElse: () => _crops.first,
        )
        .label;
    final scenarios = ((recommendation['scenarios'] as List?) ?? const [])
        .whereType<Map>()
        .map((scenario) {
      return '- ${scenario['label'] ?? 'Scénario'} : prix de vente ${scenario['sell_price_xaf_kg'] ?? 'N/D'} XAF/kg ; résultat net ${scenario['net_profit_xaf'] ?? 'N/D'} XAF ; ROI ${scenario['roi_pct'] ?? 'N/D'} %.';
    }).join('\n');

    final capitalContext = _capitalEdited
        ? 'Capital saisi par l’utilisateur : ${_capitalCtrl.text.trim()} XAF.'
        : 'Le champ capital contient encore sa valeur initiale préremplie : le capital réel de l’utilisateur n’est pas confirmé. Ne traite pas cette valeur par défaut comme un budget validé ; demande le capital réellement disponible avant un business plan.';
    final commonContext = <String>[
      'Profil : $profile.',
      'Province de départ : ${result['origin_province'] ?? _province}.',
      'Culture choisie : $crop.',
      capitalContext,
      'Horizon : ${_monthsCtrl.text.trim()} mois.',
      'Poids du coro : ${_coroCtrl.text.trim()} kg.',
      'Transport par sac : ${_transportCtrl.text.trim()} XAF.',
      'Stockage par sac et par mois : ${_storageCtrl.text.trim()} XAF.',
      'Pertes déclarées : ${_lossCtrl.text.trim()} %. ',
      'Recommandation : ${recommendation['label_fr'] ?? 'N/D'} ; signal : ${recommendation['timing_label'] ?? 'N/D'} ; percentile historique : ${recommendation['percentile_rank_pct'] ?? 'N/D'} %.',
      'Quantité : ${recommendation['bags_count'] ?? 'N/D'} sacs de 100 kg ; équivalent : ${recommendation['coros_equiv'] ?? 'N/D'} coros.',
      'Prix d’achat : ${recommendation['buy_price_xaf_kg'] ?? 'N/D'} XAF/kg ; point mort : ${recommendation['breakeven_price_xaf_kg'] ?? 'N/D'} XAF/kg.',
      'Réserve de trésorerie : ${recommendation['cash_reserve_xaf'] ?? 'N/D'} XAF.',
      'Calendrier : achat optimal ${(recommendation['cheapest_months'] as List? ?? const []).join(', ')} ; pic historique ${(recommendation['peak_months'] as List? ?? const []).join(', ')} ; sortie visée ${recommendation['target_exit_month'] ?? 'N/D'}.',
      'Scénarios calculés :',
      scenarios.isEmpty ? 'Aucun scénario détaillé disponible.' : scenarios,
    ].join('\n');

    final prompt = createBusinessPlan
        ? <String>[
            'Prépare un business plan commercial agricole structuré à partir de ce plan de campagne FreeData.AI.',
            commonContext,
            if (!_capitalEdited)
              'Avant les projections financières, demande et confirme le capital réellement disponible. Ne réutilise pas la valeur préremplie comme un montant confirmé.',
            'Présente le modèle économique, le besoin en fonds de roulement, les achats, le stockage, le transport, les pertes, les ventes, la trésorerie, les risques et des scénarios prudent, central et favorable.',
            'Recoupe les prix avec les données observées et les prévisions disponibles. Cite les sources, indique leur date et distingue les observations des prévisions et hypothèses.',
            'Ne crée aucun prix, coût, volume, calendrier ou rendement absent des données.',
          ].join('\n')
        : <String>[
            'Explique la recommandation et les résultats de ce plan de campagne agricole.',
            commonContext,
            if (!_capitalEdited)
              'Le simulateur a utilisé une valeur de capital préremplie non confirmée. Ne la présente pas comme le capital réellement disponible.',
            'Explique le prix d’achat, le point mort, la réserve de trésorerie, le calendrier saisonnier, la marge nette et le ROI des scénarios.',
            'Analyse la sensibilité au prix de vente, aux frais de transport, au stockage et aux pertes.',
            'Ne modifie pas les résultats calculés. Distingue les données historiques, les prix observés, les prévisions et les hypothèses.',
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

  @override
  Widget build(BuildContext context) {
    final rec = _result?['recommended_plan'] as Map<String, dynamic>?;
    final advice = (_result?['strategic_advice'] as List?) ?? const [];
    final allOpps = (_result?['all_opportunities'] as List?) ?? const [];

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
                      'Plan de Campagne & Investissement (Cycle Céréalier Tchad)',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w800,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'Construisez une stratégie d’achat, de stockage et de revente à partir de votre capital réel, des prix observés et des hypothèses de coûts.',
                      style: TextStyle(fontSize: 12.5, color: AppColors.muted),
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      '1. Votre statut d’entrepreneur',
                      style: TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final p in _profiles)
                          ChoiceChip(
                            avatar: Icon(p.icon, size: 16),
                            label: Text(p.label),
                            selected: _status == p.id,
                            onSelected: (_) {
                              setState(() {
                                _status = p.id;
                                _monthsCtrl.text = p.defaultMonths.toString();
                              });
                            },
                          ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        SizedBox(
                          width: 210,
                          child: TextField(
                            controller: _capitalCtrl,
                            keyboardType: TextInputType.number,
                            onChanged: (value) => _capitalEdited =
                                (double.tryParse(value.trim()) ?? 0) > 0,
                            decoration: const InputDecoration(
                              labelText: 'Capital réellement disponible (FCFA)',
                              isDense: true,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 210,
                          child: DropdownButtonFormField<String>(
                            isExpanded: true,
                            initialValue: _province,
                            decoration: const InputDecoration(
                              labelText: 'Marché / Province',
                              isDense: true,
                            ),
                            items: _provinces
                                .map((pr) => DropdownMenuItem(
                                      value: pr,
                                      child: Text(pr,
                                          overflow: TextOverflow.ellipsis),
                                    ))
                                .toList(),
                            onChanged: (v) {
                              if (v != null) setState(() => _province = v);
                            },
                          ),
                        ),
                        SizedBox(
                          width: 220,
                          child: DropdownButtonFormField<String>(
                            isExpanded: true,
                            initialValue: _cropId,
                            decoration: const InputDecoration(
                              labelText: 'Produit / Céréale',
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
                        SizedBox(
                          width: 150,
                          child: TextField(
                            controller: _monthsCtrl,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(
                              labelText: 'Horizon (1 à 12 mois)',
                              isDense: true,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 130,
                          child: TextField(
                            controller: _coroCtrl,
                            keyboardType: const TextInputType.numberWithOptions(
                                decimal: true),
                            decoration: const InputDecoration(
                              labelText: 'Poids du coro (kg)',
                              isDense: true,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 170,
                          child: TextField(
                            controller: _transportCtrl,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(
                              labelText: 'Transport / sac (XAF)',
                              isDense: true,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 185,
                          child: TextField(
                            controller: _storageCtrl,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(
                              labelText: 'Stockage / sac / mois (XAF)',
                              isDense: true,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 130,
                          child: TextField(
                            controller: _lossCtrl,
                            keyboardType: const TextInputType.numberWithOptions(
                                decimal: true),
                            decoration: const InputDecoration(
                              labelText: 'Pertes (%)',
                              isDense: true,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    FDPrimaryButton(
                      label: _loading
                          ? 'Calcul du plan en cours…'
                          : 'Simuler mon Plan de Campagne',
                      icon: Icons.calculate_outlined,
                      onPressed: _loading ? null : _runSimulation,
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 10),
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
              if (_result != null && rec == null) ...[
                const SizedBox(height: 14),
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Aucune opportunité suffisamment viable',
                        style: TextStyle(
                          fontSize: 15.5,
                          fontWeight: FontWeight.w800,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        _result?['recommendation_message']?.toString() ??
                            'Aucune recommandation ne satisfait les critères de rentabilité et de capital disponible.',
                        style: const TextStyle(
                          fontSize: 12.5,
                          color: AppColors.muted,
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Vérifiez le capital, les frais de transport et de stockage, les pertes déclarées et la disponibilité des prix locaux avant de relancer la simulation.',
                        style: TextStyle(
                          fontSize: 12.5,
                          color: AppColors.inkSoft,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              if (rec != null) ...[
                const SizedBox(height: 14),
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              'Recommandation principale : ${rec['label_fr']} (${_result?['origin_province']})',
                              style: const TextStyle(
                                fontSize: 15.5,
                                fontWeight: FontWeight.w800,
                                color: AppColors.ink,
                              ),
                            ),
                          ),
                          FDBadge(
                            label: rec['timing_signal'] == 'fenetre_achat'
                                ? 'FENÊTRE D’ACHAT'
                                : (rec['timing_signal'] == 'pic_eleve'
                                    ? 'PRIX ÉLEVÉ'
                                    : 'ZONE NEUTRE'),
                            color: rec['timing_signal'] == 'fenetre_achat'
                                ? AppColors.greenDark
                                : (rec['timing_signal'] == 'pic_eleve'
                                    ? AppColors.danger
                                    : AppColors.blue),
                            backgroundColor:
                                rec['timing_signal'] == 'fenetre_achat'
                                    ? AppColors.greenSoft
                                    : (rec['timing_signal'] == 'pic_eleve'
                                        ? AppColors.dangerSoft
                                        : AppColors.blueSoft),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text(
                        '${rec['timing_label']} (percentile historique : ${rec['percentile_rank_pct']}%)',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.inkSoft,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 12,
                        runSpacing: 8,
                        children: [
                          _metricChip(
                              'Sacs 100 kg', '${rec['bags_count']} sacs'),
                          _metricChip('Équivalent Coros',
                              '${rec['coros_equiv']} coros (${rec['coro_weight_kg']} kg)'),
                          _metricChip('Prix achat',
                              '${rec['buy_price_xaf_kg']} F/kg (${_fmtXaf(rec['buy_price_bag_100kg_xaf'])}/sac)'),
                          _metricChip('Point mort',
                              '${rec['breakeven_price_xaf_kg']} F/kg'),
                          _metricChip(
                              'Réserve cash', _fmtXaf(rec['cash_reserve_xaf'])),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'Calendrier saisonnier : achat le plus bas en ${(rec['cheapest_months'] as List?)?.join(', ') ?? '—'} · pic historique en ${(rec['peak_months'] as List?)?.join(', ') ?? '—'} · sortie visée (${rec['holding_months']} mois) : ${rec['target_exit_month'] ?? '—'}',
                        style: const TextStyle(
                          fontSize: 12.5,
                          color: AppColors.muted,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'Qualité des données : ${rec['data_scope'] == 'province' ? 'prix de la province sélectionnée' : 'repli sur une autre zone pour cette denrée'} · ${rec['history_observations'] ?? '—'} observations · ${rec['history_year_count'] ?? '—'} années couvertes.',
                        style: const TextStyle(
                          fontSize: 11.5,
                          color: AppColors.muted,
                        ),
                      ),
                      if (rec['used_national_fallback'] == true)
                        const Padding(
                          padding: EdgeInsets.only(top: 4),
                          child: Text(
                            'Attention : les prix ne proviennent pas de la province sélectionnée. Cette estimation ne doit pas être considérée comme un prix local.',
                            style: TextStyle(
                              fontSize: 11.5,
                              color: AppColors.danger,
                            ),
                          ),
                        ),
                      const SizedBox(height: 12),
                      const Text(
                        'Scénarios de sortie temporelle',
                        style: TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 6),
                      for (final sc in ((rec['scenarios'] as List?) ?? const [])
                          .whereType<Map>())
                        Container(
                          margin: const EdgeInsets.only(bottom: 6),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: AppColors.canvas,
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: AppColors.line),
                          ),
                          child: Row(
                            children: [
                              Expanded(
                                child: Text(
                                  '${sc['label']} (${sc['sell_price_xaf_kg']} F/kg)',
                                  style: const TextStyle(
                                    fontSize: 12.5,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                              Text(
                                'Net : ${_fmtXaf(sc['net_profit_xaf'])} (${sc['roi_pct']}%)',
                                style: TextStyle(
                                  fontSize: 12.5,
                                  fontWeight: FontWeight.w700,
                                  color:
                                      (sc['net_profit_xaf'] as num? ?? 0) >= 0
                                          ? AppColors.greenDark
                                          : AppColors.danger,
                                ),
                              ),
                            ],
                          ),
                        ),
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          if (widget.onSelectPrompt != null)
                            FDSecondaryButton(
                              label: 'Expliquer avec l’IA',
                              icon: Icons.auto_awesome_outlined,
                              onPressed: () => _askAssistantAboutCampaign(
                                createBusinessPlan: false,
                              ),
                            ),
                          if (widget.onSelectPrompt != null)
                            FDSecondaryButton(
                              label: 'Créer un business plan',
                              icon: Icons.description_outlined,
                              onPressed: () => _askAssistantAboutCampaign(
                                createBusinessPlan: true,
                              ),
                            ),
                          FDSecondaryButton(
                            label: 'Copier le résumé WhatsApp',
                            icon: Icons.copy_rounded,
                            onPressed: () async {
                              final txt =
                                  rec['whatsapp_summary']?.toString() ?? '';
                              if (txt.isEmpty) return;
                              await Clipboard.setData(ClipboardData(text: txt));
                              if (!context.mounted) return;
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content: Text(
                                      'Plan de campagne copié pour WhatsApp !'),
                                ),
                              );
                            },
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                if (advice.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  FDCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Accompagnement stratégique (${_result?['entrepreneur_label']})',
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 6),
                        for (final a in advice)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Text('• $a',
                                style: const TextStyle(fontSize: 12.5)),
                          ),
                      ],
                    ),
                  ),
                ],
                if (allOpps.length > 1) ...[
                  const SizedBox(height: 12),
                  FDCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Comparatif des produits disponibles',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 6),
                        for (final o in allOpps.whereType<Map>())
                          Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Text(
                              '• ${o['label_fr']} : ${o['buy_price_xaf_kg']} F/kg (${o['bags_count']} sacs) · ${o['timing_label']} · Score ${o['opportunity_score']}/100',
                              style: const TextStyle(fontSize: 12.5),
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _metricChip(String label, String value) => Container(
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
