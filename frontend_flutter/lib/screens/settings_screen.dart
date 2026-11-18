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
  String _language = 'fr';
  String _style = 'concis';
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
    setState(() {
      _language = prefs.getString('fd_pref_lang') ?? 'fr';
      _style = prefs.getString('fd_pref_style') ?? 'concis';
      _defaultDomain = prefs.getString('fd_pref_domain') ?? 'auto';
      _userCtrl.text = prefs.getString('fd_pref_user_id') ?? widget.apiService.userId;
    });
  }

  Future<void> _save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('fd_pref_lang', _language);
    await prefs.setString('fd_pref_style', _style);
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
                  initialValue: _language,
                  decoration: const InputDecoration(labelText: 'Langue des rapports'),
                  items: const [
                    DropdownMenuItem(value: 'fr', child: Text('Français')),
                    DropdownMenuItem(value: 'en', child: Text('English')),
                  ],
                  onChanged: (v) => setState(() => _language = v ?? 'fr'),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _style,
                  decoration: const InputDecoration(labelText: 'Style de réponse préféré'),
                  items: const [
                    DropdownMenuItem(value: 'concis', child: Text('Concis & opérationnel')),
                    DropdownMenuItem(value: 'detaille', child: Text('Détaillé & académique')),
                  ],
                  onChanged: (v) => setState(() => _style = v ?? 'concis'),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _defaultDomain,
                  decoration: const InputDecoration(labelText: 'Domaine par défaut'),
                  items: const [
                    DropdownMenuItem(value: 'auto', child: Text('Détection automatique')),
                    DropdownMenuItem(value: 'chad_intelligence', child: Text('Intelligence Tchad')),
                    DropdownMenuItem(value: 'business_entrepreneurship', child: Text('Business & Études')),
                    DropdownMenuItem(value: 'tech_programming', child: Text('Tech & Code')),
                  ],
                  onChanged: (v) => setState(() => _defaultDomain = v ?? 'auto'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _userCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Identifiant espace projets (X-User-Id)',
                    helperText: 'Utilisé pour isoler vos projets (minimum 3 caractères).',
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

