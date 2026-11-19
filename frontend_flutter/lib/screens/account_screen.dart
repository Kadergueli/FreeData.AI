import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import '../services/conversation_storage.dart';
import '../widgets/auth_dialog.dart';
import 'subscription_screen.dart';

class AccountScreen extends StatefulWidget {
  final ApiService apiService;
  final VoidCallback? onConfigureKey;
  final VoidCallback? onSessionChanged;

  const AccountScreen({
    super.key,
    required this.apiService,
    this.onConfigureKey,
    this.onSessionChanged,
  });

  @override
  State<AccountScreen> createState() => _AccountScreenState();
}

class _AccountScreenState extends State<AccountScreen> {
  final _nameCtrl = TextEditingController();
  final _curPassCtrl = TextEditingController();
  final _newPassCtrl = TextEditingController();

  Map<String, dynamic>? _billing;
  bool _loadingBilling = false;
  bool _savingProfile = false;
  bool _changingPass = false;
  bool _syncing = false;

  @override
  void initState() {
    super.initState();
    _nameCtrl.text =
        widget.apiService.authUser?['display_name']?.toString() ?? '';
    _loadBilling();
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _curPassCtrl.dispose();
    _newPassCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadBilling() async {
    if (!widget.apiService.isAuthenticated) return;
    setState(() => _loadingBilling = true);
    try {
      final b = await widget.apiService.getMyBilling();
      if (!mounted) return;
      setState(() {
        _billing = b;
        _loadingBilling = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loadingBilling = false);
    }
  }

  Future<void> _openAuth({bool register = false}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AuthDialog(
          apiService: widget.apiService, initialRegisterMode: register),
    );
    if (ok == true && mounted) {
      _nameCtrl.text =
          widget.apiService.authUser?['display_name']?.toString() ?? '';
      widget.onSessionChanged?.call();
      await _loadBilling();
      if (mounted) setState(() {});
    }
  }

  Future<void> _saveProfile() async {
    if (_savingProfile) return;
    setState(() => _savingProfile = true);
    try {
      await widget.apiService.updateProfile(displayName: _nameCtrl.text.trim());
      widget.onSessionChanged?.call();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Profil mis à jour.')),
      );
      setState(() {});
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Erreur : $e')));
    } finally {
      if (mounted) setState(() => _savingProfile = false);
    }
  }

  Future<void> _changePassword() async {
    if (_changingPass) return;
    final cur = _curPassCtrl.text;
    final next = _newPassCtrl.text;
    if (cur.isEmpty || next.length < 8) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text(
                'Saisissez votre mot de passe actuel et un nouveau (min. 8 caractères).')),
      );
      return;
    }
    setState(() => _changingPass = true);
    try {
      await widget.apiService
          .changePassword(currentPassword: cur, newPassword: next);
      _curPassCtrl.clear();
      _newPassCtrl.clear();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Mot de passe modifié avec succès.')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _changingPass = false);
    }
  }

  Future<void> _syncNow() async {
    if (_syncing) return;
    setState(() => _syncing = true);
    try {
      final list = await LocalConversationStorage.instance
          .syncWithCloud(widget.apiService);
      widget.onSessionChanged?.call();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(
                'Synchronisation terminée (${list.length} conversation(s)).')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Synchro impossible : $e')));
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  Future<void> _exportData() async {
    try {
      final data = await widget.apiService.exportMyPrivacyData();
      await Clipboard.setData(ClipboardData(
          text: const JsonEncoder.withIndent('  ').convert(data)));
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text('Export RGPD JSON copié dans le presse-papiers.')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Export impossible : $e')));
    }
  }

  Future<void> _logout() async {
    await widget.apiService.logoutAccount();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(kAuthTokenStorageKey);
    await LocalConversationStorage.instance.saveAll(const []);
    widget.onSessionChanged?.call();
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('Déconnexion effectuée.')));
    Navigator.of(context).pop();
  }

  Future<void> _confirmDeleteAccount() async {
    final passCtrl = TextEditingController();
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Supprimer définitivement mon compte ?'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Cette action supprime définitivement votre compte, vos projets et vos conversations cloud.',
                style: TextStyle(fontSize: 13, color: AppColors.muted),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: passCtrl,
                obscureText: true,
                decoration: const InputDecoration(
                    labelText: 'Confirmez votre mot de passe'),
              ),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Annuler')),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.danger,
                  foregroundColor: Colors.white),
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Supprimer'),
            ),
          ],
        ),
      );
      if (ok != true || passCtrl.text.isEmpty) return;
      await widget.apiService.deleteAccount(password: passCtrl.text);
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(kAuthTokenStorageKey);
      await LocalConversationStorage.instance.saveAll(const []);
      widget.onSessionChanged?.call();
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Compte supprimé.')));
      Navigator.of(context).pop();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      passCtrl.dispose();
    }
  }

  static String _initials(String name, String email) {
    final src = name.trim().isNotEmpty ? name.trim() : email.trim();
    if (src.isEmpty) return 'FD';
    final parts =
        src.split(RegExp(r'[\s@._-]+')).where((p) => p.isNotEmpty).toList();
    if (parts.length >= 2) {
      return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
    }
    return src.substring(0, src.length >= 2 ? 2 : 1).toUpperCase();
  }

  @override
  Widget build(BuildContext context) {
    final loggedIn = widget.apiService.isAuthenticated;
    final user = widget.apiService.authUser;
    final name = user?['display_name']?.toString() ?? '';
    final email = user?['email']?.toString() ?? '';
    final sub = _billing?['subscription'] is Map
        ? _billing!['subscription'] as Map
        : const {};
    final planId = sub['effective_plan_id']?.toString() ??
        (widget.apiService.hasPremiumKey ? 'premium' : 'free');
    final isPro = planId == 'premium' ||
        planId == 'trial' ||
        widget.apiService.hasPremiumKey;

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
          title: const Text('Mon compte',
              style: TextStyle(fontWeight: FontWeight.w700))),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (!loggedIn) ...[
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Connectez-vous à votre espace FreeData.AI',
                        style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w800,
                            color: AppColors.ink),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Créez un compte gratuit pour discuter avec l’assistant IA, synchroniser vos conversations entre mobile et ordinateur, et gérer votre abonnement PRO.',
                        style: TextStyle(
                            fontSize: 13.5,
                            color: AppColors.muted,
                            height: 1.45),
                      ),
                      const SizedBox(height: 16),
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
                  ),
                ),
              ] else ...[
                // Carte identité & plan (responsive 375px+ sans débordement)
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          CircleAvatar(
                            radius: 26,
                            backgroundColor: AppColors.blue,
                            child: Text(
                              _initials(name, email),
                              style: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.w800,
                                  fontSize: 16),
                            ),
                          ),
                          const SizedBox(width: 14),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  name.isNotEmpty ? name : email,
                                  style: const TextStyle(
                                      fontSize: 16,
                                      fontWeight: FontWeight.w800,
                                      color: AppColors.ink),
                                ),
                                if (name.isNotEmpty)
                                  Text(email,
                                      style: const TextStyle(
                                          fontSize: 13,
                                          color: AppColors.muted)),
                                const SizedBox(height: 6),
                                FDBadge(
                                  label:
                                      isPro ? 'PARTENAIRE PRO' : 'PLAN GRATUIT',
                                  color: isPro
                                      ? AppColors.greenDark
                                      : AppColors.blue,
                                  backgroundColor: isPro
                                      ? AppColors.greenSoft
                                      : AppColors.blueSoft,
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      FDSecondaryButton(
                        label: isPro
                            ? 'Gérer mon abonnement & quotas'
                            : 'Passer à PRO',
                        icon: Icons.workspace_premium_outlined,
                        onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => SubscriptionScreen(
                              apiService: widget.apiService,
                              onConfigureKey: widget.onConfigureKey,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                // Profil
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Profil',
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink)),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _nameCtrl,
                        decoration: const InputDecoration(
                            labelText: 'Nom ou organisation affichée'),
                      ),
                      const SizedBox(height: 12),
                      FDPrimaryButton(
                        label: _savingProfile
                            ? 'Enregistrement…'
                            : 'Enregistrer le profil',
                        icon: Icons.save_outlined,
                        onPressed: _savingProfile ? null : _saveProfile,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                // Sécurité & mot de passe
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Sécurité du compte',
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink)),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _curPassCtrl,
                        obscureText: true,
                        decoration: const InputDecoration(
                            labelText: 'Mot de passe actuel'),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _newPassCtrl,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: 'Nouveau mot de passe',
                          helperText: 'Minimum 8 caractères',
                        ),
                      ),
                      const SizedBox(height: 12),
                      FDSecondaryButton(
                        label: _changingPass
                            ? 'Mise à jour…'
                            : 'Changer le mot de passe',
                        icon: Icons.lock_reset_rounded,
                        onPressed: _changingPass ? null : _changePassword,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                // Synchro cloud & RGPD
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Synchronisation & Données (RGPD)',
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink)),
                      const SizedBox(height: 6),
                      if (_loadingBilling)
                        const Padding(
                          padding: EdgeInsets.symmetric(vertical: 6),
                          child: LinearProgressIndicator(minHeight: 3),
                        )
                      else
                        const Text(
                          'Vos conversations, projets et préférences sont associés à votre compte sécurisé.',
                          style:
                              TextStyle(fontSize: 13, color: AppColors.muted),
                        ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 10,
                        runSpacing: 8,
                        children: [
                          FDSecondaryButton(
                            label: _syncing
                                ? 'Synchro…'
                                : 'Synchroniser mes discussions',
                            icon: Icons.cloud_sync_outlined,
                            onPressed: _syncing ? null : _syncNow,
                          ),
                          FDSecondaryButton(
                            label: 'Exporter mes données (JSON)',
                            icon: Icons.download_outlined,
                            onPressed: _exportData,
                          ),
                          FDSecondaryButton(
                            label: 'Se déconnecter',
                            icon: Icons.logout_rounded,
                            onPressed: _logout,
                          ),
                        ],
                      ),
                      const Divider(height: 28),
                      TextButton.icon(
                        onPressed: _confirmDeleteAccount,
                        icon: const Icon(Icons.delete_forever_outlined,
                            color: AppColors.danger),
                        label: const Text(
                          'Supprimer définitivement mon compte',
                          style: TextStyle(
                              color: AppColors.danger,
                              fontWeight: FontWeight.w700),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
