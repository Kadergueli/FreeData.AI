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

  int _passwordStrength(String p) {
    if (p.isEmpty) return 0;
    int score = 0;
    if (p.length >= 8) score++;
    if (RegExp(r'[A-Z]').hasMatch(p) && RegExp(r'[a-z]').hasMatch(p)) score++;
    if (RegExp(r'[0-9]').hasMatch(p) || RegExp(r'[^A-Za-z0-9]').hasMatch(p)) {
      score++;
    }
    return score;
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
    final isWide = MediaQuery.sizeOf(context).width >= 760;

    return Dialog(
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
      backgroundColor: AppColors.surface,
      insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: isWide ? 840 : 440),
        child: isWide
            ? IntrinsicHeight(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SizedBox(width: 340, child: _buildBrandPanel()),
                    Expanded(child: _buildFormPanel(showBrandHeader: false)),
                  ],
                ),
              )
            : _buildFormPanel(showBrandHeader: true),
      ),
    );
  }

  Widget _buildBrandPanel() {
    return Container(
      padding: const EdgeInsets.all(28),
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF0F172A), Color(0xFF1E293B)],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
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
                    fontSize: 15,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              const Text(
                'FreeData.AI',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 17,
                  fontWeight: FontWeight.w800,
                  letterSpacing: -0.2,
                ),
              ),
            ],
          ),
          const SizedBox(height: 28),
          const Text(
            'L’intelligence artificielle & décisionnelle multi-sectorielle.',
            style: TextStyle(
              color: Colors.white,
              fontSize: 20,
              fontWeight: FontWeight.w800,
              height: 1.28,
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            'Un espace unifié pour explorer vos données, analyser vos documents et piloter vos projets en toute confiance.',
            style: TextStyle(
              color: Color(0xFF94A3B8),
              fontSize: 13,
              height: 1.45,
            ),
          ),
          const SizedBox(height: 28),
          _brandFeature(
            Icons.auto_awesome_outlined,
            'Assistant IA & Analyse Documentaire',
            'Synthèse intelligente de vos documents privés et requêtes multi-domaines.',
          ),
          const SizedBox(height: 16),
          _brandFeature(
            Icons.insights_outlined,
            'Tableaux de Bord & Modèles Prédictifs',
            'Indicateurs sectoriels, scoring décisionnel et rapports professionnels.',
          ),
          const SizedBox(height: 16),
          _brandFeature(
            Icons.verified_user_outlined,
            'Isolation & Confidentialité RGPD',
            'Espaces de travail cloisonnés, chiffrement et maîtrise totale de vos données.',
          ),
          const Spacer(),
          const Text(
            'Plateforme sécurisée · Accès Standard & PRO',
            style: TextStyle(
              color: Color(0xFF64748B),
              fontSize: 11.5,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  Widget _brandFeature(IconData icon, String title, String subtitle) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 30,
          height: 30,
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Icon(icon, size: 17, color: const Color(0xFF38BDF8)),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: const TextStyle(
                  color: Color(0xFF94A3B8),
                  fontSize: 12,
                  height: 1.35,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildFormPanel({required bool showBrandHeader}) {
    final strength = _passwordStrength(_passCtrl.text);
    final strengthColor = strength <= 1
        ? AppColors.danger
        : (strength == 2 ? AppColors.warning : AppColors.green);
    final strengthLabel = strength <= 1
        ? 'Faible'
        : (strength == 2 ? 'Moyen' : 'Solide');

    return SingleChildScrollView(
      padding: const EdgeInsets.all(26),
      child: AutofillGroup(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                if (showBrandHeader) ...[
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
                        fontSize: 14,
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                ],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _registerMode
                            ? 'Créer votre compte'
                            : 'Connexion à votre espace',
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        _registerMode
                            ? 'Accédez à l’ensemble des outils et services en quelques secondes.'
                            : 'Retrouvez vos conversations, projets et analyses sauvegardés.',
                        style: const TextStyle(
                            fontSize: 12.5, color: AppColors.muted),
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
                  border:
                      Border.all(color: AppColors.blue.withValues(alpha: 0.2)),
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
                          height: 1.35,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 18),
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
            const SizedBox(height: 18),
            AnimatedSize(
              duration: const Duration(milliseconds: 180),
              curve: Curves.easeOut,
              child: _registerMode
                  ? Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: TextField(
                        controller: _nameCtrl,
                        autofillHints: const [AutofillHints.name],
                        textInputAction: TextInputAction.next,
                        decoration: const InputDecoration(
                          labelText: 'Nom ou organisation (optionnel)',
                          prefixIcon:
                              Icon(Icons.person_outline_rounded, size: 19),
                        ),
                      ),
                    )
                  : const SizedBox.shrink(),
            ),
            TextField(
              controller: _emailCtrl,
              keyboardType: TextInputType.emailAddress,
              autofillHints: const [AutofillHints.email],
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
              autofillHints: [
                _registerMode
                    ? AutofillHints.newPassword
                    : AutofillHints.password,
              ],
              onChanged: _registerMode ? (_) => setState(() {}) : null,
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
            if (_registerMode && _passCtrl.text.isNotEmpty) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(99),
                      child: LinearProgressIndicator(
                        value: strength / 3.0,
                        minHeight: 5,
                        backgroundColor: AppColors.canvasSoft,
                        color: strengthColor,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Text(
                    strengthLabel,
                    style: TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w700,
                      color: strengthColor,
                    ),
                  ),
                ],
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 12),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                decoration: BoxDecoration(
                  color: AppColors.dangerSoft,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: AppColors.dangerBorder),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.error_outline_rounded,
                        size: 17, color: AppColors.dangerDark),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _error!,
                        style: const TextStyle(
                          color: AppColors.dangerDark,
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
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
            const SizedBox(height: 12),
            const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.shield_outlined, size: 13, color: AppColors.subtle),
                SizedBox(width: 5),
                Flexible(
                  child: Text(
                    'Données isolées · Chiffrement JWT · Contrôle RGPD',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 11.5, color: AppColors.subtle),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _modeTab({
    required String label,
    required bool selected,
    required VoidCallback? onTap,
  }) {
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
                    offset: Offset(0, 1),
                  )
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
