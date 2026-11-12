import 'package:flutter/material.dart';
import '../services/api_service.dart';

class PassportScreen extends StatefulWidget {
  final ApiService apiService;
  const PassportScreen({super.key, required this.apiService});

  @override
  State<PassportScreen> createState() => _PassportScreenState();
}

class _PassportScreenState extends State<PassportScreen> {
  String _commodity = 'Millet';
  int _loanAmount = 1000000;
  List<dynamic> _passports = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final items = await widget.apiService.getCreditPassports(
        commodity: _commodity,
        loanAmount: _loanAmount,
      );
      setState(() => _passports = items);
    } finally {
      setState(() => _loading = false);
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
                  value: _commodity,
                  decoration: const InputDecoration(labelText: 'Culture financée', border: OutlineInputBorder()),
                  items: const [
                    DropdownMenuItem(value: 'Millet', child: Text('Mil (Millet)')),
                    DropdownMenuItem(value: 'Sorghum (red)', child: Text('Sorgho rouge')),
                    DropdownMenuItem(value: 'Maize (white)', child: Text('Maïs blanc')),
                    DropdownMenuItem(value: 'Rice (imported)', child: Text('Riz importé')),
                    DropdownMenuItem(value: 'Groundnuts (shelled)', child: Text('Arachide')),
                    DropdownMenuItem(value: 'Sesame', child: Text('Sésame')),
                  ],
                  onChanged: (v) {
                    if (v != null) {
                      setState(() => _commodity = v);
                      _load();
                    }
                  },
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: DropdownButtonFormField<int>(
                  value: _loanAmount,
                  decoration: const InputDecoration(labelText: 'Prêt demandé (XAF)', border: OutlineInputBorder()),
                  items: const [
                    DropdownMenuItem(value: 500000, child: Text('500 000 XAF')),
                    DropdownMenuItem(value: 1000000, child: Text('1 000 000 XAF')),
                    DropdownMenuItem(value: 3000000, child: Text('3 000 000 XAF')),
                    DropdownMenuItem(value: 10000000, child: Text('10 000 000 XAF')),
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
          const SizedBox(height: 16),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : ListView.builder(
                    itemCount: _passports.length,
                    itemBuilder: (context, idx) {
                      final r = _passports[idx];
                      final score = (r['credit_score'] as num).toDouble();
                      final maxLoan = r['recommended_max_loan_xaf'];
                      return Card(
                        child: ListTile(
                          leading: CircleAvatar(
                            backgroundColor: score >= 60 ? Colors.green.shade700 : (score >= 45 ? Colors.orange.shade700 : Colors.red.shade700),
                            child: Text(score.toStringAsFixed(0), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                          ),
                          title: Text('${r['province']} — ${r['grade']}', style: const TextStyle(fontWeight: FontWeight.bold)),
                          subtitle: Text(
                            '${r['policy_recommendation']}\n'
                            'Volatilité CV : ${r['cv_pct']}% | Chute max : -${r['max_drawdown_pct']}% | ${r['obs_months']} mois',
                          ),
                          isThreeLine: true,
                          trailing: Text(
                            'Plafond LTV\n$maxLoan XAF',
                            textAlign: TextAlign.right,
                            style: const TextStyle(fontWeight: FontWeight.bold),
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
