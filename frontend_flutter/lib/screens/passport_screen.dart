import 'package:flutter/material.dart';
import '../core/fd_theme.dart';
import '../core/utils/formatters.dart';
import '../services/api_service.dart';

class PassportScreen extends StatefulWidget {
  final ApiService apiService;
  const PassportScreen({super.key, required this.apiService});

  @override
  State<PassportScreen> createState() => _PassportScreenState();
}

class _PassportScreenState extends State<PassportScreen> {
  static const String _officialDisclaimer =
      "Indicateur informatif fondé sur la volatilité des prix de marché. "
      "Il n'a pas été calibré sur des historiques de défaut de paiement et ne constitue "
      "ni une décision de crédit ni un conseil financier.";

  static const List<String> _defaultCommodities = [
    'Millet',
    'Sorghum (red)',
    'Maize (white)',
    'Rice (imported)',
    'Groundnuts (shelled)',
    'Sesame',
  ];

  List<String> _commodities = List<String>.from(_defaultCommodities);
  String _commodity = 'Millet';
  int _loanAmount = 1000000;
  List<dynamic> _passports = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      final meta = await widget.apiService.getMetadata();
      final legacy = meta['legacy_fields'];
      final passportProds = meta['passport_products'];
      final rawComms = (passportProds is List && passportProds.isNotEmpty)
          ? passportProds
          : (meta['products'] ??
              (legacy is Map ? legacy['commodities'] : null) ??
              meta['commodities'] ??
              const []);
      final comms = List<String>.from(rawComms).where((c) => c.isNotEmpty).toList();
      if (mounted && comms.isNotEmpty) {
        setState(() {
          _commodities = comms;
          if (!comms.contains(_commodity)) {
            _commodity = comms.contains('Millet') ? 'Millet' : comms.first;
          }
        });
      }
    } catch (_) {
      // Conservation de la liste par défaut si les métadonnées échouent.
    }
    if (mounted) {
      await _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await widget.apiService.getCreditPassports(
        commodity: _commodity,
        loanAmount: _loanAmount,
      );
      if (mounted) setState(() => _passports = items);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Les données Credit Passport ne sont pas accessibles pour le moment.');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _formatDrawdown(dynamic raw) {
    final parsed = parseNum(raw);
    if (parsed == null) return '—';
    final signed = parsed > 0 ? -parsed : parsed;
    return signed.toStringAsFixed(1);
  }

  String _formatCv(dynamic raw) {
    final parsed = parseNum(raw);
    if (parsed == null) return '—';
    return parsed.toStringAsFixed(1);
  }

  String _resolveDisclaimer() {
    for (final raw in _passports) {
      if (raw is Map && raw['disclaimer'] != null) {
        final d = raw['disclaimer'].toString().trim();
        if (d.isNotEmpty) return d;
      }
    }
    return _officialDisclaimer;
  }

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 640;

    return SingleChildScrollView(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 14 : 24,
        vertical: compact ? 14 : 20,
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1080),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              FDCard(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        key: ValueKey(_commodity),
                        initialValue: _commodities.contains(_commodity) ? _commodity : null,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Produit',
                          isDense: true,
                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                        ),
                        items: _commodities
                            .map((c) => DropdownMenuItem(
                                  value: c,
                                  child: Text(
                                    commodityLabelFr(c),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ))
                            .toList(),
                        onChanged: (v) {
                          if (v != null) {
                            setState(() => _commodity = v);
                            _load();
                          }
                        },
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: DropdownButtonFormField<int>(
                        initialValue: _loanAmount,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Montant',
                          isDense: true,
                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                        ),
                        items: const [
                          DropdownMenuItem(
                            value: 500000,
                            child: Text('500 000 XAF', maxLines: 1, overflow: TextOverflow.ellipsis),
                          ),
                          DropdownMenuItem(
                            value: 1000000,
                            child: Text('1 000 000 XAF', maxLines: 1, overflow: TextOverflow.ellipsis),
                          ),
                          DropdownMenuItem(
                            value: 3000000,
                            child: Text('3 000 000 XAF', maxLines: 1, overflow: TextOverflow.ellipsis),
                          ),
                          DropdownMenuItem(
                            value: 10000000,
                            child: Text('10 000 000 XAF', maxLines: 1, overflow: TextOverflow.ellipsis),
                          ),
                        ],
                        onChanged: (v) {
                          if (v != null) {
                            setState(() => _loanAmount = v);
                            _load();
                          }
                        },
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(bottom: 14),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: const Color(0xFFF8FAFC),
                  border: Border.all(color: const Color(0xFFE2E8F0)),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.only(top: 1),
                      child: Icon(Icons.info_outline_rounded, size: 16, color: Color(0xFF64748B)),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _resolveDisclaimer(),
                        style: const TextStyle(
                          color: Color(0xFF64748B),
                          fontSize: 12,
                          height: 1.45,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              if (_loading)
                const Padding(
                  padding: EdgeInsets.all(40),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (_error != null)
                FDCard(
                  child: Column(
                    children: [
                      Text(_error!, style: const TextStyle(color: FDTheme.muted)),
                      TextButton.icon(
                        onPressed: _load,
                        icon: const Icon(Icons.refresh),
                        label: const Text('Réessayer'),
                      ),
                    ],
                  ),
                )
              else if (_passports.isEmpty)
                const FDCard(
                  child: Text(
                    'Aucun résultat disponible pour cette sélection.',
                    style: TextStyle(color: FDTheme.muted),
                  ),
                )
              else
                ..._passports.map((raw) {
                  final r = Map<String, dynamic>.from(raw as Map);
                  final score = parseNum(r['credit_score'])?.toDouble() ?? 0;
                  final maxLoan = parseNum(r['recommended_max_loan_xaf']);
                  final maxLoanLabel = maxLoan != null ? '${formatXaf(maxLoan)} XAF' : '— XAF';
                  final cvLabel = _formatCv(r['cv_pct']);
                  final drawdownLabel = _formatDrawdown(r['max_drawdown_pct']);
                  final obsMonths = r['obs_months'] ?? '—';
                  final color = score >= 60
                      ? FDTheme.green
                      : (score >= 45 ? const Color(0xFFD98B24) : const Color(0xFFB54745));

                  return Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: FDCard(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Semantics(
                                label: 'Score Credit Passport ${score.toStringAsFixed(0)} sur 100',
                                child: Container(
                                  width: 48,
                                  height: 48,
                                  decoration: BoxDecoration(
                                    color: color.withValues(alpha: .10),
                                    borderRadius: BorderRadius.circular(14),
                                  ),
                                  child: Center(
                                    child: Text(
                                      score.toStringAsFixed(0),
                                      style: TextStyle(
                                        color: color,
                                        fontSize: 18,
                                        fontWeight: FontWeight.w900,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      '${r['province'] ?? 'Province non précisée'} — ${r['grade'] ?? 'Score'}',
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w700,
                                        color: FDTheme.ink,
                                        fontSize: 15,
                                      ),
                                    ),
                                    const SizedBox(height: 4),
                                    Text(
                                      '${r['policy_recommendation'] ?? 'Aucune recommandation disponible'}',
                                      style: const TextStyle(
                                        color: FDTheme.muted,
                                        fontSize: 13.5,
                                        height: 1.4,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              const SizedBox(width: 10),
                              Column(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  const Text(
                                    'Plafond LTV',
                                    style: TextStyle(fontSize: 10.5, color: FDTheme.muted),
                                  ),
                                  const SizedBox(height: 3),
                                  Text(
                                    maxLoanLabel,
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w800,
                                      fontSize: 15,
                                      color: FDTheme.ink,
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          Wrap(
                            spacing: 6,
                            runSpacing: 6,
                            children: [
                              _MetricBadge(text: 'CV : $cvLabel%'),
                              _MetricBadge(text: 'Baisse max : $drawdownLabel%'),
                              _MetricBadge(text: '$obsMonths mois'),
                            ],
                          ),
                        ],
                      ),
                    ),
                  );
                }),
            ],
          ),
        ),
      ),
    );
  }
}

class _MetricBadge extends StatelessWidget {
  final String text;
  const _MetricBadge({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0xFFF1F5F9),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 11.5,
          fontWeight: FontWeight.w600,
          color: Color(0xFF475569),
        ),
      ),
    );
  }
}
