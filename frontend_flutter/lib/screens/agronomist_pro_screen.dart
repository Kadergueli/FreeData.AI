import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/formatters.dart';
import '../core/utils/pdf_download.dart';
import '../services/api_service.dart';
import '../widgets/auth_dialog.dart';
import 'account_screen.dart';

/// Espace Agronome PRO — Diagnostic de terrain (pré-achat) & Rapport PDF co-brandé.
class AgronomistProScreen extends StatefulWidget {
  final ApiService apiService;
  final List<String> availableHubs;
  final String? initialHub;
  final bool embedded;
  final void Function(String prompt)? onAskAssistant;

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
    this.onAskAssistant,
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
    'rice_local': 'Riz local',
    'sesame': 'Sésame',
    'cowpeas': 'Niébé (Haricot)',
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
          _addressCtrl.text = prof['address']?.toString() ?? _addressCtrl.text;
          _contactCtrl.text = prof['contact']?.toString() ?? _contactCtrl.text;
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
      final prefHub = prefs.getString('fd_pref_agro_hub')?.trim() ?? '';
      if (!mounted) return;
      if (widget.initialHub == null &&
          prefHub.isNotEmpty &&
          widget.availableHubs.contains(prefHub)) {
        setState(() => _hub = prefHub);
      }
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

  static const Map<String, List<double>> _chadHubCoords = {
    "N'Djamena": [12.1348, 15.0557],
    'Moundou': [8.5667, 16.0833],
    'Sarh': [9.1429, 18.3923],
    'Abeche': [13.8292, 20.8324],
    'Bongor': [10.2806, 15.3722],
    'Doba': [8.6500, 16.8500],
    'Koumra': [8.9126, 17.5539],
    'Pala': [9.3642, 14.9046],
    'Mongo': [12.1844, 18.6930],
    'Ati': [13.2154, 18.3353],
    'Mao': [14.1212, 15.3103],
    'Bol': [13.4586, 14.7147],
  };

  Future<void> _openChadMapPicker() async {
    const minLat = 7.4;
    const maxLat = 23.5;
    const minLon = 13.4;
    const maxLon = 24.0;
    double selLat =
        _parseOpt(_latCtrl) ?? (_chadHubCoords[_hub]?[0] ?? 12.1348);
    double selLon =
        _parseOpt(_lonCtrl) ?? (_chadHubCoords[_hub]?[1] ?? 15.0557);

    final picked = await showDialog<List<double>>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlgState) {
          final availableWidth = MediaQuery.sizeOf(ctx).width - 56;
          final dialogWidth = availableWidth.clamp(240.0, 380.0).toDouble();
          final mapWidth = (dialogWidth - 32).clamp(180.0, 340.0).toDouble();
          final mapHeight = mapWidth * 300 / 340;
          String nearest = _hub;
          double bestD2 = double.infinity;
          _chadHubCoords.forEach((hub, ll) {
            final d2 = (ll[0] - selLat) * (ll[0] - selLat) +
                (ll[1] - selLon) * (ll[1] - selLon);
            if (d2 < bestD2) {
              bestD2 = d2;
              nearest = hub;
            }
          });
          return AlertDialog(
            scrollable: true,
            title: const Text('Pointer la parcelle (Carte Tchad — 12 pôles)'),
            content: SizedBox(
              width: dialogWidth,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Cliquez sur la carte ou sur un pôle pour remplir automatiquement la latitude et la longitude.',
                    style: TextStyle(fontSize: 12.5, color: Color(0xFF475569)),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: mapWidth,
                    height: mapHeight,
                    child: GestureDetector(
                      onTapDown: (details) {
                        final dx =
                            details.localPosition.dx.clamp(0.0, mapWidth);
                        final dy =
                            details.localPosition.dy.clamp(0.0, mapHeight);
                        final lon =
                            minLon + (dx / mapWidth) * (maxLon - minLon);
                        final lat =
                            maxLat - (dy / mapHeight) * (maxLat - minLat);
                        setDlgState(() {
                          selLat = double.parse(lat.toStringAsFixed(4));
                          selLon = double.parse(lon.toStringAsFixed(4));
                        });
                      },
                      child: Container(
                        width: mapWidth,
                        height: mapHeight,
                        decoration: BoxDecoration(
                          color: const Color(0xFFF0F9FF),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: const Color(0xFFBAE6FD)),
                        ),
                        child: CustomPaint(
                          painter: _ChadHubMapPainter(
                            hubs: _chadHubCoords,
                            selectedLat: selLat,
                            selectedLon: selLon,
                            minLat: minLat,
                            maxLat: maxLat,
                            minLon: minLon,
                            maxLon: maxLon,
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    'Position : ${selLat.toStringAsFixed(4)}, ${selLon.toStringAsFixed(4)} · Pôle proche : $nearest',
                    style: const TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600,
                        color: Color(0xFF0F172A)),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(ctx).pop(),
                child: const Text('Annuler'),
              ),
              FilledButton.icon(
                onPressed: () => Navigator.of(ctx).pop([selLat, selLon]),
                icon: const Icon(Icons.my_location, size: 16),
                label: const Text('Appliquer ces coordonnées'),
              ),
            ],
          );
        },
      ),
    );
    if (picked != null && picked.length == 2 && mounted) {
      setState(() {
        _latCtrl.text = picked[0].toStringAsFixed(4);
        _lonCtrl.text = picked[1].toStringAsFixed(4);
      });
    }
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
    final area = _parseOpt(_areaCtrl);
    if (area == null || area <= 0 || area > 500000) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text(
                'Saisissez la superficie réelle de la parcelle en hectares (valeur supérieure à 0).')),
      );
      return;
    }
    final latitude = _parseOpt(_latCtrl);
    final longitude = _parseOpt(_lonCtrl);
    if ((latitude == null) != (longitude == null)) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text(
                'Pour l’analyse GPS, saisissez latitude et longitude ensemble.')),
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

  Future<void> _openCreditPassportFromAssessment(String assessmentId) async {
    final loanCtrl = TextEditingController(text: '500000');
    final loanAmount = await showDialog<double>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Générer un Credit Passport Agro'),
        content: TextField(
          controller: loanCtrl,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(
            labelText: 'Montant du prêt demandé (FCFA)',
            helperText: 'Utilisé pour calculer le DSCR et l\'échéancier',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Annuler'),
          ),
          FilledButton(
            onPressed: () {
              final v =
                  double.tryParse(loanCtrl.text.trim().replaceAll(',', '.'));
              Navigator.of(ctx).pop(v != null && v > 0 ? v : 500000.0);
            },
            child: const Text('Calculer'),
          ),
        ],
      ),
    );
    loanCtrl.dispose();
    if (loanAmount == null || !mounted) return;

    try {
      final cp = await widget.apiService.createAgroCreditPassportFromAssessment(
        assessmentId,
        loanAmountXaf: loanAmount,
      );
      if (!mounted) return;
      final scenarios = (cp['scenarios'] as List?) ?? const [];
      final schedule = (cp['repayment_schedule'] as List?) ?? const [];
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(
              'Credit Passport · ${cp['label_fr'] ?? ''} (${cp['province'] ?? ''})'),
          content: SizedBox(
            width: 460,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Code dossier : ${cp['report_verification_code'] ?? assessmentId} · Surface : ${cp['area_hectares']} ha',
                    style: const TextStyle(
                        fontSize: 12.5, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 10),
                  const Text('Scénarios DSCR :',
                      style: TextStyle(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 4),
                  for (final s in scenarios.whereType<Map>())
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text(
                        '• ${s['description']} : CA ${s['estimated_revenue_xaf'] ?? '—'} FCFA | DSCR ${s['dscr'] ?? '—'}',
                        style: const TextStyle(fontSize: 12.5),
                      ),
                    ),
                  if (schedule.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    const Text('Échéancier saisonnier indicatif :',
                        style: TextStyle(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 4),
                    for (final step in schedule.whereType<Map>())
                      Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Text(
                          '• ${step['period']} : ${step['installment_xaf']} FCFA (${step['share_pct']}%)',
                          style: const TextStyle(fontSize: 12.5),
                        ),
                      ),
                  ],
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('Fermer'),
            ),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.toString().replaceFirst('Exception: ', ''))),
      );
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
    // Terrain A pré-rempli depuis le formulaire principal ; Terrain B (et C optionnel) saisis manuellement
    final aLabel = TextEditingController(text: 'Terrain A ($_hub)');
    String aHub = _hub;
    final aLat = TextEditingController(text: _latCtrl.text);
    final aLon = TextEditingController(text: _lonCtrl.text);
    final aArea = TextEditingController(text: _areaCtrl.text);
    final aPh = TextEditingController(text: _phCtrl.text);
    String aTex = _texture;
    final aOm = TextEditingController(text: _omCtrl.text);
    final aN = TextEditingController(text: _nCtrl.text);
    final aP = TextEditingController(text: _pCtrl.text);
    final aK = TextEditingController(text: _kCtrl.text);

    final bLabel = TextEditingController(text: 'Terrain B');
    String bHub = _hub == 'Moundou' ? 'Sarh' : 'Moundou';
    final bLat = TextEditingController();
    final bLon = TextEditingController();
    final bArea = TextEditingController();
    final bPh = TextEditingController();
    String bTex = '';
    final bOm = TextEditingController();
    final bN = TextEditingController();
    final bP = TextEditingController();
    final bK = TextEditingController();

    bool includeC = false;
    final cLabel = TextEditingController(text: 'Terrain C');
    String cHub = 'Bongor';
    final cLat = TextEditingController();
    final cLon = TextEditingController();
    final cArea = TextEditingController();
    final cPh = TextEditingController();
    String cTex = '';
    final cOm = TextEditingController();
    final cN = TextEditingController();
    final cP = TextEditingController();
    final cK = TextEditingController();

    Map<String, dynamic>? cmpData;
    String? cmpErr;
    bool comparing = false;
    bool downloading = false;

    double? pNum(TextEditingController c) =>
        double.tryParse(c.text.trim().replaceAll(',', '.'));

    Map<String, dynamic> buildCand(
      TextEditingController lbl,
      String hub,
      TextEditingController lat,
      TextEditingController lon,
      TextEditingController area,
      TextEditingController ph,
      String tex,
      TextEditingController om,
      TextEditingController n,
      TextEditingController p,
      TextEditingController k,
    ) {
      final lab = <String, dynamic>{};
      if (pNum(ph) != null) lab['ph'] = pNum(ph);
      if (tex.isNotEmpty) lab['texture'] = tex;
      if (pNum(om) != null) lab['organic_matter'] = pNum(om);
      if (pNum(n) != null) lab['nitrogen'] = pNum(n);
      if (pNum(p) != null) lab['phosphorus'] = pNum(p);
      if (pNum(k) != null) lab['potassium'] = pNum(k);
      return {
        'label': lbl.text.trim(),
        'province_hub': hub,
        if (pNum(lat) != null) 'gps_lat': pNum(lat),
        if (pNum(lon) != null) 'gps_lon': pNum(lon),
        if (pNum(area) != null && pNum(area)! > 0) 'area_hectares': pNum(area),
        'lab_soil_inputs': lab,
        'target_crops': _selectedCrops.toList(),
      };
    }

    Widget candForm(
      String title,
      TextEditingController lbl,
      String hub,
      void Function(String) onHub,
      TextEditingController lat,
      TextEditingController lon,
      TextEditingController area,
      TextEditingController ph,
      String tex,
      void Function(String) onTex,
      TextEditingController om,
      TextEditingController n,
      TextEditingController p,
      TextEditingController k,
    ) {
      return Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: const Color(0xFFF8FAFC),
          border: Border.all(color: const Color(0xFFCBD5E1)),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title,
                style: const TextStyle(
                    fontWeight: FontWeight.w700, color: AppColors.blue)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                SizedBox(
                  width: 170,
                  child: TextField(
                    controller: lbl,
                    decoration: const InputDecoration(
                        labelText: 'Nom du terrain', isDense: true),
                  ),
                ),
                SizedBox(
                  width: 165,
                  child: DropdownButtonFormField<String>(
                    initialValue: hub,
                    decoration:
                        const InputDecoration(labelText: 'Pôle', isDense: true),
                    items: widget.availableHubs
                        .map((h) => DropdownMenuItem(value: h, child: Text(h)))
                        .toList(),
                    onChanged: (v) {
                      if (v != null) onHub(v);
                    },
                  ),
                ),
                SizedBox(
                  width: 110,
                  child: TextField(
                    controller: area,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(
                        labelText: 'Surface (ha)', isDense: true),
                  ),
                ),
                SizedBox(
                  width: 120,
                  child: TextField(
                    controller: lat,
                    keyboardType: const TextInputType.numberWithOptions(
                        decimal: true, signed: true),
                    decoration: const InputDecoration(
                        labelText: 'Lat GPS (opt.)', isDense: true),
                  ),
                ),
                SizedBox(
                  width: 120,
                  child: TextField(
                    controller: lon,
                    keyboardType: const TextInputType.numberWithOptions(
                        decimal: true, signed: true),
                    decoration: const InputDecoration(
                        labelText: 'Lon GPS (opt.)', isDense: true),
                  ),
                ),
                SizedBox(
                  width: 95,
                  child: TextField(
                    controller: ph,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(
                        labelText: 'pH (opt.)', isDense: true),
                  ),
                ),
                SizedBox(
                  width: 155,
                  child: DropdownButtonFormField<String>(
                    initialValue: tex,
                    decoration: const InputDecoration(
                        labelText: 'Texture (opt.)', isDense: true),
                    items: _textures
                        .map((t) => DropdownMenuItem(
                            value: t['id']!, child: Text(t['label']!)))
                        .toList(),
                    onChanged: (v) => onTex(v ?? ''),
                  ),
                ),
                SizedBox(
                  width: 95,
                  child: TextField(
                    controller: om,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration: const InputDecoration(
                        labelText: 'MO % (opt.)', isDense: true),
                  ),
                ),
                SizedBox(
                  width: 80,
                  child: TextField(
                    controller: n,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration:
                        const InputDecoration(labelText: 'N', isDense: true),
                  ),
                ),
                SizedBox(
                  width: 80,
                  child: TextField(
                    controller: p,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration:
                        const InputDecoration(labelText: 'P', isDense: true),
                  ),
                ),
                SizedBox(
                  width: 80,
                  child: TextField(
                    controller: k,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                    decoration:
                        const InputDecoration(labelText: 'K', isDense: true),
                  ),
                ),
              ],
            ),
          ],
        ),
      );
    }

    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) {
          final tableRows =
              ((cmpData?['comparison_table'] as List?) ?? const [])
                  .whereType<Map>()
                  .map((e) => Map<String, dynamic>.from(e))
                  .toList();
          List<Map<String, dynamic>> currentCandidates() => [
                buildCand(aLabel, aHub, aLat, aLon, aArea, aPh, aTex, aOm, aN,
                    aP, aK),
                buildCand(bLabel, bHub, bLat, bLon, bArea, bPh, bTex, bOm, bN,
                    bP, bK),
                if (includeC)
                  buildCand(cLabel, cHub, cLat, cLon, cArea, cPh, cTex, cOm, cN,
                      cP, cK),
              ];

          return AlertDialog(
            title: const Text('Comparaison manuelle de 2 à 3 terrains'),
            content: SizedBox(
              width: 820,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    candForm(
                      'Terrain A (référence)',
                      aLabel,
                      aHub,
                      (v) => setDlg(() => aHub = v),
                      aLat,
                      aLon,
                      aArea,
                      aPh,
                      aTex,
                      (v) => setDlg(() => aTex = v),
                      aOm,
                      aN,
                      aP,
                      aK,
                    ),
                    candForm(
                      'Terrain B (candidat)',
                      bLabel,
                      bHub,
                      (v) => setDlg(() => bHub = v),
                      bLat,
                      bLon,
                      bArea,
                      bPh,
                      bTex,
                      (v) => setDlg(() => bTex = v),
                      bOm,
                      bN,
                      bP,
                      bK,
                    ),
                    if (includeC)
                      candForm(
                        'Terrain C (candidat)',
                        cLabel,
                        cHub,
                        (v) => setDlg(() => cHub = v),
                        cLat,
                        cLon,
                        cArea,
                        cPh,
                        cTex,
                        (v) => setDlg(() => cTex = v),
                        cOm,
                        cN,
                        cP,
                        cK,
                      ),
                    TextButton.icon(
                      icon: Icon(
                          includeC
                              ? Icons.remove_circle_outline
                              : Icons.add_circle_outline,
                          size: 18),
                      label: Text(includeC
                          ? 'Retirer le Terrain C'
                          : 'Ajouter un 3ᵉ terrain (Terrain C)'),
                      onPressed: () => setDlg(() => includeC = !includeC),
                    ),
                    if (cmpErr != null) ...[
                      const SizedBox(height: 8),
                      Text(cmpErr!,
                          style: const TextStyle(color: AppColors.danger)),
                    ],
                    if (tableRows.isNotEmpty) ...[
                      const Divider(height: 20),
                      SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: DataTable(
                          headingRowColor:
                              WidgetStateProperty.all(const Color(0xFFF0F9FF)),
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
                              DataCell(
                                  Text('${r['score_composite'] ?? '—'}/100')),
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
                    ],
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Fermer'),
              ),
              ElevatedButton(
                onPressed: comparing
                    ? null
                    : () async {
                        final areaControllers = [
                          aArea,
                          bArea,
                          if (includeC) cArea,
                        ];
                        final invalidArea = areaControllers.any((controller) {
                          final value = pNum(controller);
                          return value == null ||
                              !value.isFinite ||
                              value <= 0 ||
                              value > 500000;
                        });
                        if (invalidArea) {
                          setDlg(() {
                            cmpErr =
                                'Chaque terrain doit avoir une superficie réelle comprise entre 0 et 500 000 hectares.';
                          });
                          return;
                        }

                        final coordinatePairs = [
                          (aLat, aLon),
                          (bLat, bLon),
                          if (includeC) (cLat, cLon),
                        ];
                        for (final pair in coordinatePairs) {
                          final latText = pair.$1.text.trim();
                          final lonText = pair.$2.text.trim();
                          final latitude = pNum(pair.$1);
                          final longitude = pNum(pair.$2);
                          if ((latText.isEmpty) != (lonText.isEmpty)) {
                            setDlg(() {
                              cmpErr =
                                  'Pour chaque terrain, renseignez les deux coordonnées GPS ou laissez les deux vides.';
                            });
                            return;
                          }
                          if (latText.isNotEmpty &&
                              (latitude == null ||
                                  longitude == null ||
                                  !latitude.isFinite ||
                                  !longitude.isFinite ||
                                  latitude < -90 ||
                                  latitude > 90 ||
                                  longitude < -180 ||
                                  longitude > 180)) {
                            setDlg(() {
                              cmpErr =
                                  'Coordonnées GPS invalides : latitude entre -90 et 90, longitude entre -180 et 180.';
                            });
                            return;
                          }
                        }

                        final candidates = currentCandidates();
                        setDlg(() {
                          comparing = true;
                          cmpErr = null;
                        });
                        try {
                          final res =
                              await widget.apiService.compareAgroAssessments(
                            candidates: candidates,
                            agronomistName: _firmCtrl.text,
                            agronomistLicense: _licenseCtrl.text,
                          );
                          setDlg(() {
                            cmpData = res;
                            comparing = false;
                          });
                        } catch (e) {
                          setDlg(() {
                            cmpErr = '$e';
                            comparing = false;
                          });
                        }
                      },
                child: Text(comparing ? 'Calcul…' : 'Lancer la comparaison'),
              ),
              if (cmpData != null)
                ElevatedButton.icon(
                  icon: const Icon(Icons.picture_as_pdf_outlined, size: 17),
                  label: Text(downloading
                      ? 'PDF…'
                      : (_isOfficialApproved
                          ? 'PDF Comparatif'
                          : 'PDF (validation admin requise)')),
                  onPressed: (downloading || !_isOfficialApproved)
                      ? null
                      : () async {
                          setDlg(() => downloading = true);
                          try {
                            await _persistBranding();
                            final bytes =
                                await widget.apiService.downloadAgroComparePdf(
                              candidates: currentCandidates(),
                              agronomistName: _firmCtrl.text,
                              agronomistLicense: _licenseCtrl.text,
                              agronomistAddress: _addressCtrl.text,
                              agronomistContact: _contactCtrl.text,
                            );
                            triggerPdfDownload(
                                bytes, 'freedata_comparatif_agro.pdf');
                          } catch (e) {
                            setDlg(() => cmpErr = '$e');
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
                          if (ok == true &&
                              mounted &&
                              widget.apiService.isAuthenticated) {
                            if (_firmCtrl.text.trim().isEmpty) {
                              _firmCtrl.text = widget
                                      .apiService.authUser?['display_name']
                                      ?.toString()
                                      .trim() ??
                                  '';
                            }
                            setState(() {});
                            if (_hasAccess) {
                              await Future.wait([
                                _loadOfficialProfile(),
                                _loadHistory(),
                              ]);
                            }
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
                      'Renseignez uniquement les mesures réellement disponibles. Les valeurs déclarées sans justificatif de laboratoire sont signalées comme non vérifiées ; sans mesure, le résultat reste un pré-diagnostic régional.',
                      style: TextStyle(fontSize: 12.5, color: AppColors.muted),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      key: ValueKey(_hub),
                      initialValue: _hub,
                      decoration:
                          const InputDecoration(labelText: 'Pôle régional'),
                      items: widget.availableHubs
                          .map(
                              (h) => DropdownMenuItem(value: h, child: Text(h)))
                          .toList(),
                      onChanged: (v) {
                        if (v != null) setState(() => _hub = v);
                      },
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      'Les deux coordonnées GPS permettent de demander les indicateurs satellitaires au point de la parcelle. Sans GPS, le système utilise les données régionales disponibles et l’indique dans le PDF.',
                      style: TextStyle(fontSize: 11.5, color: AppColors.muted),
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      '2. Superficie et localisation GPS',
                      style: TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.blue),
                    ),
                    const SizedBox(height: 8),
                    LayoutBuilder(
                      builder: (context, constraints) {
                        final fieldWidth = constraints.maxWidth >= 620
                            ? (constraints.maxWidth - 20) / 3
                            : (constraints.maxWidth - 10) / 2;
                        return Wrap(
                          spacing: 10,
                          runSpacing: 10,
                          children: [
                            SizedBox(
                              width: fieldWidth,
                              child: TextField(
                                controller: _areaCtrl,
                                keyboardType:
                                    const TextInputType.numberWithOptions(
                                        decimal: true),
                                decoration: const InputDecoration(
                                  labelText: 'Superficie exacte (ha) *',
                                  helperText:
                                      'Obligatoire — dimensionne production et revenus',
                                ),
                              ),
                            ),
                            SizedBox(
                              width: fieldWidth,
                              child: TextField(
                                controller: _latCtrl,
                                keyboardType:
                                    const TextInputType.numberWithOptions(
                                        decimal: true, signed: true),
                                decoration: const InputDecoration(
                                  labelText: 'Latitude GPS (recommandée)',
                                ),
                              ),
                            ),
                            SizedBox(
                              width: fieldWidth,
                              child: TextField(
                                controller: _lonCtrl,
                                keyboardType:
                                    const TextInputType.numberWithOptions(
                                        decimal: true, signed: true),
                                decoration: const InputDecoration(
                                  labelText: 'Longitude GPS (recommandée)',
                                ),
                              ),
                            ),
                            SizedBox(
                              width: fieldWidth,
                              child: OutlinedButton.icon(
                                onPressed: _openChadMapPicker,
                                icon: const Icon(Icons.map_outlined, size: 18),
                                label: const Text('Choisir sur la carte'),
                              ),
                            ),
                          ],
                        );
                      },
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      '3. Mesures de sol laboratoire (priment sur la moyenne zonale)',
                      style: TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.blue),
                    ),
                    const SizedBox(height: 8),
                    LayoutBuilder(
                      builder: (context, constraints) {
                        final fieldWidth = constraints.maxWidth >= 620
                            ? (constraints.maxWidth - 20) / 3
                            : (constraints.maxWidth - 10) / 2;
                        return Wrap(
                          spacing: 10,
                          runSpacing: 10,
                          children: [
                            SizedBox(
                              width: fieldWidth,
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
                            SizedBox(
                              width: fieldWidth,
                              child: DropdownButtonFormField<String>(
                                key: ValueKey(_texture),
                                initialValue: _texture,
                                isExpanded: true,
                                decoration: const InputDecoration(
                                  labelText: 'Texture du sol',
                                ),
                                items: _textures
                                    .map((t) => DropdownMenuItem(
                                        value: t['id'],
                                        child: Text(t['label']!)))
                                    .toList(),
                                onChanged: (v) =>
                                    setState(() => _texture = v ?? ''),
                              ),
                            ),
                            SizedBox(
                              width: fieldWidth,
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
                        );
                      },
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      'Nutriments NPK — reprenez les unités indiquées sur le bulletin du laboratoire.',
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
                                    labelText: 'Azote N (unité labo)'),
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
                                    labelText: 'Phosphore P (unité labo)'),
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
                                    labelText: 'Potassium K (unité labo)'),
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
                      '4. Inspection terrain & Co-branding officiel du cabinet',
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
                    Wrap(
                      spacing: 10,
                      runSpacing: 8,
                      children: [
                        FDPrimaryButton(
                          label: _submitting
                              ? 'Analyse en cours…'
                              : 'Calculer le diagnostic',
                          icon: Icons.science_outlined,
                          onPressed: _submitting ? null : _submit,
                        ),
                        FDSecondaryButton(
                          label: 'Comparer 2 à 3 terrains',
                          icon: Icons.compare_arrows_rounded,
                          onPressed: _openCompareParcelsDialog,
                        ),
                        if (!_isOfficialApproved)
                          TextButton.icon(
                            icon: const Icon(Icons.verified_user_outlined,
                                size: 18),
                            label: const Text('Mon profil officiel'),
                            onPressed: () {
                              Navigator.of(context)
                                  .push(MaterialPageRoute(
                                      builder: (_) => AccountScreen(
                                          apiService: widget.apiService)))
                                  .then((_) => _loadOfficialProfile());
                            },
                          ),
                      ],
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
                            item['report_verification_code']?.toString() ?? '';
                        return ListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          title: Text(
                            '${item['province_hub']} · Code $code',
                            style: const TextStyle(fontWeight: FontWeight.w600),
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
    final pointSatellite = scores['point_satellite_data'] is Map
        ? Map<String, dynamic>.from(scores['point_satellite_data'] as Map)
        : const <String, dynamic>{};
    final pointProvenance = pointSatellite['provenance'] is Map
        ? Map<String, dynamic>.from(pointSatellite['provenance'] as Map)
        : const <String, dynamic>{};
    final siteContext = scores['site_context'] is Map
        ? Map<String, dynamic>.from(scores['site_context'] as Map)
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

          // 1. Fiche d'Identification Parcellaire & Localisation GPS
          _bulletinSectionTitle(
              '1. Fiche d’Identification Parcellaire & Localisation GPS'),
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
                    'GPS : $gpsStr · Surface : ${assessment['area_hectares'] ?? 'Non renseignée'}${assessment['area_hectares'] != null ? ' ha' : ''}'),
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

          if (siteContext.isNotEmpty || pointSatellite.isNotEmpty) ...[
            const SizedBox(height: 14),
            _bulletinSectionTitle(
                'Données spatiales et provenance des sources'),
            Container(
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: const Color(0xFFCBD5E1)),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                children: [
                  _kvRow(
                    'Superficie déclarée',
                    siteContext['area_hectares'] == null
                        ? 'Non renseignée'
                        : '${siteContext['area_hectares']} ha · ${siteContext['area_m2'] ?? '—'} m²',
                    shaded: true,
                  ),
                  _kvRow(
                    'Méthode climatique',
                    siteContext['climate_method']?.toString() ??
                        'Données régionales du pôle',
                  ),
                  _kvRow(
                    'Méthode pédologique',
                    siteContext['soil_method']?.toString() ?? 'Non documentée',
                    shaded: true,
                  ),
                  if (pointSatellite.isNotEmpty) ...[
                    _kvRow(
                      'Source au point GPS',
                      pointSatellite['source']?.toString() ?? 'NASA POWER',
                    ),
                    _kvRow(
                      'Période de référence',
                      pointProvenance['reference_period']?.toString() ??
                          pointSatellite['reference_period']?.toString() ??
                          'Non précisée',
                      shaded: true,
                    ),
                    _kvRow(
                      'Récupération UTC',
                      pointProvenance['retrieved_at_utc']?.toString() ??
                          pointSatellite['retrieved_at_utc']?.toString() ??
                          '—',
                    ),
                    _kvRow(
                      'Portée spatiale',
                      'Valeurs au point GPS, pas une moyenne de toute la parcelle. Une géométrie de parcelle est nécessaire pour une extraction zonale.',
                      shaded: true,
                    ),
                  ],
                ],
              ),
            ),
          ],
          if (labParams.isNotEmpty) ...[
            const SizedBox(height: 14),
            _bulletinSectionTitle('2. Bulletin Pédologique & Agro-Climatique'),
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
              '3. Matrice Comparative d’Aptitude Culturale & Rentabilité'),
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
                    DataCell(Text(rev is num ? '${formatXaf(rev)} F' : '—')),
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
                '4. Diagnostic des Facteurs Limitants & Prescriptions Techniques'),
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
              FDSecondaryButton(
                label: 'Comparer 2 à 3 terrains',
                icon: Icons.compare_arrows_rounded,
                onPressed: _openCompareParcelsDialog,
              ),
              FDSecondaryButton(
                label: 'Créer Credit Passport',
                icon: Icons.account_balance_outlined,
                onPressed: () => _openCreditPassportFromAssessment(
                    assessment['id'].toString()),
              ),
              if (widget.onAskAssistant != null)
                FDSecondaryButton(
                  label: 'Discuter avec l’Assistant IA',
                  icon: Icons.chat_bubble_outline_rounded,
                  onPressed: () {
                    final hub =
                        gps['selected_hub'] ?? assessment['province_hub'] ?? '';
                    final topCrop = crops.isNotEmpty
                        ? '${crops.first['label_fr']} (${crops.first['suitability_score']}/100)'
                        : '';
                    widget.onAskAssistant!(
                      'Analyse ce bulletin agronomique pour $hub '
                      '(Réf. $code, score global ${ws['total_score'] ?? '—'}/100, meilleure culture : $topCrop) '
                      'et propose un plan d’action concret.',
                    );
                  },
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

class _ChadHubMapPainter extends CustomPainter {
  final Map<String, List<double>> hubs;
  final double selectedLat;
  final double selectedLon;
  final double minLat;
  final double maxLat;
  final double minLon;
  final double maxLon;

  const _ChadHubMapPainter({
    required this.hubs,
    required this.selectedLat,
    required this.selectedLon,
    required this.minLat,
    required this.maxLat,
    required this.minLon,
    required this.maxLon,
  });

  Offset _toOffset(double lat, double lon, Size size) {
    final x = ((lon - minLon) / (maxLon - minLon)) * size.width;
    final y = ((maxLat - lat) / (maxLat - minLat)) * size.height;
    return Offset(
        x.clamp(8.0, size.width - 8.0), y.clamp(8.0, size.height - 8.0));
  }

  @override
  void paint(Canvas canvas, Size size) {
    final gridPaint = Paint()
      ..color = const Color(0xFFCBD5E1)
      ..strokeWidth = 0.6;
    for (var i = 1; i < 4; i++) {
      final gx = size.width * i / 4;
      final gy = size.height * i / 4;
      canvas.drawLine(Offset(gx, 0), Offset(gx, size.height), gridPaint);
      canvas.drawLine(Offset(0, gy), Offset(size.width, gy), gridPaint);
    }

    final hubPaint = Paint()..color = const Color(0xFF0284C7);
    hubs.forEach((name, ll) {
      final pt = _toOffset(ll[0], ll[1], size);
      canvas.drawCircle(pt, 4.0, hubPaint);
      final tp = TextPainter(
        text: TextSpan(
          text: name,
          style: const TextStyle(fontSize: 9.5, color: Color(0xFF334155)),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas,
          Offset((pt.dx + 5).clamp(2.0, size.width - tp.width - 2), pt.dy - 5));
    });

    final sel = _toOffset(selectedLat, selectedLon, size);
    canvas.drawCircle(sel, 8.0, Paint()..color = const Color(0x33DC2626));
    canvas.drawCircle(sel, 4.5, Paint()..color = const Color(0xFFDC2626));
  }

  @override
  bool shouldRepaint(covariant _ChadHubMapPainter oldDelegate) =>
      oldDelegate.selectedLat != selectedLat ||
      oldDelegate.selectedLon != selectedLon;
}
