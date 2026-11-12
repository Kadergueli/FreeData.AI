import 'package:flutter/material.dart';
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

  static const String _errorText =
      'Impossible de charger les prévisions pour le moment. Réessayez dans une minute.';

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      final meta = await widget.apiService.getMetadata();
      if (!mounted) return;
      final provs = List<String>.from(meta['provinces'] ?? []);
      final comms = List<String>.from(meta['commodities'] ?? []);
      setState(() {
        _provinces = provs;
        _commodities = comms;
        _selectedProvince = provs.contains("N'Djamena") ? "N'Djamena" : (provs.isNotEmpty ? provs.first : null);
        _selectedCommodity = comms.contains('Millet') ? 'Millet' : (comms.isNotEmpty ? comms.first : null);
      });
      await _loadForecasts();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = _errorText;
      });
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
      if (!mounted) return;
      setState(() => _items = items);
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = _errorText);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  value: _selectedProvince,
                  decoration: const InputDecoration(labelText: 'Province', border: OutlineInputBorder()),
                  items: _provinces.map((p) => DropdownMenuItem(value: p, child: Text(p))).toList(),
                  onChanged: (val) {
                    setState(() => _selectedProvince = val);
                    _loadForecasts();
                  },
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: DropdownButtonFormField<String>(
                  value: _selectedCommodity,
                  decoration: const InputDecoration(labelText: 'Produit (XAF/kg)', border: OutlineInputBorder()),
                  items: _commodities.map((c) => DropdownMenuItem(value: c, child: Text(c))).toList(),
                  onChanged: (val) {
                    setState(() => _selectedCommodity = val);
                    _loadForecasts();
                  },
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? Center(child: Text(_error!))
                    : ListView.builder(
                    itemCount: _items.length,
                    itemBuilder: (context, idx) {
                      final r = _items[idx];
                      final lastPrice = (r['last_observed_price'] as num).toDouble();
                      final fcPrice = (r['forecast_t1'] as num).toDouble();
                      final pct = ((fcPrice - lastPrice) / lastPrice) * 100.0;
                      return Card(
                        child: ListTile(
                          title: Text('${r['market_name']} (${r['source']})', style: const TextStyle(fontWeight: FontWeight.bold)),
                          subtitle: Text(
                            'Dernier (${r['last_observed_month']}) : ${lastPrice.toStringAsFixed(0)} XAF/kg  |  '
                            'IC 80% : [${r['ci_low_80']} – ${r['ci_high_80']}] XAF',
                          ),
                          trailing: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              Text(
                                '${fcPrice.toStringAsFixed(0)} XAF/kg',
                                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                              ),
                              Text(
                                '${pct >= 0 ? '+' : ''}${pct.toStringAsFixed(1)}% (${r['forecast_month']})',
                                style: TextStyle(color: pct >= 0 ? Colors.orange : Colors.green),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
