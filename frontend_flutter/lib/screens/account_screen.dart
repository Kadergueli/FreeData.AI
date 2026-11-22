import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/pdf_download.dart';
import '../services/api_service.dart';
import '../services/conversation_storage.dart';
import '../widgets/auth_dialog.dart';
import 'subscription_screen.dart';

class AccountScreen extends StatefulWidget {
  final ApiService apiService;
  final Future<void> Function()? onConfigureKey;
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
  Map<String, dynamic>? _billing;
  Map<String, dynamic>? _agroProfile;
  List<Map<String, dynamic>> _myDocs = const [];
  bool _loadingBilling = false;
  bool _savingProfile = false;
  bool _savingAgroProfile = false;
  bool _changingPass = false;
  bool _syncing = false;

  @override
  void initState() {
    super.initState();
    if (widget.apiService.isAuthenticated) {
      _billing = widget.apiService.cachedMyBilling;
    }
    _loadBilling();
  }

  @override
  void dispose() {
    super.dispose();
  }

  Future<void> _loadBilling() async {
    if (!widget.apiService.isAuthenticated) return;
    setState(() => _loadingBilling = true);
    try {
      final billingFuture = widget.apiService
          .getMyBilling()
          .then<Map<String, dynamic>?>((v) => v)
          .catchError((_) => null);
      final docsFuture = widget.apiService
          .listUserDocuments()
          .catchError((_) => const <Map<String, dynamic>>[]);
      final agroFuture =
          widget.apiService.getMyAgroProfile().catchError((_) => null);
      final results =
          await Future.wait<Object?>([billingFuture, docsFuture, agroFuture]);
      final b = results[0] as Map<String, dynamic>?;
      final docs = results[1] as List<Map<String, dynamic>>;
      final agroProf = results[2] as Map<String, dynamic>?;
      if (!mounted) return;
      setState(() {
        _billing = b;
        _myDocs = docs;
        _agroProfile = agroProf;
        _loadingBilling = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loadingBilling = false);
    }
  }

  Future<void> _deleteDoc(String docId, String filename) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Supprimer ce document ?'),
        content: Text(
          'Le document « $filename » et ses segments d’indexation seront définitivement supprimés de votre compte.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Annuler'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.danger,
              foregroundColor: Colors.white,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Supprimer'),
          ),
        ],
      ),
    );
    if (confirm != true || !mounted) return;
    try {
      await widget.apiService.deleteUserDocument(docId);
      if (!mounted) return;
      setState(() {
        _myDocs = _myDocs.where((d) => d['doc_id'] != docId).toList();
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Document privé « $filename » supprimé.')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Suppression impossible : $e')));
    }
  }

  Future<void> _openAuth({bool register = false}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AuthDialog(
          apiService: widget.apiService, initialRegisterMode: register),
    );
    if (ok == true && mounted) {
      widget.onSessionChanged?.call();
      await _loadBilling();
      if (mounted) setState(() {});
    }
  }

  Future<void> _openEditNameDialog() async {
    if (_savingProfile) return;
    final currentName =
        widget.apiService.authUser?['display_name']?.toString() ?? '';
    final ctrl = TextEditingController(text: currentName);
    String? errorText;
    try {
      final newName = await showDialog<String>(
        context: context,
        builder: (ctx) => StatefulBuilder(
          builder: (ctx, setDialogState) => AlertDialog(
            title: const Text('Modifier le nom'),
            content: SizedBox(
              width: 380,
              child: TextField(
                controller: ctrl,
                autofocus: true,
                textInputAction: TextInputAction.done,
                decoration: InputDecoration(
                  labelText: 'Nom ou organisation affichée',
                  errorText: errorText,
                ),
                onSubmitted: (_) {
                  final v = ctrl.text.trim();
                  if (v.length < 2) {
                    setDialogState(() => errorText = 'Minimum 2 caractères.');
                    return;
                  }
                  Navigator.pop(ctx, v);
                },
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Annuler'),
              ),
              ElevatedButton(
                onPressed: () {
                  final v = ctrl.text.trim();
                  if (v.length < 2) {
                    setDialogState(() => errorText = 'Minimum 2 caractères.');
                    return;
                  }
                  Navigator.pop(ctx, v);
                },
                child: const Text('Enregistrer'),
              ),
            ],
          ),
        ),
      );
      if (newName == null || !mounted) return;
      setState(() => _savingProfile = true);
      try {
        await widget.apiService.updateProfile(displayName: newName);
        widget.onSessionChanged?.call();
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Nom mis à jour.')),
        );
        setState(() {});
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Erreur : $e')));
      } finally {
        if (mounted) setState(() => _savingProfile = false);
      }
    } finally {
      // Le contrôleur local est libéré après l'animation de fermeture du dialogue.
    }
  }

  Future<void> _openChangePasswordDialog() async {
    if (_changingPass) return;
    final curCtrl = TextEditingController();
    final nextCtrl = TextEditingController();
    final confirmCtrl = TextEditingController();
    String? errorText;
    try {
      final result = await showDialog<Map<String, String>>(
        context: context,
        builder: (ctx) => StatefulBuilder(
          builder: (ctx, setDialogState) => AlertDialog(
            title: const Text('Changer le mot de passe'),
            content: SizedBox(
              width: 400,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: curCtrl,
                    obscureText: true,
                    autofocus: true,
                    decoration: const InputDecoration(
                      labelText: 'Mot de passe actuel',
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: nextCtrl,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: 'Nouveau mot de passe',
                      helperText: 'Minimum 8 caractères',
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: confirmCtrl,
                    obscureText: true,
                    decoration: InputDecoration(
                      labelText: 'Confirmer le nouveau mot de passe',
                      errorText: errorText,
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Annuler'),
              ),
              ElevatedButton(
                onPressed: () {
                  final cur = curCtrl.text;
                  final next = nextCtrl.text;
                  final conf = confirmCtrl.text;
                  if (cur.isEmpty || next.length < 8) {
                    setDialogState(() => errorText =
                        'Mot de passe actuel requis et 8 caractères minimum.');
                    return;
                  }
                  if (next != conf) {
                    setDialogState(() =>
                        errorText = 'Les nouveaux mots de passe diffèrent.');
                    return;
                  }
                  Navigator.pop(ctx, {'cur': cur, 'next': next});
                },
                child: const Text('Mettre à jour'),
              ),
            ],
          ),
        ),
      );
      if (result == null || !mounted) return;
      setState(() => _changingPass = true);
      try {
        await widget.apiService.changePassword(
          currentPassword: result['cur']!,
          newPassword: result['next']!,
        );
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Mot de passe modifié avec succès.')),
        );
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      } finally {
        if (mounted) setState(() => _changingPass = false);
      }
    } finally {
      // Les contrôleurs locaux sont libérés après l'animation de fermeture du dialogue.
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
      final jsonStr = const JsonEncoder.withIndent('  ').convert(data);
      triggerFileDownload(
        Uint8List.fromList(utf8.encode(jsonStr)),
        'freedata_rgpd_export.json',
        'application/json',
      );
      await Clipboard.setData(ClipboardData(text: jsonStr));
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text(
                'Export RGPD téléchargé (freedata_rgpd_export.json) et copié.')),
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

  Widget _buildAgroOfficialProfileCard() {
    final prof = _agroProfile;
    final status = prof?['status']?.toString() ?? 'unsubmitted';
    final isApproved = status == 'approved';
    final isPending = status == 'pending';
    final isRejected = status == 'rejected';
    final badgeLabel = isApproved
        ? 'VALIDÉ PAR L’ADMIN'
        : (isPending
            ? 'EN ATTENTE DE VALIDATION'
            : (isRejected ? 'REFUSÉ' : 'NON SOUMIS'));
    final badgeColor = isApproved
        ? AppColors.greenDark
        : (isRejected ? AppColors.danger : AppColors.blue);
    final badgeBg = isApproved
        ? AppColors.greenSoft
        : (isRejected ? const Color(0xFFFEE2E2) : AppColors.blueSoft);

    return FDCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              const Text(
                'Profil officiel Agronome / Cabinet (PDF)',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppColors.ink,
                ),
              ),
              FDBadge(
                label: badgeLabel,
                color: badgeColor,
                backgroundColor: badgeBg,
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            'Renseignez vos informations officielles et soumettez-les à l’administrateur. Une fois validées, elles seront automatiquement pré-remplies sur vos rapports PDF Agronome PRO.',
            style: TextStyle(fontSize: 12.5, color: AppColors.muted),
          ),
          if (prof != null) ...[
            const SizedBox(height: 10),
            Text(
              '${prof['firm_name']} · Agrément : ${prof['license_number']}',
              style: const TextStyle(
                fontWeight: FontWeight.w700,
                color: AppColors.ink,
              ),
            ),
            if ((prof['address']?.toString() ?? '').isNotEmpty ||
                (prof['contact']?.toString() ?? '').isNotEmpty)
              Text(
                '${prof['address'] ?? ''}${(prof['address']?.toString().isNotEmpty ?? false) && (prof['contact']?.toString().isNotEmpty ?? false) ? ' · ' : ''}${prof['contact'] ?? ''}',
                style: const TextStyle(fontSize: 12.5, color: AppColors.muted),
              ),
            if (isRejected &&
                (prof['admin_note']?.toString().isNotEmpty ?? false))
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  'Motif : ${prof['admin_note']}',
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: AppColors.danger,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
          ],
          const SizedBox(height: 12),
          FDSecondaryButton(
            label: _savingAgroProfile
                ? 'Envoi…'
                : (prof == null
                    ? 'Renseigner & soumettre mon profil officiel'
                    : 'Mettre à jour mes informations officielles'),
            icon: Icons.verified_user_outlined,
            onPressed: _savingAgroProfile ? null : _openSubmitAgroProfileDialog,
          ),
        ],
      ),
    );
  }

  Future<void> _openSubmitAgroProfileDialog() async {
    final firmCtrl = TextEditingController(
        text: _agroProfile?['firm_name']?.toString() ?? '');
    final licCtrl = TextEditingController(
        text: _agroProfile?['license_number']?.toString() ?? '');
    final addrCtrl =
        TextEditingController(text: _agroProfile?['address']?.toString() ?? '');
    final contactCtrl =
        TextEditingController(text: _agroProfile?['contact']?.toString() ?? '');
    String? err;

    try {
      final submitted = await showDialog<bool>(
        context: context,
        builder: (ctx) => StatefulBuilder(
          builder: (ctx, setDlg) => AlertDialog(
            title: const Text('Informations officielles Agronome / Cabinet'),
            content: SizedBox(
              width: 440,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextField(
                      controller: firmCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Raison sociale / Nom officiel *',
                      ),
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      controller: licCtrl,
                      decoration: const InputDecoration(
                        labelText: 'N° d’agrément / Ordre / RCCM *',
                      ),
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      controller: addrCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Adresse officielle / Ville',
                      ),
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      controller: contactCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Téléphone & Email professionnel',
                      ),
                    ),
                    if (err != null) ...[
                      const SizedBox(height: 8),
                      Text(err!,
                          style: const TextStyle(color: AppColors.danger)),
                    ],
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Annuler'),
              ),
              ElevatedButton(
                onPressed: () {
                  if (firmCtrl.text.trim().length < 2 ||
                      licCtrl.text.trim().length < 2) {
                    setDlg(() => err =
                        'Nom officiel et numéro d’agrément requis (min. 2 caractères).');
                    return;
                  }
                  Navigator.pop(ctx, true);
                },
                child: const Text('Soumettre à l’admin'),
              ),
            ],
          ),
        ),
      );
      if (submitted != true || !mounted) return;
      setState(() => _savingAgroProfile = true);
      try {
        final updated = await widget.apiService.submitMyAgroProfile(
          firmName: firmCtrl.text,
          licenseNumber: licCtrl.text,
          address: addrCtrl.text,
          contact: contactCtrl.text,
        );
        if (!mounted) return;
        setState(() => _agroProfile = updated);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
                'Profil officiel envoyé à l’administrateur pour validation.'),
          ),
        );
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      } finally {
        if (mounted) setState(() => _savingAgroProfile = false);
      }
    } finally {
      firmCtrl.dispose();
      licCtrl.dispose();
      addrCtrl.dispose();
      contactCtrl.dispose();
    }
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
                      if (_billing?['usage'] is Map) ...[
                        Builder(builder: (_) {
                          final usage = _billing!['usage'] as Map;
                          final chatUsed = usage['daily_chat_used'] ?? 0;
                          final chatLimit =
                              usage['daily_chat_limit'] ?? (isPro ? 500 : 30);
                          return Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: [
                              FDBadge(
                                label: 'Messages IA : $chatUsed / $chatLimit',
                                color: AppColors.ink,
                                backgroundColor: AppColors.canvas,
                              ),
                              FDBadge(
                                label: 'Documents privés : ${_myDocs.length}',
                                color: AppColors.blue,
                                backgroundColor: AppColors.blueSoft,
                              ),
                            ],
                          );
                        }),
                        const SizedBox(height: 12),
                      ],
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
                _buildAgroOfficialProfileCard(),
                const SizedBox(height: 14),
                // Informations personnelles (lecture seule + modal sur action, style Google / ChatGPT)
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Informations personnelles',
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink)),
                      const SizedBox(height: 8),
                      ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        title: const Text(
                          'Nom affiché',
                          style:
                              TextStyle(fontSize: 12.5, color: AppColors.muted),
                        ),
                        subtitle: Text(
                          name.isNotEmpty ? name : 'Non renseigné',
                          style: const TextStyle(
                              fontSize: 14.5,
                              fontWeight: FontWeight.w600,
                              color: AppColors.ink),
                        ),
                        trailing: TextButton(
                          key: const ValueKey('edit-name-btn'),
                          onPressed:
                              _savingProfile ? null : _openEditNameDialog,
                          child: Text(
                              _savingProfile ? 'Enregistrement…' : 'Modifier'),
                        ),
                      ),
                      const Divider(height: 12),
                      ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        title: const Text(
                          'Adresse e-mail',
                          style:
                              TextStyle(fontSize: 12.5, color: AppColors.muted),
                        ),
                        subtitle: Text(
                          email,
                          style: const TextStyle(
                              fontSize: 14.5,
                              fontWeight: FontWeight.w600,
                              color: AppColors.ink),
                        ),
                        trailing: const Icon(
                          Icons.lock_outline_rounded,
                          size: 18,
                          color: AppColors.subtle,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                // Sécurité & mot de passe (lecture seule + modal dédiée)
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Sécurité du compte',
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink)),
                      const SizedBox(height: 8),
                      ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        title: const Text(
                          'Mot de passe',
                          style:
                              TextStyle(fontSize: 12.5, color: AppColors.muted),
                        ),
                        subtitle: const Text(
                          '••••••••••••',
                          style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 1.5,
                              color: AppColors.ink),
                        ),
                        trailing: TextButton(
                          key: const ValueKey('edit-password-btn'),
                          onPressed:
                              _changingPass ? null : _openChangePasswordDialog,
                          child:
                              Text(_changingPass ? 'Mise à jour…' : 'Modifier'),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                // Coffre-fort de documents privés (Jina + Groq)
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Coffre-fort de documents privés',
                        style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'Vos documents (PDF, CSV, TXT, MD, JSON) joints depuis le chat sont indexés pour la recherche sémantique IA et restent strictement isolés sur votre compte.',
                        style: TextStyle(fontSize: 13, color: AppColors.muted),
                      ),
                      const SizedBox(height: 10),
                      if (_myDocs.isEmpty)
                        const Text(
                          'Aucun document privé téléversé pour le moment.',
                          style: TextStyle(
                              fontSize: 12.5, color: AppColors.subtle),
                        )
                      else
                        ..._myDocs.map((d) {
                          final docId = d['doc_id']?.toString() ?? '';
                          final fname = d['filename']?.toString() ?? 'Document';
                          final chunks = d['chunks_count'] ?? 1;
                          final idxStatus =
                              d['indexing_status']?.toString() ?? 'complete';
                          return ListTile(
                            dense: true,
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.description_outlined,
                                color: AppColors.blue, size: 20),
                            title: Text(fname,
                                style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                    color: AppColors.ink)),
                            subtitle: Text(
                                '$chunks segment(s) · Indexation : ${idxStatus == 'complete' ? 'Complète' : 'Partielle'}',
                                style: const TextStyle(
                                    fontSize: 12, color: AppColors.muted)),
                            trailing: IconButton(
                              icon: const Icon(Icons.delete_outline_rounded,
                                  color: AppColors.danger, size: 19),
                              tooltip: 'Supprimer ce document',
                              onPressed: () => _deleteDoc(docId, fname),
                            ),
                          );
                        }),
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
