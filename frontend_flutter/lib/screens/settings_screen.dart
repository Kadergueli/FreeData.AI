import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import '../services/conversation_storage.dart';
import '../widgets/auth_dialog.dart';
import 'account_screen.dart';

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
    final validDomain =
        _domainOptions.any((d) => d['id'] == stored) ? stored : 'auto';
    setState(() {
      _defaultDomain = validDomain;
      _userCtrl.text = widget.apiService.isAuthenticated
          ? widget.apiService.userId
          : (prefs.getString('fd_pref_user_id') ?? widget.apiService.userId);
    });
  }

  Future<void> _openAuth({bool register = false}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AuthDialog(
          apiService: widget.apiService, initialRegisterMode: register),
    );
    if (ok == true && mounted) {
      setState(() => _userCtrl.text = widget.apiService.userId);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
              'Connecté : ${widget.apiService.authUser?['email'] ?? 'compte actif'}'),
        ),
      );
    }
  }

  Future<void> _logout() async {
    await widget.apiService.logoutAccount();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(kAuthTokenStorageKey);
    await LocalConversationStorage.instance.saveAll(const []);
    if (!mounted) return;
    setState(() {});
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Déconnexion effectuée.')),
    );
  }

  Future<void> _save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('fd_pref_domain', _defaultDomain);
    final uid = _userCtrl.text.trim();
    var idRejected = false;
    if (!widget.apiService.isAuthenticated &&
        uid.isNotEmpty &&
        uid != widget.apiService.userId) {
      if (widget.apiService.setUserId(uid)) {
        await prefs.setString('fd_pref_user_id', uid);
      } else {
        idRejected = true;
      }
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          idRejected
              ? 'Identifiant refusé : 32 à 80 caractères (lettres, chiffres, - ou _). Autres préférences enregistrées.'
              : 'Préférences enregistrées.',
        ),
      ),
    );
  }

  @override
  void dispose() {
    _userCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final user = widget.apiService.authUser;
    final loggedIn = widget.apiService.isAuthenticated;

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
          title: const Text('Préférences & Espace',
              style: TextStyle(fontWeight: FontWeight.w700))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          FDCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Compte FreeData.AI',
                  style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.ink),
                ),
                const SizedBox(height: 8),
                if (loggedIn) ...[
                  Text(
                    'Connecté : ${user?['email'] ?? 'Utilisateur'}'
                    '${(user?['display_name']?.toString().isNotEmpty ?? false) ? ' (${user!['display_name']})' : ''}',
                    style: const TextStyle(
                        fontWeight: FontWeight.w600, color: AppColors.ink),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    widget.apiService.hasSubscriptionPro
                        ? 'Statut compte : Abonnement PRO actif (session Bearer sécurisée)'
                        : 'Statut compte : Session Bearer sécurisée active',
                    style:
                        const TextStyle(fontSize: 12.5, color: AppColors.muted),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 10,
                    runSpacing: 8,
                    children: [
                      FDPrimaryButton(
                        label: 'Gérer mon compte',
                        icon: Icons.person_outline_rounded,
                        onPressed: () {
                          Navigator.of(context)
                              .push(
                            MaterialPageRoute(
                              builder: (_) =>
                                  AccountScreen(apiService: widget.apiService),
                            ),
                          )
                              .then((_) {
                            if (mounted) setState(() {});
                          });
                        },
                      ),
                      FDSecondaryButton(
                        label: 'Se déconnecter',
                        icon: Icons.logout_rounded,
                        onPressed: _logout,
                      ),
                    ],
                  ),
                ] else ...[
                  const Text(
                    'Connectez-vous pour synchroniser vos projets, quotas et votre accès PRO sur tous vos appareils.',
                    style: TextStyle(fontSize: 13, color: AppColors.muted),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 10,
                    runSpacing: 8,
                    children: [
                      FDPrimaryButton(
                        label: 'Se connecter',
                        icon: Icons.login_rounded,
                        onPressed: () => _openAuth(register: false),
                      ),
                      FDSecondaryButton(
                        label: 'Créer un compte',
                        icon: Icons.person_add_alt_1_rounded,
                        onPressed: () => _openAuth(register: true),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 14),
          FDCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DropdownButtonFormField<String>(
                  key: ValueKey(_defaultDomain),
                  initialValue: _defaultDomain,
                  isExpanded: true,
                  decoration: const InputDecoration(
                    labelText: 'Domaine par défaut du chat',
                    helperText: 'Appliqué à l’ouverture du chat.',
                  ),
                  items: _domainOptions
                      .map((d) => DropdownMenuItem<String>(
                          value: d['id'], child: Text(d['label']!)))
                      .toList(),
                  onChanged: (v) =>
                      setState(() => _defaultDomain = v ?? 'auto'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _userCtrl,
                  readOnly: loggedIn,
                  decoration: InputDecoration(
                    labelText: 'Identifiant espace projets (X-User-Id)',
                    helperText: loggedIn
                        ? 'Lié automatiquement à votre compte connecté.'
                        : 'Isole vos projets : 32 à 80 caractères (lettres, chiffres, - ou _). Le changer donne accès à un autre espace.',
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
