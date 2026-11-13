import 'package:flutter/material.dart';
import '../core/fd_theme.dart';
import '../core/utils/formatters.dart';
import '../services/api_service.dart';

class ForecastScreen extends StatefulWidget {
  final ApiService apiService;
  const ForecastScreen({super.key, required this.apiService});

  @override
  State<ForecastScreen> createState() => _ForecastScreenState();
}

class _ForecastScreenState extends State<ForecastScreen> {
  List<String> _provinces = [];
  List<String> _commodities = [];
  String? _selectedProvince;
  String? _selectedCommodity;
  List<dynamic> _items = [];
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
      final provs = List<String>.from(meta['provinces'] ?? const []);
      final comms = List<String>.from(meta['commodities'] ?? const []);
      if (!mounted) return;
      setState(() {
        _provinces = provs;
        _commodities = comms;
        _selectedProvince = provs.contains("N'Djamena")
            ? "N'Djamena"
            : (provs.isNotEmpty ? provs.first : null);
        _selectedCommodity = comms.contains('Millet')
            ? 'Millet'
            : (comms.isNotEmpty ? comms.first : null);
      });
      await _loadForecasts();
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Impossible de charger les paramètres de prévision.';
        });
      }
    }
  }

  Future<void> _loadForecasts() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await widget.apiService.getForecasts(
        province: _selectedProvince,
        commodity: _selectedCommodity,
      );
      if (mounted) setState(() => _items = items);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Les prévisions ne sont pas accessibles pour le moment.');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
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
                        initialValue: _selectedProvince,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Province',
                          isDense: true,
                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                        ),
                        items: _provinces
                            .map((p) => DropdownMenuItem(
                                  value: p,
                                  child: Text(p, maxLines: 1, overflow: TextOverflow.ellipsis),
                                ))
                            .toList(),
                        onChanged: (v) {
                          setState(() => _selectedProvince = v);
                          _loadForecasts();
                        },
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        initialValue: _selectedCommodity,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Produit',
                          isDense: true,
                          contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                        ),
                        items: _commodities
                            .map((c) => DropdownMenuItem(
                                  value: c,
                                  child: Text(c, maxLines: 1, overflow: TextOverflow.ellipsis),
                                ))
                            .toList(),
                        onChanged: (v) {
                          setState(() => _selectedCommodity = v);
                          _loadForecasts();
                        },
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              if (_loading)
                const Padding(
                  padding: EdgeInsets.all(40),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (_error != null)
                _StateMessage(text: _error!, onRetry: _loadForecasts)
              else if (_items.isEmpty)
                const _StateMessage(text: 'Aucune prévision disponible pour ces filtres.')
              else ...[
                Text(
                  '${_items.length} résultat(s)',
                  style: const TextStyle(
                    color: FDTheme.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 10),
                ..._items.map((raw) {
                  final r = Map<String, dynamic>.from(raw as Map);
                  final last = parseNum(r['last_observed_price']) ?? 0;
                  final forecast = parseNum(r['forecast_t1']) ?? 0;
                  final pct = last == 0 ? 0.0 : ((forecast - last) / last) * 100;
                  final up = pct >= 0;
                  final ciLow = parseNum(r['ci_low_80']);
                  final ciHigh = parseNum(r['ci_high_80']);

                  return Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: FDCard(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(
                                child: Text(
                                  '${r['market_name'] ?? 'Marché non précisé'}',
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: FDTheme.ink,
                                    fontSize: 15,
                                  ),
                                ),
                              ),
                              _ChangeBadge(
                                text: '${up ? '+' : ''}${pct.toStringAsFixed(1)}%',
                                positive: !up,
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),
                          Wrap(
                            spacing: 24,
                            runSpacing: 10,
                            children: [
                              _PriceValue(
                                label: 'Dernier prix observé',
                                value: '${formatXaf(last)} XAF/kg',
                              ),
                              _PriceValue(
                                label: 'Prévision ${r['forecast_month'] ?? ''}',
                                value: '${formatXaf(forecast)} XAF/kg',
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          Text(
                            'Source : ${r['source'] ?? 'Non précisée'}  •  Dernière observation : ${r['last_observed_month'] ?? '—'}',
                            style: const TextStyle(color: FDTheme.muted, fontSize: 11.5),
                          ),
                          if (ciLow != null && ciHigh != null) ...[
                            const SizedBox(height: 3),
                            Text(
                              'Intervalle indicatif 80 % : ${formatXaf(ciLow)} – ${formatXaf(ciHigh)} XAF/kg',
                              style: const TextStyle(color: FDTheme.muted, fontSize: 11.5),
                            ),
                          ],
                        ],
                      ),
                    ),
                  );
                }),
              ],
              const SizedBox(height: 12),
              const Text(
                'Une prévision est une estimation issue du modèle, et non un prix observé ou garanti.',
                style: TextStyle(color: FDTheme.muted, fontSize: 11.5),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PriceValue extends StatelessWidget {
  final String label;
  final String value;
  const _PriceValue({required this.label, required this.value});

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 11.5, color: FDTheme.muted)),
          const SizedBox(height: 3),
          Text(
            value,
            style: const TextStyle(
              fontSize: 17,
              fontWeight: FontWeight.w800,
              color: FDTheme.ink,
            ),
          ),
        ],
      );
}

class _ChangeBadge extends StatelessWidget {
  final String text;
  final bool positive;
  const _ChangeBadge({required this.text, required this.positive});

  @override
  Widget build(BuildContext context) {
    final color = positive ? FDTheme.green : const Color(0xFFB54745);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .09),
        borderRadius: BorderRadius.circular(30),
      ),
      child: Text(
        text,
        style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12),
      ),
    );
  }
}

class _StateMessage extends StatelessWidget {
  final String text;
  final VoidCallback? onRetry;
  const _StateMessage({required this.text, this.onRetry});

  @override
  Widget build(BuildContext context) => FDCard(
        child: Column(
          children: [
            const Icon(Icons.query_stats, size: 30, color: FDTheme.muted),
            const SizedBox(height: 10),
            Text(text, textAlign: TextAlign.center, style: const TextStyle(color: FDTheme.muted)),
            if (onRetry != null)
              TextButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Réessayer'),
              ),
          ],
        ),
      );
}
