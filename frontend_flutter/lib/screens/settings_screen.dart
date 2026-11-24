import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import '../services/session_logout.dart';
import '../widgets/auth_dialog.dart';
import 'account_screen.dart';

class SettingsScreen extends StatefulWidget {
  final ApiService apiService;
  final Future<void> Function()? onConfigureKey;
  final VoidCallback? onSessionChanged;
  final VoidCallback? onPreferencesSaved;

  const SettingsScreen({
    super.key,
    required this.apiService,
    this.onConfigureKey,
    this.onSessionChanged,
    this.onPreferencesSaved,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  static const List<Map<String, String>> _domainOptions = [
    {'id': 'auto', 'label': 'Détection automatique (Tchad)'},
    {
      'id': 'markets_and_prices',
      'label': 'Marchés et prix des produits (données actives)'
    },
    {'id': 'agriculture', 'label': 'Agriculture (données actives)'},
    {'id': 'economy', 'label': 'Économie (en préparation)'},
    {'id': 'health', 'label': 'Santé (en préparation)'},
    {'id': 'population', 'label': 'Population (en préparation)'},
    {'id': 'environment', 'label': 'Environnement (en préparation)'},
    {'id': 'infrastructure', 'label': 'Infrastructures (en préparation)'},
    {'id': 'transport', 'label': 'Transport (en préparation)'},
  ];

  static const List<String> _agroHubOptions = [
    "N'Djamena",
    'Abeche',
    'Ati',
    'Bol',
    'Bongor',
    'Doba',
    'Koumra',
    'Mao',
    'Mongo',
    'Moundou',
    'Pala',
    'Sarh',
  ];

  String _defaultDomain = 'auto';
  String _defaultAgroHub = "N'Djamena";
  bool _saving = false;
  bool _loggingOut = false;

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
    final storedHub = prefs.getString('fd_pref_agro_hub') ?? "N'Djamena";
    final validHub =
        _agroHubOptions.contains(storedHub) ? storedHub : "N'Djamena";
    setState(() {
      _defaultDomain = validDomain;
      _defaultAgroHub = validHub;
    });
  }

  Future<void> _openAuth({bool register = false}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AuthDialog(
          apiService: widget.apiService, initialRegisterMode: register),
    );
    if (ok == true && mounted) {
      widget.onSessionChanged?.call();
      setState(() {});
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
              'Connecté : ${widget.apiService.authUser?['email'] ?? 'compte actif'}'),
        ),
      );
    }
  }

  Future<void> _logout() async {
    if (_loggingOut) return;
    setState(() => _loggingOut = true);
    try {
      final result = await SessionLogout.perform(apiService: widget.apiService);
      widget.onSessionChanged?.call();
      if (!mounted) return;
      setState(() {});
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            result.cacheCleared
                ? 'Déconnexion effectuée.'
                : 'Déconnexion effectuée. Le cache local n’a pas pu être entièrement effacé.',
          ),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Déconnexion impossible. Votre session est conservée ; réessayez.',
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _loggingOut = false);
    }
  }

  Future<void> _save() async {
    if (_saving) return;
    setState(() => _saving = true);
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('fd_pref_domain', _defaultDomain);
      await prefs.setString('fd_pref_agro_hub', _defaultAgroHub);
      widget.onPreferencesSaved?.call();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Préférences enregistrées.')),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Impossible d’enregistrer les préférences. Vos modifications ne sont pas confirmées.',
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = widget.apiService.authUser;
    final loggedIn = widget.apiService.isAuthenticated;
    final isPro = widget.apiService.hasPremiumKey;
    final displayName = user?['display_name']?.toString().trim() ?? '';
    final email = user?['email']?.toString().trim() ?? '';

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
        title: const Text(
          'Préférences',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              FDCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Expanded(
                          child: Text(
                            'Compte FreeData.AI',
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink,
                            ),
                          ),
                        ),
                        if (loggedIn)
                          FDBadge(
                            label: isPro ? 'ABONNEMENT PRO' : 'PLAN GRATUIT',
                            color: isPro ? AppColors.greenDark : AppColors.blue,
                            backgroundColor: isPro
                                ? AppColors.greenSoft
                                : AppColors.blueSoft,
                          ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    if (loggedIn) ...[
                      Text(
                        displayName.isNotEmpty
                            ? '$displayName · $email'
                            : (email.isNotEmpty ? email : 'Compte actif'),
                        style: const TextStyle(
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        isPro
                            ? 'Votre espace, vos projets et vos avantages PRO sont synchronisés sur tous vos appareils.'
                            : 'Votre espace, vos discussions et vos documents privés sont synchronisés sur tous vos appareils.',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.muted,
                          height: 1.4,
                        ),
                      ),
                      const SizedBox(height: 14),
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
                                  builder: (_) => AccountScreen(
                                    apiService: widget.apiService,
                                    onConfigureKey: widget.onConfigureKey,
                                    onSessionChanged: () {
                                      widget.onSessionChanged?.call();
                                      if (mounted) setState(() {});
                                    },
                                  ),
                                ),
                              )
                                  .then((_) {
                                if (mounted) setState(() {});
                              });
                            },
                          ),
                          FDSecondaryButton(
                            label:
                                _loggingOut ? 'Déconnexion…' : 'Se déconnecter',
                            icon: Icons.logout_rounded,
                            onPressed: _loggingOut ? null : _logout,
                          ),
                        ],
                      ),
                    ] else ...[
                      const Text(
                        'Connectez-vous ou créez un compte gratuit pour synchroniser vos discussions, vos projets, vos documents privés et votre abonnement PRO.',
                        style: TextStyle(
                          fontSize: 13,
                          color: AppColors.muted,
                          height: 1.45,
                        ),
                      ),
                      const SizedBox(height: 14),
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
                    const Text(
                      'Assistant IA — Préférences d’analyse',
                      style: TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ink,
                      ),
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      'Choisissez le domaine prioritaire appliqué à l’ouverture d’une nouvelle discussion sur le Tchad.',
                      style: TextStyle(
                        fontSize: 13,
                        color: AppColors.muted,
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: 14),
                    DropdownButtonFormField<String>(
                      key: ValueKey(_defaultDomain),
                      initialValue: _defaultDomain,
                      isExpanded: true,
                      decoration: const InputDecoration(
                        labelText: 'Domaine par défaut du chat',
                        helperText:
                            'Recommandé : Détection automatique (Tchad).',
                      ),
                      items: _domainOptions
                          .map(
                            (d) => DropdownMenuItem<String>(
                              value: d['id'],
                              child: Text(d['label']!),
                            ),
                          )
                          .toList(),
                      onChanged: (v) =>
                          setState(() => _defaultDomain = v ?? 'auto'),
                    ),
                    const SizedBox(height: 14),
                    DropdownButtonFormField<String>(
                      key: ValueKey(_defaultAgroHub),
                      initialValue: _defaultAgroHub,
                      isExpanded: true,
                      decoration: const InputDecoration(
                        labelText: 'Pôle agro-climatique favori',
                        helperText:
                            'Utilisé par défaut pour vos pré-diagnostics et audits agricoles.',
                      ),
                      items: _agroHubOptions
                          .map(
                            (h) => DropdownMenuItem<String>(
                              value: h,
                              child: Text(h),
                            ),
                          )
                          .toList(),
                      onChanged: (v) =>
                          setState(() => _defaultAgroHub = v ?? "N'Djamena"),
                    ),
                    const SizedBox(height: 16),
                    FDPrimaryButton(
                      label: _saving ? 'Enregistrement…' : 'Enregistrer',
                      icon: Icons.save_outlined,
                      onPressed: _saving ? null : _save,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
