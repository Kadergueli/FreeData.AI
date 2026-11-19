import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';

class SettingsScreen extends StatefulWidget {
  final ApiService apiService;

  const SettingsScreen({super.key, required this.apiService});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  static const List<Map<String, String>> _domainOptions = [
    {'id': 'auto', 'label': 'Détection automatique'},
    {'id': 'chad_intelligence', 'label': 'Intelligence Tchad'},
    {'id': 'business_entrepreneurship', 'label': 'Business & Études'},
    {'id': 'finance', 'label': 'Finance & Risque'},
    {'id': 'agriculture', 'label': 'Agriculture & Marchés'},
    {'id': 'data_science', 'label': 'Data Science & ML'},
    {'id': 'education', 'label': 'Éducation & Révisions'},
    {'id': 'tech_programming', 'label': 'Tech & Code'},
    {'id': 'productivity', 'label': 'Productivité & Gestion'},
  ];

  String _defaultDomain = 'auto';
  final _userCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;
    final stored = prefs.getString('fd_pref_domain') ?? 'auto';
    final validDomain = _domainOptions.any((d) => d['id'] == stored) ? stored : 'auto';
    setState(() {
      _defaultDomain = validDomain;
      _userCtrl.text = prefs.getString('fd_pref_user_id') ?? widget.apiService.userId;
    });
  }

  Future<void> _save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('fd_pref_domain', _defaultDomain);
    final uid = _userCtrl.text.trim();
    var idRejected = false;
    if (uid.isNotEmpty && uid != widget.apiService.userId) {
      if (widget.apiService.setUserId(uid)) {
        await prefs.setString('fd_pref_user_id', uid);
      } else {
        idRejected = true;
      }
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(idRejected
          ? 'Identifiant refusé : 32 à 80 caractères (lettres, chiffres, - ou _). Autres préférences enregistrées.'
          : 'Préférences enregistrées.'),
    ));
  }

  @override
  void dispose() {
    _userCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(title: const Text('Préférences & Espace', style: TextStyle(fontWeight: FontWeight.w700))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          FDCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DropdownButtonFormField<String>(
                  key: ValueKey(_defaultDomain),
                  initialValue: _defaultDomain,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Domaine par défaut du chat', helperText: 'Appliqué à l’ouverture du chat.'),
                  items: _domainOptions
                      .map((d) => DropdownMenuItem<String>(value: d['id'], child: Text(d['label']!)))
                      .toList(),
                  onChanged: (v) => setState(() => _defaultDomain = v ?? 'auto'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _userCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Identifiant espace projets (X-User-Id)',
                    helperText: 'Isole vos projets : 32 à 80 caractères (lettres, chiffres, - ou _). Le changer donne accès à un autre espace.',
                  ),
                ),
                const SizedBox(height: 16),
                FDPrimaryButton(
                  label: 'Enregistrer',
                  icon: Icons.save_outlined,
                  onPressed: _save,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

