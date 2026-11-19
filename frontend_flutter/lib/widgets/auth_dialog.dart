import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';

const String kAuthTokenStorageKey = 'fd_auth_token_v1';

class AuthDialog extends StatefulWidget {
  final ApiService apiService;
  final bool initialRegisterMode;
  final String? reasonBanner;

  const AuthDialog({
    super.key,
    required this.apiService,
    this.initialRegisterMode = false,
    this.reasonBanner,
  });

  @override
  State<AuthDialog> createState() => _AuthDialogState();
}

class _AuthDialogState extends State<AuthDialog> {
  late bool _registerMode = widget.initialRegisterMode;
  final _emailCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _nameCtrl = TextEditingController();
  bool _obscurePassword = true;
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passCtrl.dispose();
    _nameCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) return;
    final email = _emailCtrl.text.trim();
    final pass = _passCtrl.text;
    if (!email.contains('@') || !email.contains('.')) {
      setState(() => _error = 'Veuillez saisir une adresse e-mail valide.');
      return;
    }
    if (_registerMode && pass.length < 8) {
      setState(() =>
          _error = 'Le mot de passe doit contenir au moins 8 caractères.');
      return;
    }
    if (!_registerMode && pass.isEmpty) {
      setState(() => _error = 'Veuillez saisir votre mot de passe.');
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final res = _registerMode
          ? await widget.apiService.registerAccount(
              email: email,
              password: pass,
              displayName: _nameCtrl.text.trim(),
            )
          : await widget.apiService.loginAccount(email: email, password: pass);

      final prefs = await SharedPreferences.getInstance();
      final tok = res['token']?.toString() ?? '';
      if (tok.isNotEmpty) {
        await prefs.setString(kAuthTokenStorageKey, tok);
      }
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _submitting = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      backgroundColor: AppColors.surface,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 430),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: AppColors.blue,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    alignment: Alignment.center,
                    child: const Text(
                      'FD',
                      style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w800,
                          fontSize: 14),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _registerMode
                              ? 'Créer votre compte'
                              : 'Bienvenue sur FreeData.AI',
                          style: const TextStyle(
                              fontSize: 17,
                              fontWeight: FontWeight.w800,
                              color: AppColors.ink),
                        ),
                        const Text(
                          'Votre espace IA & marchés du Tchad',
                          style:
                              TextStyle(fontSize: 12.5, color: AppColors.muted),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close_rounded,
                        size: 20, color: AppColors.muted),
                    onPressed: _submitting
                        ? null
                        : () => Navigator.of(context).pop(false),
                    tooltip: 'Fermer',
                  ),
                ],
              ),
              if (widget.reasonBanner != null &&
                  widget.reasonBanner!.trim().isNotEmpty) ...[
                const SizedBox(height: 14),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  decoration: BoxDecoration(
                    color: AppColors.blueSoft,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                        color: AppColors.blue.withValues(alpha: 0.2)),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.lock_outline_rounded,
                          size: 17, color: AppColors.blue),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          widget.reasonBanner!,
                          style: const TextStyle(
                              fontSize: 12.5,
                              color: AppColors.blueDark,
                              height: 1.35),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: AppColors.canvasSoft,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: _modeTab(
                        label: 'Se connecter',
                        selected: !_registerMode,
                        onTap: _submitting
                            ? null
                            : () => setState(() {
                                  _registerMode = false;
                                  _error = null;
                                }),
                      ),
                    ),
                    Expanded(
                      child: _modeTab(
                        label: 'Créer un compte',
                        selected: _registerMode,
                        onTap: _submitting
                            ? null
                            : () => setState(() {
                                  _registerMode = true;
                                  _error = null;
                                }),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              if (_registerMode) ...[
                TextField(
                  controller: _nameCtrl,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: 'Nom ou organisation (optionnel)',
                    prefixIcon: Icon(Icons.person_outline_rounded, size: 19),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              TextField(
                controller: _emailCtrl,
                keyboardType: TextInputType.emailAddress,
                textInputAction: TextInputAction.next,
                decoration: const InputDecoration(
                  labelText: 'Adresse e-mail',
                  prefixIcon: Icon(Icons.email_outlined, size: 19),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _passCtrl,
                obscureText: _obscurePassword,
                onSubmitted: (_) => _submit(),
                decoration: InputDecoration(
                  labelText: 'Mot de passe',
                  helperText: _registerMode ? 'Minimum 8 caractères' : null,
                  prefixIcon: const Icon(Icons.key_outlined, size: 19),
                  suffixIcon: IconButton(
                    icon: Icon(
                      _obscurePassword
                          ? Icons.visibility_outlined
                          : Icons.visibility_off_outlined,
                      size: 19,
                    ),
                    onPressed: () =>
                        setState(() => _obscurePassword = !_obscurePassword),
                  ),
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: AppColors.dangerSoft,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.dangerBorder),
                  ),
                  child: Text(
                    _error!,
                    style: const TextStyle(
                        color: AppColors.dangerDark,
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600),
                  ),
                ),
              ],
              const SizedBox(height: 18),
              FDPrimaryButton(
                expanded: true,
                label: _submitting
                    ? 'Patientez…'
                    : (_registerMode
                        ? 'Créer mon compte gratuit'
                        : 'Se connecter'),
                icon: _registerMode
                    ? Icons.person_add_alt_1_rounded
                    : Icons.login_rounded,
                onPressed: _submitting ? null : _submit,
              ),
              const SizedBox(height: 8),
              const Text(
                'Compte gratuit inclus · Synchronisation cloud de vos conversations et projets.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 11.5, color: AppColors.subtle),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _modeTab(
      {required String label,
      required bool selected,
      required VoidCallback? onTap}) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(9),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 9),
        decoration: BoxDecoration(
          color: selected ? AppColors.surface : Colors.transparent,
          borderRadius: BorderRadius.circular(9),
          boxShadow: selected
              ? [
                  const BoxShadow(
                      color: AppColors.shadow,
                      blurRadius: 4,
                      offset: Offset(0, 1))
                ]
              : null,
        ),
        alignment: Alignment.center,
        child: Text(
          label,
          style: TextStyle(
            fontSize: 13,
            fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
            color: selected ? AppColors.ink : AppColors.muted,
          ),
        ),
      ),
    );
  }
}
