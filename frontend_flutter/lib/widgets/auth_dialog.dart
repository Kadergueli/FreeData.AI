import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';

const String kAuthTokenStorageKey = 'fd_auth_token_v1';

class AuthDialog extends StatefulWidget {
  final ApiService apiService;
  final bool initialRegisterMode;

  const AuthDialog({
    super.key,
    required this.apiService,
    this.initialRegisterMode = false,
  });

  @override
  State<AuthDialog> createState() => _AuthDialogState();
}

class _AuthDialogState extends State<AuthDialog> {
  late bool _registerMode = widget.initialRegisterMode;
  final _emailCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _nameCtrl = TextEditingController();
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
      final uid = widget.apiService.userId;
      if (ApiService.isStrongUserId(uid)) {
        await prefs.setString('fd_pref_user_id', uid);
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
    return AlertDialog(
      title: Text(_registerMode
          ? 'Créer un compte FreeData.AI'
          : 'Connexion FreeData.AI'),
      content: SizedBox(
        width: 400,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Synchronisez vos projets, quotas et votre accès PRO sur tous vos appareils.',
                style: TextStyle(fontSize: 13, color: AppColors.muted),
              ),
              const SizedBox(height: 12),
              if (_registerMode) ...[
                TextField(
                  controller: _nameCtrl,
                  decoration: const InputDecoration(
                      labelText: 'Nom ou organisation (optionnel)'),
                ),
                const SizedBox(height: 10),
              ],
              TextField(
                controller: _emailCtrl,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Adresse e-mail'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _passCtrl,
                obscureText: true,
                onSubmitted: (_) => _submit(),
                decoration: InputDecoration(
                  labelText: 'Mot de passe',
                  helperText: _registerMode ? 'Minimum 8 caractères' : null,
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 10),
                Text(
                  _error!,
                  style: const TextStyle(
                      color: AppColors.danger,
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600),
                ),
              ],
              const SizedBox(height: 8),
              TextButton(
                onPressed: _submitting
                    ? null
                    : () => setState(() {
                          _registerMode = !_registerMode;
                          _error = null;
                        }),
                child: Text(
                  _registerMode
                      ? 'Déjà inscrit ? Se connecter'
                      : 'Pas encore de compte ? Créer un compte',
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed:
              _submitting ? null : () => Navigator.of(context).pop(false),
          child: const Text('Annuler'),
        ),
        FDPrimaryButton(
          label: _submitting
              ? 'Patientez…'
              : (_registerMode ? 'Créer le compte' : 'Se connecter'),
          icon: _registerMode
              ? Icons.person_add_alt_1_rounded
              : Icons.login_rounded,
          onPressed: _submitting ? null : _submit,
        ),
      ],
    );
  }
}
