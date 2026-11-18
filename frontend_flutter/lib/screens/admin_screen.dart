import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../services/api_service.dart';

class AdminScreen extends StatefulWidget {
  final ApiService apiService;

  const AdminScreen({super.key, required this.apiService});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  final _tokenCtrl = TextEditingController();
  Map<String, dynamic>? _overview;
  bool _loading = false;
  String? _error;

  Future<void> _loadOverview() async {
    final tok = _tokenCtrl.text.trim();
    if (tok.isEmpty) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await widget.apiService.getAdminOverview(tok);
      if (!mounted) return;
      setState(() {
        _overview = data;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  void dispose() {
    _tokenCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final health = _overview?['api_health'] as Map? ?? {};
    final metrics = _overview?['api_metrics'] as Map? ?? {};
    final usersSum = _overview?['users_summary'] as Map? ?? {};
    final datasets = (_overview?['datasets'] as List? ?? []).cast<Map>();
    final audits = (_overview?['recent_audit_logs'] as List? ?? []).cast<Map>();

    return Scaffold(
      appBar: AppBar(title: const Text('Console Administration FreeData.AI')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _tokenCtrl,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Jeton Administrateur (X-Admin-Token)',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              ElevatedButton(onPressed: _loading ? null : _loadOverview, child: const Text('Charger')),
            ],
          ),
          if (_loading) ...[const SizedBox(height: 16), const Center(child: CircularProgressIndicator())],
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: const TextStyle(color: FDTheme.danger)),
          ],
          if (_overview != null) ...[
            const SizedBox(height: 16),
            Card(
              child: ListTile(
                title: Text('Santé API : ${health['status']} (v${health['version']})', style: const TextStyle(fontWeight: FontWeight.bold)),
                subtitle: Text('Requêtes : ${metrics['total_requests']} · Erreurs 5xx : ${metrics['error_5xx']} · Latence moy : ${metrics['avg_latency_ms']} ms'),
              ),
            ),
            Card(
              child: ListTile(
                title: Text('Utilisateurs : ${usersSum['total_known_users'] ?? 0}', style: const TextStyle(fontWeight: FontWeight.bold)),
                subtitle: Text('Par plan : ${usersSum['by_plan']}'),
              ),
            ),
            const SizedBox(height: 12),
            const Text('Jeux de données & Licences', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
            ...datasets.map((d) => ListTile(
                  dense: true,
                  title: Text(d['dataset_id'].toString()),
                  subtitle: Text('${d['license_category']} · Statut : ${d['publication_status']}'),
                )),
            const SizedBox(height: 12),
            const Text('Journal d’audit récent', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
            ...audits.take(10).map((a) => ListTile(
                  dense: true,
                  title: Text('${a['action']} (${a['resource_id']})'),
                  subtitle: Text('${a['actor']} [${a['actor_role']}] · ${a['created_at']}'),
                )),
          ],
        ],
      ),
    );
  }
}

