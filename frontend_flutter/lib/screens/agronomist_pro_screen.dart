import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

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
  final bool embedded;

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
    this.embedded = false,
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
  final _licenseCtrl = TextEditingController();
  final _addressCtrl = TextEditingController();
  final _contactCtrl = TextEditingController();

  bool _submitting = false;
  bool _downloadingPdf = false;
  Map<String, dynamic>? _officialProfile;
  Map<String, dynamic>? _result;
  List<Map<String, dynamic>> _history = const [];

  bool get _hasAccess =>
      widget.apiService.isAuthenticated && widget.apiService.hasPremiumKey;
  bool get _isOfficialApproved => _officialProfile?['status'] == 'approved';

  @override
  void initState() {
    super.initState();
    final hubs = widget.availableHubs;
    _hub = (widget.initialHub != null && hubs.contains(widget.initialHub))
        ? widget.initialHub!
        : (hubs.contains("N'Djamena") ? "N'Djamena" : hubs.first);
    _firmCtrl.text =
        widget.apiService.authUser?['display_name']?.toString().trim() ?? '';
    _loadSavedBranding();
    if (_hasAccess) {
      _loadOfficialProfile();
      _loadHistory();
    }
  }

  Future<void> _loadOfficialProfile() async {
    try {
      final prof = await widget.apiService.getMyAgroProfile();
      if (!mounted) return;
      setState(() {
        _officialProfile = prof;
        if (prof != null && prof['status'] == 'approved') {
          _firmCtrl.text = prof['firm_name']?.toString() ?? _firmCtrl.text;
          _licenseCtrl.text =
              prof['license_number']?.toString() ?? _licenseCtrl.text;
          _addressCtrl.text =
              prof['address']?.toString() ?? _addressCtrl.text;
          _contactCtrl.text =
              prof['contact']?.toString() ?? _contactCtrl.text;
        }
      });
    } catch (_) {}
  }

  Future<void> _loadSavedBranding() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final savedName = prefs.getString('agro_firm_name')?.trim() ?? '';
      final savedLic = prefs.getString('agro_firm_license')?.trim() ?? '';
      final savedAddr = prefs.getString('agro_firm_address')?.trim() ?? '';
      final savedContact = prefs.getString('agro_firm_contact')?.trim() ?? '';
      if (!mounted) return;
      if (savedName.isNotEmpty) _firmCtrl.text = savedName;
      if (savedLic.isNotEmpty) _licenseCtrl.text = savedLic;
      if (savedAddr.isNotEmpty) _addressCtrl.text = savedAddr;
      if (savedContact.isNotEmpty) _contactCtrl.text = savedContact;
    } catch (_) {}
  }

  Future<void> _persistBranding() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('agro_firm_name', _firmCtrl.text.trim());
      await prefs.setString('agro_firm_license', _licenseCtrl.text.trim());
      await prefs.setString('agro_firm_address', _addressCtrl.text.trim());
      await prefs.setString('agro_firm_contact', _contactCtrl.text.trim());
    } catch (_) {}
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
    _licenseCtrl.dispose();
    _addressCtrl.dispose();
    _contactCtrl.dispose();
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
      await _persistBranding();
      final bytes = await widget.apiService.downloadAgroAssessmentPdf(
        assessmentId,
        agronomistName: _firmCtrl.text,
        agronomistLicense: _licenseCtrl.text,
        agronomistAddress: _addressCtrl.text,
        agronomistContact: _contactCtrl.text,
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

  Future<void> _openCompareParcelsDialog() async {
    final items = _history.take(3).toList();
    if (items.length < 2) return;
    final ids = items.map((e) => e['id'].toString()).toList();
    Map<String, dynamic>? cmpData;
    String? cmpErr;
    bool downloading = false;

    try {
      cmpData = await widget.apiService.compareAgroAssessments(
        assessmentIds: ids,
        agronomistName: _firmCtrl.text,
      );
    } catch (e) {
      cmpErr = '$e';
    }
    if (!mounted) return;

    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) {
          final tableRows =
              ((cmpData?['comparison_table'] as List?) ?? const [])
                  .whereType<Map>()
                  .map((e) => Map<String, dynamic>.from(e))
                  .toList();
          return AlertDialog(
            title: Text(cmpData?['title']?.toString() ??
                'Comparaison multi-terrains (côte à côte)'),
            content: SizedBox(
              width: 760,
              child: cmpErr != null
                  ? Text(cmpErr,
                      style: const TextStyle(color: AppColors.danger))
                  : SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: DataTable(
                        columns: const [
                          DataColumn(label: Text('Rang')),
                          DataColumn(label: Text('Terrain / Pôle')),
                          DataColumn(label: Text('Score /100')),
                          DataColumn(label: Text('Dist. marché')),
                          DataColumn(label: Text('Hum. rac.')),
                          DataColumn(label: Text('Prix ML')),
                          DataColumn(label: Text('CA Central')),
                        ],
                        rows: tableRows.map((r) {
                          return DataRow(cells: [
                            DataCell(Text(r['rank_label']?.toString() ?? '—',
                                style: const TextStyle(
                                    fontWeight: FontWeight.w700))),
                            DataCell(Text(
                                '${r['label']} · ${r['region'] ?? '—'}')),
                            DataCell(Text('${r['score_composite'] ?? '—'}/100')),
                            DataCell(Text(r['distance_hub_km'] != null
                                ? '${r['distance_hub_km']} km'
                                : '—')),
                            DataCell(Text(r['rainy_root_wetness'] != null
                                ? '${r['rainy_root_wetness']}'
                                : '—')),
                            DataCell(Text(r['predicted_xaf_kg'] != null
                                ? '${r['predicted_xaf_kg']} F'
                                : '—')),
                            DataCell(Text(r['ca_central_xaf'] is num
                                ? '${formatXaf(r['ca_central_xaf'] as num)} F'
                                : '—')),
                          ]);
                        }).toList(),
                      ),
                    ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Fermer'),
              ),
              if (cmpData != null)
                ElevatedButton.icon(
                  icon: const Icon(Icons.picture_as_pdf_outlined, size: 17),
                  label: Text(downloading ? 'PDF…' : 'Télécharger PDF Comparatif'),
                  onPressed: downloading
                      ? null
                      : () async {
                          setDlg(() => downloading = true);
                          try {
                            await _persistBranding();
                            final bytes =
                                await widget.apiService.downloadAgroComparePdf(
                              assessmentIds: ids,
                              agronomistName: _firmCtrl.text,
                              agronomistLicense: _licenseCtrl.text,
                              agronomistAddress: _addressCtrl.text,
                              agronomistContact: _contactCtrl.text,
                            );
                            triggerPdfDownload(
                                bytes, 'freedata_comparatif_agro.pdf');
                          } finally {
                            setDlg(() => downloading = false);
                          }
                        },
                ),
            ],
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final assessment = _result?['assessment'] is Map
        ? Map<String, dynamic>.from(_result!['assessment'] as Map)
        : null;
    final qa = _result?['qa'] is Map
        ? Map<String, dynamic>.from(_result!['qa'] as Map)
        : null;

    final content = Center(
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
                            final ok = await showDialog<bool>(
                              context: context,
                              builder: (_) =>
                                  AuthDialog(apiService: widget.apiService),
                            );
                            if (ok == true && mounted) {
                              if (_firmCtrl.text.trim().isEmpty) {
                                _firmCtrl.text = widget
                                        .apiService.authUser?['display_name']
                                        ?.toString()
                                        .trim() ??
                                    '';
                              }
                              setState(() {});
                              if (_hasAccess) await _loadHistory();
                            }
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
                      const Text(
                        '2. Mesures de sol laboratoire (priment sur la moyenne zonale)',
                        style: TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700,
                            color: AppColors.blue),
                      ),
                      const SizedBox(height: 8),
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
                      const Text(
                        '2. Mesures de sol laboratoire (priment sur la moyenne zonale)',
                        style: TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700,
                            color: AppColors.blue),
                      ),
                      const SizedBox(height: 8),
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
                      const Text(
                        '2. Mesures de sol laboratoire (priment sur la moyenne zonale)',
                        style: TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700,
                            color: AppColors.blue),
                      ),
                      const SizedBox(height: 8),
                      LayoutBuilder(
                        builder: (context, constraints) {
                          final fieldWidth = constraints.maxWidth >= 560
                              ? (constraints.maxWidth - 20) / 3
                              : constraints.maxWidth;
                          return Wrap(
                            spacing: 10,
                            runSpacing: 10,
                            children: [
                              SizedBox(
                                width: fieldWidth,
                                child: TextField(
                                  controller: _nCtrl,
                                  keyboardType:
                                      const TextInputType.numberWithOptions(
                                          decimal: true),
                                  decoration: const InputDecoration(
                                      labelText: 'Azote N (opt.)'),
                                ),
                              ),
                              SizedBox(
                                width: fieldWidth,
                                child: TextField(
                                  controller: _pCtrl,
                                  keyboardType:
                                      const TextInputType.numberWithOptions(
                                          decimal: true),
                                  decoration: const InputDecoration(
                                      labelText: 'Phosphore P (opt.)'),
                                ),
                              ),
                              SizedBox(
                                width: fieldWidth,
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
                          );
                        },
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
                      const SizedBox(height: 12),
                      const Text(
                        '3. Inspection terrain & Co-branding officiel du cabinet',
                        style: TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700,
                            color: AppColors.blue),
                      ),
                      const SizedBox(height: 8),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: _isOfficialApproved
                              ? AppColors.greenSoft
                              : const Color(0xFFFEF3C7),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(
                          _isOfficialApproved
                              ? 'Cabinet vérifié par l’administrateur : vos informations officielles sont pré-remplies automatiquement sur tous vos PDF.'
                              : (_officialProfile?['status'] == 'pending'
                                  ? 'Profil officiel en attente de validation par l’administrateur. La génération de PDF sera débloquée dès confirmation.'
                                  : 'Pour générer des rapports PDF certifiés, soumettez vos informations officielles depuis « Mon compte » pour validation administrateur.'),
                          style: const TextStyle(
                              fontSize: 12.5,
                              color: AppColors.ink,
                              fontWeight: FontWeight.w600),
                        ),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _firmCtrl,
                        readOnly: _isOfficialApproved,
                        decoration: const InputDecoration(
                          labelText:
                              'Raison sociale / Nom officiel de l’agronome (en-tête PDF)',
                        ),
                      ),
                      const SizedBox(height: 10),
                      LayoutBuilder(
                        builder: (context, constraints) {
                          final half = constraints.maxWidth >= 560
                              ? (constraints.maxWidth - 10) / 2
                              : constraints.maxWidth;
                          return Wrap(
                            spacing: 10,
                            runSpacing: 10,
                            children: [
                              SizedBox(
                                width: half,
                                child: TextField(
                                  controller: _licenseCtrl,
                                  readOnly: _isOfficialApproved,
                                  decoration: const InputDecoration(
                                    labelText:
                                        'N° d’agrément / Ordre / RCCM (opt.)',
                                  ),
                                ),
                              ),
                              SizedBox(
                                width: half,
                                child: TextField(
                                  controller: _contactCtrl,
                                  readOnly: _isOfficialApproved,
                                  decoration: const InputDecoration(
                                    labelText:
                                        'Téléphone & Email professionnel (opt.)',
                                  ),
                                ),
                              ),
                            ],
                          );
                        },
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _addressCtrl,
                        readOnly: _isOfficialApproved,
                        decoration: const InputDecoration(
                          labelText:
                              'Adresse officielle du cabinet / ville (opt.)',
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
      );
    if (widget.embedded) {
      return Container(color: AppColors.canvas, child: content);
    }
    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
        title: const Text(
          'Agronome PRO — Diagnostic de terrain',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      body: content,
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
    final ws = scores['weighted_score'] is Map
        ? Map<String, dynamic>.from(scores['weighted_score'] as Map)
        : const <String, dynamic>{};
    final bd = ws['breakdown'] is Map
        ? Map<String, dynamic>.from(ws['breakdown'] as Map)
        : const <String, dynamic>{};
    final gps = scores['gps_logistics'] is Map
        ? Map<String, dynamic>.from(scores['gps_logistics'] as Map)
        : const <String, dynamic>{};
    final econ = scores['verified_economics'] is Map
        ? Map<String, dynamic>.from(scores['verified_economics'] as Map)
        : const <String, dynamic>{};
    final bulletin = scores['bulletin'] is Map
        ? Map<String, dynamic>.from(scores['bulletin'] as Map)
        : const <String, dynamic>{};
    final labParams = ((bulletin['lab_parameters'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final prescriptions = ((bulletin['prescriptions'] as List?) ?? const [])
        .map((e) => e.toString())
        .toList();
    final hasLab = scores['has_lab_measurements'] == true;
    final dateStr = (assessment['created_at']?.toString() ?? '').length >= 10
        ? assessment['created_at'].toString().substring(0, 10)
        : '—';
    final gpsStr = gps['gps_provided'] == true
        ? '${gps['gps_lat']}, ${gps['gps_lon']}'
        : 'Non fournies';
    final idwHubs = ((gps['idw_hubs'] as List?) ?? const [])
        .whereType<Map>()
        .where((h) => ((h['weight_pct'] as num?) ?? 0) > 0)
        .map((h) =>
            '${h['hub']} (${h['road_distance_km']} km · ${h['weight_pct']}%)')
        .join(' · ');

    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              FDBadge(
                label: scores['confidence_level']?.toString() ?? 'Bulletin',
                color: hasLab ? AppColors.greenDark : const Color(0xFF92400E),
                backgroundColor:
                    hasLab ? AppColors.greenSoft : const Color(0xFFFEF3C7),
              ),
              if (code.isNotEmpty)
                FDBadge(
                  label: 'Réf. $code',
                  color: AppColors.blue,
                  backgroundColor: AppColors.blueSoft,
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            scores['title']?.toString() ??
                'Bulletin d’Analyse Agronomique & Pédologique',
            style: const TextStyle(
              fontSize: 15.5,
              fontWeight: FontWeight.w800,
              color: AppColors.ink,
            ),
          ),
          const SizedBox(height: 12),

          // BLOC A — Fiche d'Identification Parcellaire & Localisation GPS
          _bulletinSectionTitle(
              'BLOC A — Fiche d’Identification Parcellaire & GPS'),
          Container(
            decoration: BoxDecoration(
              color: Colors.white,
              border: Border.all(color: const Color(0xFFCBD5E1)),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              children: [
                _kvRow('Référence Dossier',
                    '$code · Date : $dateStr · Cabinet : ${_firmCtrl.text.trim().isNotEmpty ? _firmCtrl.text.trim() : '—'}',
                    shaded: true),
                _kvRow('Coordonnées GPS & Surface',
                    'GPS : $gpsStr · Surface : ${assessment['area_hectares'] ?? '1.0 (réf.)'} ha'),
                _kvRow(
                    'Rattachement Spatial (IDW)',
                    'Pôle : ${gps['selected_hub'] ?? assessment['province_hub'] ?? '—'} '
                        '(${gps['distance_hub_km'] ?? '—'} km) · N’Djamena : ${gps['distance_ndjamena_km'] ?? '—'} km · '
                        'Décote : -${gps['farmgate_discount_pct'] ?? 8}%'
                        '${idwHubs.isNotEmpty ? '\nIDW (k=3) : $idwHubs' : ''}',
                    shaded: true),
                _kvRow(
                    'Score Unifié & Confiance',
                    '${ws['total_score'] ?? '—'}/100 (${ws['verdict'] ?? '—'}) '
                        '[Eau ${bd['hydric_security']?['score'] ?? '—'}/50 + '
                        'Sol ${bd['soil_quality']?['score'] ?? '—'}/30 + '
                        'Marché ${bd['market_logistics']?['score'] ?? '—'}/20]'),
              ],
            ),
          ),

          if (labParams.isNotEmpty) ...[
            const SizedBox(height: 14),
            _bulletinSectionTitle(
                'BLOC B — Bulletin Pédologique & Agro-Climatique'),
            SingleChildScrollView(
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
                    DataColumn(label: Text('Paramètre')),
                    DataColumn(label: Text('Valeur Parcelle')),
                    DataColumn(label: Text('Norme / Seuil')),
                    DataColumn(label: Text('Statut')),
                    DataColumn(label: Text('Source & Maille')),
                  ],
                  rows: labParams.map((p) {
                    final st = p['status']?.toString() ?? '—';
                    final isOk = st == 'Bon' || st == 'Mesuré';
                    final isBad = st == 'Déficit' || st == 'Attention';
                    return DataRow(cells: [
                      DataCell(Text(p['parameter']?.toString() ?? '—',
                          style: const TextStyle(fontWeight: FontWeight.w600))),
                      DataCell(Text(p['value']?.toString() ?? '—')),
                      DataCell(Text(p['optimal']?.toString() ?? '—')),
                      DataCell(FDBadge(
                        label: st,
                        color: isOk
                            ? AppColors.greenDark
                            : (isBad
                                ? AppColors.danger
                                : const Color(0xFF92400E)),
                        backgroundColor: isOk
                            ? AppColors.greenSoft
                            : (isBad
                                ? const Color(0xFFFEE2E2)
                                : const Color(0xFFFEF3C7)),
                      )),
                      DataCell(Text(p['source']?.toString() ?? '—',
                          style: const TextStyle(
                              fontSize: 12, color: AppColors.muted))),
                    ]);
                  }).toList(),
                ),
              ),
            ),
          ],

          const SizedBox(height: 14),
          _bulletinSectionTitle(
              'BLOC C — Matrice Comparative d’Aptitude Culturale & Rentabilité'),
          SingleChildScrollView(
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
                  DataColumn(label: Text('Culture')),
                  DataColumn(label: Text('Score /100')),
                  DataColumn(label: Text('Eau/50 + Sol/30 + Marché/20')),
                  DataColumn(label: Text('Prix Bord-Champ')),
                  DataColumn(label: Text('CA Brut Estimé')),
                  DataColumn(label: Text('Verdict')),
                ],
                rows: crops.map((c) {
                  final sc = (c['suitability_score'] as num?)?.toInt() ?? 0;
                  final cecon = c['verified_economics'] is Map
                      ? c['verified_economics'] as Map
                      : const {};
                  final fg = cecon['farmgate_price_central_xaf_kg'];
                  final rev = c['indicative_gross_revenue_xaf'];
                  return DataRow(cells: [
                    DataCell(Text(c['label_fr']?.toString() ?? '—',
                        style: const TextStyle(fontWeight: FontWeight.w700))),
                    DataCell(Text('$sc / 100',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          color: sc >= 70
                              ? AppColors.greenDark
                              : (sc >= 45
                                  ? AppColors.warning
                                  : AppColors.danger),
                        ))),
                    DataCell(Text(
                        '${c['water_score'] ?? '—'} + ${c['soil_score'] ?? '—'} + ${c['market_score'] ?? '—'}')),
                    DataCell(Text(fg != null ? '$fg F/kg' : 'N/A')),
                    DataCell(
                        Text(rev is num ? '${formatXaf(rev)} F' : '—')),
                    DataCell(Text(c['suitability_label']?.toString() ?? '—')),
                  ]);
                }).toList(),
              ),
            ),
          ),
          if ((econ['formula_text']?.toString() ?? '').isNotEmpty) ...[
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                border: Border.all(color: const Color(0xFFCBD5E1)),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                'Formule vérifiable : ${econ['formula_text']}'
                '${econ['ca_stress_xaf'] is num ? '\nPlancher Stress 2024–2026 : ${formatXaf(econ['ca_stress_xaf'] as num)} FCFA · Incertitude ±${econ['mape_pct'] ?? '—'}%' : ''}',
                style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: AppColors.ink),
              ),
            ),
          ],

          if (prescriptions.isNotEmpty) ...[
            const SizedBox(height: 14),
            _bulletinSectionTitle(
                'BLOC D — Facteurs Limitants & Prescriptions Techniques'),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: const Color(0xFFCBD5E1)),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: prescriptions
                    .map((rx) => Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Text('• $rx',
                              style: const TextStyle(
                                  fontSize: 12.5, color: AppColors.ink)),
                        ))
                    .toList(),
              ),
            ),
          ],

          if (!canPdf && blockers.isNotEmpty) ...[
            const SizedBox(height: 10),
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
          ],
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              FDPrimaryButton(
                label: _downloadingPdf
                    ? 'Génération PDF…'
                    : (_isOfficialApproved
                        ? 'Télécharger le rapport PDF co-brandé'
                        : 'PDF verrouillé (validation admin requise)'),
                icon: Icons.picture_as_pdf_outlined,
                onPressed: (!canPdf || _downloadingPdf || !_isOfficialApproved)
                    ? null
                    : () => _downloadPdf(assessment['id'].toString(), code),
              ),
              if (_history.length >= 2)
                FDSecondaryButton(
                  label: 'Comparer avec une autre parcelle',
                  icon: Icons.compare_arrows_rounded,
                  onPressed: _openCompareParcelsDialog,
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _bulletinSectionTitle(String title) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Text(
          title,
          style: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w800,
            color: Color(0xFF0284C7),
          ),
        ),
      );

  Widget _kvRow(String label, String value, {bool shaded = false}) => Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: shaded ? const Color(0xFFF0F9FF) : Colors.white,
          border: const Border(
              bottom: BorderSide(color: Color(0xFFE2E8F0), width: 0.8)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 150,
              child: Text(
                label,
                style: const TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: AppColors.ink),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                value,
                style: const TextStyle(fontSize: 12.5, color: AppColors.ink),
              ),
            ),
          ],
        ),
      );
}
