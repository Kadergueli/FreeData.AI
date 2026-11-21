import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/formatters.dart';
import '../core/utils/pdf_download.dart';
import '../services/api_service.dart';
import '../widgets/auth_dialog.dart';

/// Espace Agronome PRO — Diagnostic de terrain (pré-achat) & Rapport PDF co-brandé.
class AgronomistProScreen extends StatefulWidget {
  final ApiService apiService;
  final List<String> availableHubs;
  final String? initialHub;

  const AgronomistProScreen({
    super.key,
    required this.apiService,
    this.availableHubs = const [
      'Abeche',
      'Ati',
      'Bol',
      'Bongor',
      'Doba',
      'Koumra',
      'Mao',
      'Mongo',
      'Moundou',
      "N'Djamena",
      'Pala',
      'Sarh',
    ],
    this.initialHub,
  });

  @override
  State<AgronomistProScreen> createState() => _AgronomistProScreenState();
}

class _AgronomistProScreenState extends State<AgronomistProScreen> {
  static const Map<String, String> _cropLabels = {
    'millet': 'Mil',
    'sorghum': 'Sorgho rouge',
    'maize': 'Maïs blanc',
    'groundnut_raw': 'Arachide',
  };

  static const List<Map<String, String>> _textures = [
    {'id': '', 'label': 'Non mesurée'},
    {'id': 'sandy', 'label': 'Sableux'},
    {'id': 'sandy_loam', 'label': 'Sablo-limoneux'},
    {'id': 'loamy', 'label': 'Limoneux'},
    {'id': 'clay_loam', 'label': 'Argilo-limoneux'},
    {'id': 'clay', 'label': 'Argileux'},
    {'id': 'silty', 'label': 'Limon fin'},
  ];

  late String _hub;
  String _texture = '';
  final Set<String> _selectedCrops = {
    'millet',
    'sorghum',
    'maize',
    'groundnut_raw',
  };
  final _phCtrl = TextEditingController();
  final _omCtrl = TextEditingController();
  final _nCtrl = TextEditingController();
  final _pCtrl = TextEditingController();
  final _kCtrl = TextEditingController();
  final _areaCtrl = TextEditingController();
  final _latCtrl = TextEditingController();
  final _lonCtrl = TextEditingController();
  final _notesCtrl = TextEditingController();
  final _firmCtrl = TextEditingController();

  bool _submitting = false;
  bool _downloadingPdf = false;
  Map<String, dynamic>? _result;
  List<Map<String, dynamic>> _history = const [];

  bool get _hasAccess =>
      widget.apiService.isAuthenticated && widget.apiService.hasPremiumKey;

  @override
  void initState() {
    super.initState();
    final hubs = widget.availableHubs;
    _hub = (widget.initialHub != null && hubs.contains(widget.initialHub))
        ? widget.initialHub!
        : (hubs.contains("N'Djamena") ? "N'Djamena" : hubs.first);
    if (_hasAccess) {
      _loadHistory();
    }
  }

  @override
  void dispose() {
    _phCtrl.dispose();
    _omCtrl.dispose();
    _nCtrl.dispose();
    _pCtrl.dispose();
    _kCtrl.dispose();
    _areaCtrl.dispose();
    _latCtrl.dispose();
    _lonCtrl.dispose();
    _notesCtrl.dispose();
    _firmCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadHistory() async {
    try {
      final list = await widget.apiService.listAgroFieldAssessments();
      if (mounted) setState(() => _history = list);
    } catch (_) {}
  }

  double? _parseOpt(TextEditingController ctrl) {
    final t = ctrl.text.trim().replaceAll(',', '.');
    if (t.isEmpty) return null;
    return double.tryParse(t);
  }

  Future<void> _submit() async {
    if (_submitting) return;
    if (!widget.apiService.isAuthenticated) {
      await showDialog<bool>(
        context: context,
        builder: (_) => AuthDialog(apiService: widget.apiService),
      );
      if (!mounted) return;
      setState(() {});
      return;
    }
    if (_selectedCrops.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Sélectionnez au moins une culture.')),
      );
      return;
    }

    final lab = <String, dynamic>{};
    final ph = _parseOpt(_phCtrl);
    final om = _parseOpt(_omCtrl);
    final n = _parseOpt(_nCtrl);
    final p = _parseOpt(_pCtrl);
    final k = _parseOpt(_kCtrl);
    if (ph != null) lab['ph'] = ph;
    if (_texture.isNotEmpty) lab['texture'] = _texture;
    if (om != null) lab['organic_matter'] = om;
    if (n != null) lab['nitrogen'] = n;
    if (p != null) lab['phosphorus'] = p;
    if (k != null) lab['potassium'] = k;

    setState(() => _submitting = true);
    try {
      final res = await widget.apiService.createAgroFieldAssessment(
        provinceHub: _hub,
        gpsLat: _parseOpt(_latCtrl),
        gpsLon: _parseOpt(_lonCtrl),
        areaHectares: _parseOpt(_areaCtrl),
        labSoilInputs: lab,
        agronomistFieldNotes: _notesCtrl.text,
        targetCrops: _selectedCrops.toList(),
      );
      if (!mounted) return;
      setState(() {
        _result = res;
      });
      await _loadHistory();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _downloadPdf(String assessmentId, String code) async {
    if (_downloadingPdf) return;
    setState(() => _downloadingPdf = true);
    try {
      final bytes = await widget.apiService.downloadAgroAssessmentPdf(
        assessmentId,
        agronomistName: _firmCtrl.text,
      );
      triggerPdfDownload(bytes, 'freedata_agro_$code.pdf');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Rapport PDF co-brandé généré ($code).')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _downloadingPdf = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final assessment = _result?['assessment'] is Map
        ? Map<String, dynamic>.from(_result!['assessment'] as Map)
        : null;
    final qa = _result?['qa'] is Map
        ? Map<String, dynamic>.from(_result!['qa'] as Map)
        : null;

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
        title: const Text(
          'Agronome PRO — Diagnostic de terrain',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 880),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (!widget.apiService.isAuthenticated ||
                  !widget.apiService.hasPremiumKey) ...[
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const FDBadge(
                        label: 'ESPACE AGRONOME PRO',
                        color: AppColors.greenDark,
                        backgroundColor: AppColors.greenSoft,
                      ),
                      const SizedBox(height: 10),
                      const Text(
                        'Diagnostic de terrain (pré-achat) & Rapport PDF co-brandé',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'Saisissez vos mesures de sol laboratoire (pH, texture, NPK, matière organique), croisez-les avec l’humidité zonale NASA POWER et les prix de marché, et générez un rapport PDF signé avec code de vérification unique.',
                        style: TextStyle(
                          fontSize: 13.5,
                          color: AppColors.muted,
                          height: 1.45,
                        ),
                      ),
                      const SizedBox(height: 12),
                      if (!widget.apiService.isAuthenticated)
                        FDPrimaryButton(
                          label: 'Se connecter',
                          icon: Icons.login_rounded,
                          onPressed: () async {
                            await showDialog<bool>(
                              context: context,
                              builder: (_) =>
                                  AuthDialog(apiService: widget.apiService),
                            );
                            if (mounted) setState(() {});
                          },
                        )
                      else
                        const Text(
                          'Activez l’offre PRO depuis l’onglet Abonnement & Quotas pour débloquer cet outil.',
                          style: TextStyle(
                            fontWeight: FontWeight.w600,
                            color: AppColors.blue,
                          ),
                        ),
                    ],
                  ),
                ),
              ] else ...[
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '1. Localisation & Mesures laboratoire de la parcelle',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'Vos analyses restent strictement privées sur votre compte. Sans mesure de sol, seul un pré-diagnostic régional est produit (le PDF terrain est bloqué par la porte QA).',
                        style:
                            TextStyle(fontSize: 12.5, color: AppColors.muted),
                      ),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        key: ValueKey(_hub),
                        initialValue: _hub,
                        decoration:
                            const InputDecoration(labelText: 'Pôle régional'),
                        items: widget.availableHubs
                            .map((h) =>
                                DropdownMenuItem(value: h, child: Text(h)))
                            .toList(),
                        onChanged: (v) {
                          if (v != null) setState(() => _hub = v);
                        },
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: _areaCtrl,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                labelText: 'Superficie (ha)',
                              ),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: TextField(
                              controller: _latCtrl,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true, signed: true),
                              decoration: const InputDecoration(
                                labelText: 'Latitude GPS (opt.)',
                              ),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: TextField(
                              controller: _lonCtrl,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true, signed: true),
                              decoration: const InputDecoration(
                                labelText: 'Longitude GPS (opt.)',
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: _phCtrl,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                labelText: 'pH du sol (labo)',
                                hintText: 'Ex. 6.2',
                              ),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: DropdownButtonFormField<String>(
                              key: ValueKey(_texture),
                              initialValue: _texture,
                              isExpanded: true,
                              decoration: const InputDecoration(
                                labelText: 'Texture du sol',
                              ),
                              items: _textures
                                  .map((t) => DropdownMenuItem(
                                      value: t['id'], child: Text(t['label']!)))
                                  .toList(),
                              onChanged: (v) =>
                                  setState(() => _texture = v ?? ''),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: TextField(
                              controller: _omCtrl,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                labelText: 'Mat. organique (%)',
                                hintText: 'Ex. 1.8',
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: _nCtrl,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                  labelText: 'Azote N (opt.)'),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: TextField(
                              controller: _pCtrl,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                  labelText: 'Phosphore P (opt.)'),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: TextField(
                              controller: _kCtrl,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                  labelText: 'Potassium K (opt.)'),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Cultures cibles (4 cultures avec modèles prix validés)',
                        style: TextStyle(
                            fontSize: 12.5,
                            fontWeight: FontWeight.w600,
                            color: AppColors.muted),
                      ),
                      const SizedBox(height: 6),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: _cropLabels.entries.map((e) {
                          final sel = _selectedCrops.contains(e.key);
                          return FilterChip(
                            label: Text(e.value),
                            selected: sel,
                            onSelected: (v) => setState(() {
                              if (v) {
                                _selectedCrops.add(e.key);
                              } else {
                                _selectedCrops.remove(e.key);
                              }
                            }),
                          );
                        }).toList(),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _firmCtrl,
                        decoration: const InputDecoration(
                          labelText:
                              'Nom de l’agronome / Bureau d’études (en-tête PDF)',
                        ),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _notesCtrl,
                        maxLines: 2,
                        decoration: const InputDecoration(
                          labelText: 'Notes d’inspection terrain (opt.)',
                        ),
                      ),
                      const SizedBox(height: 14),
                      FDPrimaryButton(
                        label: _submitting
                            ? 'Analyse en cours…'
                            : 'Calculer le diagnostic',
                        icon: Icons.science_outlined,
                        onPressed: _submitting ? null : _submit,
                      ),
                    ],
                  ),
                ),
                if (assessment != null) ...[
                  const SizedBox(height: 14),
                  _buildResultCard(assessment, qa),
                ],
                if (_history.isNotEmpty) ...[
                  const SizedBox(height: 14),
                  FDCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Mes diagnostics enregistrés',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 8),
                        ..._history.take(8).map((item) {
                          final code =
                              item['report_verification_code']?.toString() ??
                                  '';
                          return ListTile(
                            dense: true,
                            contentPadding: EdgeInsets.zero,
                            title: Text(
                              '${item['province_hub']} · Code $code',
                              style:
                                  const TextStyle(fontWeight: FontWeight.w600),
                            ),
                            subtitle: Text(
                              '${item['area_hectares'] ?? 'N/A'} ha · ${item['created_at'] ?? ''}',
                              style: const TextStyle(
                                  fontSize: 12, color: AppColors.muted),
                            ),
                            trailing: TextButton(
                              onPressed: () =>
                                  _downloadPdf(item['id'].toString(), code),
                              child: const Text('PDF'),
                            ),
                          );
                        }),
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

  Widget _buildResultCard(
      Map<String, dynamic> assessment, Map<String, dynamic>? qa) {
    final scores = assessment['computed_scores'] is Map
        ? Map<String, dynamic>.from(assessment['computed_scores'] as Map)
        : const <String, dynamic>{};
    final crops = ((scores['crop_assessments'] as List?) ?? const [])
        .whereType<Map>()
        .map((c) => Map<String, dynamic>.from(c))
        .toList();
    final canPdf = qa?['can_deliver_pdf'] == true;
    final blockers = ((qa?['blockers'] as List?) ?? const [])
        .map((e) => e.toString())
        .toList();
    final code = assessment['report_verification_code']?.toString() ?? '';

    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              FDBadge(
                label: scores['confidence_level']?.toString() ?? 'Diagnostic',
                color: AppColors.blue,
                backgroundColor: AppColors.blueSoft,
              ),
              if (code.isNotEmpty)
                FDBadge(
                  label: 'Code : $code',
                  color: AppColors.greenDark,
                  backgroundColor: AppColors.greenSoft,
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            scores['title']?.toString() ?? 'Résultat du diagnostic',
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: AppColors.ink,
            ),
          ),
          const SizedBox(height: 10),
          ...crops.map((c) {
            final score = (c['suitability_score'] as num?)?.toInt() ?? 0;
            final mkt = c['market_forecast'] is Map
                ? c['market_forecast'] as Map
                : null;
            final rev = c['indicative_gross_revenue_xaf'];
            final lim = ((c['limiting_factors'] as List?) ?? const [])
                .map((e) => e.toString())
                .join(' · ');
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AppColors.canvas,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.line),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          '${c['label_fr']} — ${c['suitability_label']}',
                          style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        Text(
                          '$score / 100',
                          style: TextStyle(
                            fontWeight: FontWeight.w800,
                            color: score >= 70
                                ? AppColors.greenDark
                                : (score >= 45
                                    ? AppColors.warning
                                    : AppColors.danger),
                          ),
                        ),
                      ],
                    ),
                    if (mkt != null && mkt['predicted_xaf_kg'] != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        'Prix prévu (${mkt['scope']}) : ${mkt['predicted_xaf_kg']} XAF/kg'
                        '${rev is num ? ' · Potentiel brut indicatif : ${formatXaf(rev)} XAF' : ''}',
                        style: const TextStyle(
                            fontSize: 12.5, color: AppColors.blue),
                      ),
                    ],
                    if (lim.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        lim,
                        style: const TextStyle(
                            fontSize: 12, color: AppColors.muted),
                      ),
                    ],
                  ],
                ),
              ),
            );
          }),
          if (!canPdf && blockers.isNotEmpty) ...[
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFFFEF3C7),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                'Porte QA PDF : ${blockers.join(' ')}',
                style: const TextStyle(fontSize: 12.5, color: AppColors.ink),
              ),
            ),
            const SizedBox(height: 10),
          ],
          FDPrimaryButton(
            label: _downloadingPdf
                ? 'Génération PDF…'
                : 'Télécharger le rapport PDF co-brandé',
            icon: Icons.picture_as_pdf_outlined,
            onPressed: (!canPdf || _downloadingPdf)
                ? null
                : () => _downloadPdf(assessment['id'].toString(), code),
          ),
        ],
      ),
    );
  }
}
