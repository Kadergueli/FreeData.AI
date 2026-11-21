import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/fd_theme.dart';
import '../core/utils/pdf_download.dart';
import '../services/api_service.dart';

/// Agriculture : « Pré-diagnostic agro-climatique de zone » (public) et « Diagnostic de terrain (pré-achat) »
/// (Agronome PRO). Le titre du document PRO est décidé par le serveur (QA gate), jamais par ce formulaire.
class AgroScreen extends StatefulWidget {
  final ApiService apiService;
  const AgroScreen({super.key, required this.apiService});

  @override
  State<AgroScreen> createState() => _AgroScreenState();
}

class _AgroScreenState extends State<AgroScreen> {
  static const List<String> _textures = [
    'sable',
    'sablo-limoneux',
    'limon',
    'limono-argileux',
    'argile',
  ];

  bool _proMode = false;
  List<String> _hubs = [];
  String? _hub;

  // Espace public
  Map<String, dynamic>? _zone;
  bool _zoneLoading = false;
  String? _zoneError;

  // Espace PRO
  final _crop = TextEditingController();
  final _ph = TextEditingController();
  final _om = TextEditingController();
  final _sampling = TextEditingController();
  final _lab = TextEditingController();
  final _org = TextEditingController();
  final _agronomist = TextEditingController();
  final _color = TextEditingController(text: '#1B5E20');
  String? _texture;
  Map<String, dynamic>? _preview;
  String? _previewError;
  bool _previewLoading = false;
  bool _busy = false;
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    for (final c in [_crop, _ph, _om, _sampling, _lab, _org, _agronomist, _color]) {
      c.addListener(_schedulePreview);
    }
    _loadHubs();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    for (final c in [_crop, _ph, _om, _sampling, _lab, _org, _agronomist, _color]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _loadHubs() async {
    try {
      final items = await widget.apiService.getAgroHubs();
      final names = items.map((e) => (e as Map)['hub'].toString()).toList();
      if (!mounted) return;
      setState(() {
        _hubs = names;
        _hub = names.isNotEmpty ? names.first : null;
      });
      await _loadZone();
    } catch (e) {
      if (mounted) setState(() => _zoneError = e.toString());
    }
  }

  Future<void> _loadZone() async {
    final hub = _hub;
    if (hub == null) return;
    setState(() {
      _zoneLoading = true;
      _zoneError = null;
    });
    try {
      final z = await widget.apiService.getAgroZonePrediagnosis(hub);
      if (mounted) setState(() => _zone = z);
    } catch (e) {
      if (mounted) {
        setState(() {
          _zone = null;
          _zoneError = e.toString();
        });
      }
    } finally {
      if (mounted) setState(() => _zoneLoading = false);
    }
  }

  // ── Corps de requête (même charge utile que POST /api/v1/agro/field-assessment) ──
  Map<String, dynamic> _payload() {
    String? t(TextEditingController c) {
      final v = c.text.trim();
      return v.isEmpty ? null : v;
    }

    final soil = <String, dynamic>{
      if (t(_ph) != null) 'ph': double.tryParse(t(_ph)!.replaceAll(',', '.')) ?? t(_ph),
      if (t(_om) != null)
        'organic_matter_pct':
            double.tryParse(t(_om)!.replaceAll(',', '.')) ?? t(_om),
      if (_texture != null) 'texture': _texture,
      if (t(_sampling) != null) 'sampling_date': t(_sampling),
      if (t(_lab) != null) 'lab_name': t(_lab),
    };
    final branding = <String, dynamic>{
      if (t(_org) != null) 'organization_name': t(_org),
      if (t(_agronomist) != null) 'agronomist_name': t(_agronomist),
      if (t(_color) != null) 'primary_color': t(_color),
    };
    return {
      'hub': _hub ?? '',
      if (t(_crop) != null) 'crop': t(_crop),
      if (soil.isNotEmpty) 'soil': soil,
      if (branding.isNotEmpty) 'branding': branding,
    };
  }

  void _schedulePreview() {
    if (!_proMode) return;
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 600), _refreshPreview);
  }

  Future<void> _refreshPreview() async {
    if (_hub == null) return;
    setState(() => _previewLoading = true);
    try {
      final p = await widget.apiService.previewAgroAssessment(_payload());
      if (mounted) {
        setState(() {
          _preview = p;
          _previewError = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _previewError = e.toString());
    } finally {
      if (mounted) setState(() => _previewLoading = false);
    }
  }

  Future<void> _downloadPdf() async {
    setState(() => _busy = true);
    try {
      final bytes = await widget.apiService.previewAgroAssessmentPdf(_payload());
      triggerPdfDownload(bytes, 'freedata_diagnostic_${_hub ?? 'hub'}.pdf');
    } catch (e) {
      _snack(e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      final rec = await widget.apiService.saveAgroAssessment(_payload());
      _snack('Évaluation enregistrée dans votre espace privé (${rec['title']}).');
    } catch (e) {
      _snack(e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _snack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Color _brand() {
    final raw = _color.text.trim();
    if (RegExp(r'^#[0-9A-Fa-f]{6}$').hasMatch(raw)) {
      return Color(int.parse('FF${raw.substring(1)}', radix: 16));
    }
    return FDTheme.greenDark;
  }

  // ── UI ──
  @override
  Widget build(BuildContext context) {
    final isPro = widget.apiService.hasPremiumKey;
    return Container(
      color: FDTheme.canvas,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Agriculture',
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.w700, color: FDTheme.ink)),
          const SizedBox(height: 4),
          const Text(
            'Indicateurs satellitaires par hub régional (NASA POWER). Chaque valeur indique sa source, sa licence, sa date et sa résolution.',
            style: TextStyle(color: FDTheme.subtle, fontSize: 13.5),
          ),
          const SizedBox(height: 12),
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: false, label: Text('Grand public')),
              ButtonSegment(value: true, label: Text('Agronome PRO')),
            ],
            selected: {_proMode},
            onSelectionChanged: (s) {
              setState(() => _proMode = s.first);
              if (_proMode && isPro) _refreshPreview();
            },
          ),
          const SizedBox(height: 12),
          _hubPicker(),
          const SizedBox(height: 12),
          if (!_proMode) ..._publicSection() else ..._proSection(isPro),
        ],
      ),
    );
  }

  Widget _hubPicker() {
    return DropdownButtonFormField<String>(
      value: _hub,
      isExpanded: true,
      decoration: const InputDecoration(
          labelText: 'Hub régional', border: OutlineInputBorder()),
      items: _hubs
          .map((h) => DropdownMenuItem(value: h, child: Text(h)))
          .toList(),
      onChanged: (v) {
        setState(() => _hub = v);
        _loadZone();
        _schedulePreview();
      },
    );
  }

  Widget _notice(String text, {Color? color}) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: (color ?? FDTheme.blueSoft),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: FDTheme.line),
      ),
      child: Text(text, style: const TextStyle(fontSize: 13, color: FDTheme.ink)),
    );
  }

  Widget _card(Widget child) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: FDTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: FDTheme.line),
      ),
      child: child,
    );
  }

  Widget _indicatorCard(Map<String, dynamic> i) {
    final prov = (i['provenance'] as Map?) ?? const {};
    final hist = i['history_same_month'] as Map?;
    final stale = i['stale'] == true;
    return _card(Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(i['label'].toString(),
            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
        const SizedBox(height: 4),
        Text('${i['value']} ${i['unit']}',
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
        if (hist != null)
          Text(
              'Situé au ${hist['percentile']}e percentile des ${hist['years_compared']} mêmes mois observés (moyenne ${hist['mean']}).',
              style: const TextStyle(fontSize: 13, color: FDTheme.inkSoft)),
        if (stale)
          const Text('Donnée ancienne (plus de 3 mois).',
              style: TextStyle(fontSize: 12.5, color: Colors.deepOrange)),
        const SizedBox(height: 6),
        Text(
          'Source : ${prov['source']} · Licence : ${prov['license']} · Mois : ${prov['reference_date'].toString().substring(0, 7)} · '
          'Résolution : ${prov['spatial_resolution']} · Confiance : ${prov['confidence_level']}',
          style: const TextStyle(fontSize: 11.5, color: FDTheme.subtle),
        ),
      ],
    ));
  }

  List<Widget> _publicSection() {
    if (_zoneLoading) {
      return const [Center(child: CircularProgressIndicator())];
    }
    if (_zoneError != null) return [_notice(_zoneError!)];
    final z = _zone;
    if (z == null) return const [];
    final forecasts = (z['price_forecasts'] as List?) ?? const [];
    return [
      Text(z['title'].toString(),
          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      _notice(z['resolution_notice'].toString()),
      const SizedBox(height: 10),
      for (final i in (z['indicators'] as List)) _indicatorCard(Map<String, dynamic>.from(i as Map)),
      const SizedBox(height: 6),
      const Text('Prévisions de prix validées dans la région',
          style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
      const SizedBox(height: 6),
      if (forecasts.isEmpty)
        _notice('Aucune prévision de prix à jour avec une erreur historique mesurée pour cette région.')
      else
        for (final f in forecasts)
          _card(Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${f['commodity']} — ${f['market']}',
                  style: const TextStyle(fontWeight: FontWeight.w700)),
              Text(
                  'Dernier prix ${f['last_observed_price']} (${f['last_observed_month']}) → prévu ${f['forecast_t1']} (${f['forecast_month']}).',
                  style: const TextStyle(fontSize: 13.5)),
              Text(
                  'Erreur historique mesurée : ${f['hist_error_pct']} % du dernier prix. ${f['error_definition']}',
                  style: const TextStyle(fontSize: 12, color: FDTheme.subtle)),
            ],
          )),
      const SizedBox(height: 6),
      _notice(
          'Pour un diagnostic de terrain avant achat, basculez sur « Agronome PRO » : mesures de sol et document certifié.',
          color: FDTheme.greenSoft),
      const SizedBox(height: 8),
      Text(z['disclaimer'].toString(),
          style: const TextStyle(fontSize: 11.5, color: FDTheme.subtle)),
    ];
  }

  Widget _field(TextEditingController c, String label,
      {String? hint, TextInputType? type}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: TextField(
        controller: c,
        keyboardType: type,
        decoration: InputDecoration(
            labelText: label, hintText: hint, border: const OutlineInputBorder()),
      ),
    );
  }

  List<Widget> _proSection(bool isPro) {
    if (!isPro) {
      return [
        _notice(
            'Le diagnostic de terrain (pré-achat) est réservé à l\'offre Agronome PRO. Activez une clé ou un abonnement PRO depuis « Abonnement ».')
      ];
    }
    final p = _preview;
    final qaChecks = ((p?['qa'] as Map?)?['checks'] as List?) ?? const [];
    return [
      const Text('Données du terrain',
          style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      _field(_crop, 'Culture envisagée (facultatif)'),
      _field(_ph, 'pH du sol (3,0 à 10,0)', type: TextInputType.number),
      _field(_om, 'Matière organique (%)', type: TextInputType.number),
      Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: DropdownButtonFormField<String?>(
          value: _texture,
          decoration: const InputDecoration(
              labelText: 'Texture du sol', border: OutlineInputBorder()),
          items: [
            const DropdownMenuItem<String?>(value: null, child: Text('—')),
            ..._textures.map((t) => DropdownMenuItem<String?>(value: t, child: Text(t))),
          ],
          onChanged: (v) {
            setState(() => _texture = v);
            _schedulePreview();
          },
        ),
      ),
      _field(_sampling, 'Date de prélèvement (AAAA-MM-JJ)'),
      _field(_lab, 'Laboratoire (facultatif)'),
      const Text('Co-branding du document',
          style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      _field(_org, 'Nom de votre organisation'),
      _field(_agronomist, 'Nom de l\'agronome'),
      _field(_color, 'Couleur principale', hint: '#1B5E20'),
      const SizedBox(height: 4),
      Row(children: [
        const Text('Aperçu du document',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        const SizedBox(width: 8),
        if (_previewLoading)
          const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
      ]),
      const SizedBox(height: 8),
      if (_previewError != null) _notice(_previewError!, color: const Color(0xFFFFEBEE)),
      if (p != null)
        _card(Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(((p['branding'] as Map?)?['organization_name'] ?? 'FreeData.AI').toString(),
                style: const TextStyle(fontSize: 12, color: FDTheme.subtle)),
            Text(p['title'].toString(),
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: _brand())),
            if (p['downgraded'] == true)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(p['downgrade_reason'].toString(),
                    style: const TextStyle(fontSize: 13, color: Colors.deepOrange)),
              ),
            const SizedBox(height: 8),
            for (final f in (p['findings'] as List? ?? const []))
              Text('• $f', style: const TextStyle(fontSize: 13.5)),
            const SizedBox(height: 8),
            for (final c in qaChecks)
              Text('${(c as Map)['ok'] == true ? '✓' : '✗'} ${c['detail']}',
                  style: const TextStyle(fontSize: 12.5, color: FDTheme.inkSoft)),
            const SizedBox(height: 8),
            Text(p['resolution_notice'].toString(),
                style: const TextStyle(fontSize: 11.5, color: FDTheme.subtle)),
          ],
        )),
      Wrap(spacing: 10, runSpacing: 10, children: [
        FilledButton.icon(
          onPressed: _busy ? null : _downloadPdf,
          icon: const Icon(Icons.picture_as_pdf_outlined),
          label: const Text('Télécharger le PDF'),
        ),
        OutlinedButton.icon(
          onPressed: _busy ? null : _save,
          icon: const Icon(Icons.lock_outline),
          label: const Text('Enregistrer (privé)'),
        ),
      ]),
      const SizedBox(height: 16),
      _integrationView(),
    ];
  }

  Widget _integrationView() {
    final pretty = const JsonEncoder.withIndent('  ').convert(_payload());
    return ExpansionTile(
      title: const Text('Intégration (API)',
          style: TextStyle(fontWeight: FontWeight.w700)),
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: SelectableText(
            'POST /api/v1/agro/field-assessment\n(aperçu sans stockage : /api/v1/agro/field-assessment/preview, ajouter ?format=pdf pour le PDF)\n\n$pretty',
            style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
          ),
        ),
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: pretty));
            _snack('Charge utile copiée.');
          },
          icon: const Icon(Icons.copy, size: 18),
          label: const Text('Copier la charge utile'),
        ),
        const Align(
          alignment: Alignment.centerLeft,
          child: Padding(
            padding: EdgeInsets.only(bottom: 12),
            child: Text(
              'Schémas SQL : sql/16_gold_agro_indicators.sql (public, lecture seule) et sql/17_agro_field_assessments_private.sql '
              '(privé, RLS, isolé par compte). Les mesures de sol ne nourrissent aucune table publique ni aucun modèle global.',
              style: TextStyle(fontSize: 12, color: FDTheme.subtle),
            ),
          ),
        ),
      ],
    );
  }
}
