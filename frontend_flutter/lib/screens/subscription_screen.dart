import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/formatters.dart';
import '../services/api_service.dart';
import '../widgets/auth_dialog.dart';
import '../core/utils/error_text.dart';

class SubscriptionScreen extends StatefulWidget {
  final ApiService apiService;
  final Future<void> Function()? onConfigureKey;
  final VoidCallback? onSessionChanged;

  const SubscriptionScreen({
    super.key,
    required this.apiService,
    this.onConfigureKey,
    this.onSessionChanged,
  });

  @override
  State<SubscriptionScreen> createState() => _SubscriptionScreenState();
}

class _SubscriptionScreenState extends State<SubscriptionScreen> {
  Map<String, dynamic>? _me;
  List<Map<String, dynamic>> _plans = [];
  Map<String, dynamic>? _paymentMethods;
  List<Map<String, dynamic>> _myRequests = [];
  bool _loading = true;
  bool _refreshing = false;
  bool _submittingPayment = false;
  bool _redeemingKey = false;
  String? _error;
  String? _paymentMethodsError;
  String? _billingError;
  String? _requestsError;

  String _selectedProvider = 'airtel_money';
  final _phoneCtrl = TextEditingController();
  final _txCtrl = TextEditingController();
  final _amountCtrl = TextEditingController();
  final _noteCtrl = TextEditingController();
  final _activationKeyCtrl = TextEditingController();

  String _lastLoadedKey = '';

  @override
  void initState() {
    super.initState();
    _lastLoadedKey = widget.apiService.activePremiumKey;
    _hydrateFromCache();
    _load(silent: !_loading);
  }

  void _hydrateFromCache() {
    final cachedPlans = widget.apiService.cachedBillingPlans;
    final cachedMethods = widget.apiService.cachedPaymentMethods;
    final cachedMe = widget.apiService.cachedMyBilling;
    final cachedReqs = widget.apiService.cachedMyPaymentRequests;
    if (cachedPlans != null) {
      _plans = ((cachedPlans['plans'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
    }
    if (cachedMethods != null) {
      _paymentMethods = cachedMethods;
      final defaultPrice = cachedMethods['premium_price_xaf_month'];
      if (_amountCtrl.text.isEmpty && defaultPrice is num && defaultPrice > 0) {
        _amountCtrl.text = defaultPrice.toInt().toString();
      }
    }
    if (widget.apiService.isAuthenticated ||
        widget.apiService.hasExplicitPremiumKey) {
      if (cachedMe != null) _me = cachedMe;
      if (cachedReqs != null) _myRequests = cachedReqs;
    }
    if (_plans.isNotEmpty || _me != null || _paymentMethods != null) {
      _loading = false;
    }
  }

  @override
  void didUpdateWidget(covariant SubscriptionScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_lastLoadedKey != widget.apiService.activePremiumKey) {
      _lastLoadedKey = widget.apiService.activePremiumKey;
      _load(silent: !_loading);
    }
  }

  @override
  void dispose() {
    _phoneCtrl.dispose();
    _txCtrl.dispose();
    _amountCtrl.dispose();
    _noteCtrl.dispose();
    _activationKeyCtrl.dispose();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (silent) {
      if (mounted) {
        setState(() {
          _refreshing = true;
          _error = null;
        });
      }
    } else {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    String? paymentMethodsError;
    String? billingError;
    String? requestsError;
    try {
      final canReadPrivate = widget.apiService.isAuthenticated ||
          widget.apiService.hasExplicitPremiumKey;
      final plansFuture = widget.apiService.getBillingPlans();
      final methodsFuture = widget.apiService
          .getPaymentMethods()
          .then<Map<String, dynamic>?>((v) => v)
          .catchError((Object error) {
            paymentMethodsError = errText(error);
            return null;
          });
      final meFuture = canReadPrivate
          ? widget.apiService
              .getMyBilling()
              .then<Map<String, dynamic>?>((v) => v)
              .catchError((Object error) {
                billingError = errText(error);
                return null;
              })
          : Future<Map<String, dynamic>?>.value(null);
      final reqsFuture = canReadPrivate
          ? widget.apiService
              .listMyPaymentRequests()
              .catchError((Object error) {
                requestsError = errText(error);
                return const <Map<String, dynamic>>[];
              })
          : Future<List<Map<String, dynamic>>>.value(
              const <Map<String, dynamic>>[]);

      final results = await Future.wait<Object?>([
        plansFuture,
        methodsFuture,
        meFuture,
        reqsFuture,
      ]);
      final plansRes = results[0] as Map<String, dynamic>;
      final methods = results[1] as Map<String, dynamic>?;
      final me = results[2] as Map<String, dynamic>?;
      final reqs = results[3] as List<Map<String, dynamic>>;
      if (!mounted) return;
      final defaultPrice = methods?['premium_price_xaf_month'];
      if (_amountCtrl.text.isEmpty && defaultPrice is num && defaultPrice > 0) {
        _amountCtrl.text = defaultPrice.toInt().toString();
      }
      setState(() {
        _me = me;
        _plans =
            ((plansRes['plans'] as List?) ?? []).cast<Map<String, dynamic>>();
        _paymentMethods = methods;
        _myRequests = reqs;
        _paymentMethodsError = paymentMethodsError;
        _billingError = billingError;
        _requestsError = requestsError;
        _loading = false;
        _refreshing = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        if (_plans.isEmpty && _me == null) {
          _error = errText(e);
        }
        _loading = false;
        _refreshing = false;
      });
    }
  }

  Future<void> _openAuth({bool register = false}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AuthDialog(
        apiService: widget.apiService,
        initialRegisterMode: register,
      ),
    );
    if (ok == true && mounted) {
      widget.onSessionChanged?.call();
      await _load();
    }
  }

  Future<void> _redeemActivationKey() async {
    if (_redeemingKey) return;
    if (!widget.apiService.isAuthenticated) {
      await _openAuth(register: false);
      return;
    }
    final key = _activationKeyCtrl.text.trim();
    if (key.length < 8) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
              'Saisissez une clé d’activation valide (ex. FDPRO-XXXX-XXXX-XXXX).'),
        ),
      );
      return;
    }
    setState(() => _redeemingKey = true);
    try {
      final res = await widget.apiService.redeemProActivationKey(key);
      _activationKeyCtrl.clear();
      widget.onSessionChanged?.call();
      await _load();
      if (!mounted) return;
      final days = res['duration_days'] ?? 30;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content:
              Text('Abonnement PRO activé sur votre compte pour $days jours !'),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(errText(e))),
      );
    } finally {
      if (mounted) setState(() => _redeemingKey = false);
    }
  }

  Future<void> _submitPaymentRequest() async {
    if (_submittingPayment) return;
    if (!widget.apiService.isAuthenticated) {
      await _openAuth(register: false);
      return;
    }
    final phone = _phoneCtrl.text.trim();
    final tx = _txCtrl.text.trim();
    if (phone.length < 3 || tx.length < 3) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
              'Renseignez votre numéro/identifiant payeur et la référence de transaction (min. 3 car.).'),
        ),
      );
      return;
    }
    final amount =
        int.tryParse(_amountCtrl.text.replaceAll(RegExp(r'[^0-9]'), '')) ?? 0;
    setState(() => _submittingPayment = true);
    try {
      await widget.apiService.createPaymentRequest(
        provider: _selectedProvider,
        phoneOrRef: phone,
        transactionRef: tx,
        amountXaf: amount,
        note: _noteCtrl.text.trim(),
      );
      _phoneCtrl.clear();
      _txCtrl.clear();
      _noteCtrl.clear();
      await _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
              'Demande d’activation PRO envoyée. Validation sous 24 h ouvrées.'),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Envoi impossible : ${errText(e)}')),
      );
    } finally {
      if (mounted) setState(() => _submittingPayment = false);
    }
  }

  static String _quotaLabel(String key) {
    switch (key) {
      case 'daily_chat':
        return 'Messages IA / jour';
      case 'monthly_pdf':
        return 'Rapports PDF / mois';
      case 'daily_ml':
        return 'Prévisions ML / jour';
      case 'daily_rag':
        return 'Recherches documentaires / jour';
      default:
        return key;
    }
  }

  static String _planLabel(String planId) {
    switch (planId.toLowerCase()) {
      case 'premium':
      case 'pro':
        return 'FreeData PRO';
      case 'trial':
        return 'Essai PRO';
      default:
        return 'Standard (Gratuit)';
    }
  }

  static String _subStatusLabel(String status) {
    switch (status.toLowerCase()) {
      case 'active':
        return 'Actif';
      case 'trialing':
        return 'En essai';
      case 'expired':
        return 'Expiré';
      case 'cancelled':
      case 'canceled':
        return 'Annulé';
      default:
        return 'Actif';
    }
  }

  static String _providerLabel(String provider) {
    switch (provider) {
      case 'airtel_money':
        return 'Airtel Money';
      case 'moov_money':
        return 'Moov Money';
      case 'bank_transfer':
        return 'Virement / B2B';
      case 'stripe':
        return 'Carte bancaire (Stripe)';
      default:
        return provider;
    }
  }

  static String _statusLabel(String status) {
    switch (status) {
      case 'approved':
        return 'Approuvée';
      case 'rejected':
        return 'Refusée';
      default:
        return 'En attente';
    }
  }


  Widget _sectionLoadWarning(String message) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          color: const Color(0xFFFFF7ED),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: const Color(0xFFFED7AA)),
        ),
        child: Row(
          children: [
            const Icon(Icons.warning_amber_rounded,
                size: 18, color: AppColors.warning),
            const SizedBox(width: 8),
            Expanded(
              child: Text(message,
                  style: const TextStyle(
                      fontSize: 12.5, color: AppColors.ink)),
            ),
            IconButton(
              tooltip: 'Réessayer',
              visualDensity: VisualDensity.compact,
              icon: const Icon(Icons.refresh_rounded, size: 18),
              onPressed: () => _load(silent: true),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isAuthenticated = widget.apiService.isAuthenticated;
    final hasPartnerKey = widget.apiService.hasExplicitPremiumKey;
    final hasAccessContext = isAuthenticated || hasPartnerKey;
    final sub =
        _me?['subscription'] is Map ? _me!['subscription'] as Map : const {};
    final quotas = _me?['quotas'] is Map ? _me!['quotas'] as Map : const {};
    final effectivePlanId = sub['effective_plan_id']?.toString() ??
        (hasPartnerKey ? 'premium' : 'free');
    final isPro = effectivePlanId == 'premium' ||
        effectivePlanId == 'trial' ||
        widget.apiService.hasPremiumKey;
    final subStatus = _subStatusLabel(sub['status']?.toString() ?? 'active');

    final methods = ((_paymentMethods?['methods'] as List?) ?? const [])
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();
    Map<String, dynamic>? findMethod(String provider) {
      for (final m in methods) {
        if (m['provider'] == provider) return m;
      }
      return null;
    }

    final stripeMethod = findMethod('stripe');
    final selectedMeta = findMethod(_selectedProvider);
    final canPop = Navigator.of(context).canPop();

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: canPop
          ? AppBar(
              title: const Text('Abonnement & Quotas',
                  style: TextStyle(fontWeight: FontWeight.w700)))
          : null,
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 420),
                      child: FDCard(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.cloud_off_rounded,
                                size: 32, color: AppColors.danger),
                            const SizedBox(height: 10),
                            Text(
                              _error!.contains('TimeoutException')
                                  ? 'Le serveur met plus de temps que prévu à répondre (démarrage en cours).'
                                  : _error!,
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                  fontSize: 13.5, color: AppColors.ink),
                            ),
                            const SizedBox(height: 14),
                            FDPrimaryButton(
                              label: 'Réessayer',
                              icon: Icons.refresh_rounded,
                              onPressed: _load,
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                )
              : Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 760),
                    child: ListView(
                      padding: const EdgeInsets.all(16),
                      children: [
                        if (_refreshing)
                          const Padding(
                            padding: EdgeInsets.only(bottom: 10),
                            child: LinearProgressIndicator(minHeight: 2),
                          ),
                        if (_billingError != null)
                          _sectionLoadWarning(
                              'Impossible de charger votre abonnement et vos quotas : $_billingError'),
                        if (!hasAccessContext) ...[
                          FDCard(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text(
                                  'Passez à FreeData.AI PRO',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w800,
                                    color: AppColors.ink,
                                  ),
                                ),
                                const SizedBox(height: 6),
                                const Text(
                                  'Connectez-vous ou créez un compte gratuit pour suivre vos quotas en temps réel, activer l’offre PRO (Mobile Money, virement ou carte) et retrouver votre abonnement sur tous vos appareils.',
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
                                      onPressed: () =>
                                          _openAuth(register: false),
                                    ),
                                    FDSecondaryButton(
                                      label: 'Créer un compte',
                                      icon: Icons.person_add_alt_1_rounded,
                                      onPressed: () =>
                                          _openAuth(register: true),
                                    ),
                                    if (widget.onConfigureKey != null)
                                      FDSecondaryButton(
                                        label: 'J’ai une clé partenaire',
                                        icon: Icons.vpn_key_outlined,
                                        onPressed: () async {
                                          await widget.onConfigureKey!();
                                          if (mounted) {
                                            _lastLoadedKey = widget
                                                .apiService.activePremiumKey;
                                            await _load();
                                          }
                                        },
                                      ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ] else ...[
                          FDCard(
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Wrap(
                                        spacing: 8,
                                        runSpacing: 6,
                                        crossAxisAlignment:
                                            WrapCrossAlignment.center,
                                        children: [
                                          Text(
                                            _planLabel(effectivePlanId),
                                            style: const TextStyle(
                                              fontSize: 16,
                                              fontWeight: FontWeight.w800,
                                              color: AppColors.ink,
                                            ),
                                          ),
                                          FDBadge(
                                            label: subStatus.toUpperCase(),
                                            color: isPro
                                                ? AppColors.greenDark
                                                : AppColors.blue,
                                            backgroundColor: isPro
                                                ? AppColors.greenSoft
                                                : AppColors.blueSoft,
                                          ),
                                        ],
                                      ),
                                      const SizedBox(height: 6),
                                      Text(
                                        sub['current_period_end'] != null
                                            ? 'Échéance : ${sub['current_period_end']}'
                                            : (isPro
                                                ? 'Accès complet aux rapports PDF, études avancées et projets illimités.'
                                                : 'Activez PRO par Mobile Money (Tchad), virement bancaire, carte ou clé partenaire.'),
                                        style: const TextStyle(
                                          fontSize: 13,
                                          color: AppColors.muted,
                                          height: 1.4,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                if (widget.onConfigureKey != null) ...[
                                  const SizedBox(width: 12),
                                  FDSecondaryButton(
                                    label: 'Clé partenaire',
                                    icon: Icons.vpn_key_outlined,
                                    onPressed: () async {
                                      await widget.onConfigureKey!();
                                      if (mounted) {
                                        _lastLoadedKey =
                                            widget.apiService.activePremiumKey;
                                        await _load();
                                      }
                                    },
                                  ),
                                ],
                              ],
                            ),
                          ),
                          if (quotas.isNotEmpty) ...[
                            const SizedBox(height: 16),
                            const Text(
                              'Utilisation & quotas restants',
                              style: TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w700,
                                color: AppColors.ink,
                              ),
                            ),
                            const SizedBox(height: 8),
                            ...quotas.entries
                                .where((e) => e.value is Map)
                                .map((e) {
                              final q = e.value as Map;
                              final used = (q['used'] as num?)?.toInt() ?? 0;
                              final limit = (q['limit'] as num?)?.toInt() ?? 0;
                              final pct = limit > 0
                                  ? (used / limit).clamp(0.0, 1.0)
                                  : 0.0;
                              return Padding(
                                padding: const EdgeInsets.only(bottom: 10),
                                child: FDCard(
                                  padding: const EdgeInsets.all(14),
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Row(
                                        mainAxisAlignment:
                                            MainAxisAlignment.spaceBetween,
                                        children: [
                                          Text(
                                            _quotaLabel(e.key.toString()),
                                            style: const TextStyle(
                                              fontWeight: FontWeight.w600,
                                              color: AppColors.ink,
                                            ),
                                          ),
                                          Text(
                                            '$used / $limit',
                                            style: const TextStyle(
                                              fontWeight: FontWeight.w700,
                                              color: AppColors.blue,
                                            ),
                                          ),
                                        ],
                                      ),
                                      const SizedBox(height: 8),
                                      ClipRRect(
                                        borderRadius: BorderRadius.circular(99),
                                        child: LinearProgressIndicator(
                                          value: pct,
                                          minHeight: 7,
                                          backgroundColor: AppColors.canvasSoft,
                                          color: pct > 0.85
                                              ? AppColors.warning
                                              : AppColors.blue,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              );
                            }),
                          ],
                        ],
                        const SizedBox(height: 14),
                        const Text(
                          'Activer une clé PRO unique',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 8),
                        FDCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                'Si vous avez reçu une clé d’activation unique (ex. FDPRO-XXXX-XXXX-XXXX), liez-la définitivement à votre compte personnel.',
                                style: TextStyle(
                                  fontSize: 13,
                                  color: AppColors.muted,
                                  height: 1.4,
                                ),
                              ),
                              const SizedBox(height: 10),
                              if (!isAuthenticated)
                                FDSecondaryButton(
                                  label: 'Se connecter pour activer une clé',
                                  icon: Icons.login_rounded,
                                  onPressed: () => _openAuth(register: false),
                                )
                              else ...[
                                TextField(
                                  controller: _activationKeyCtrl,
                                  textCapitalization:
                                      TextCapitalization.characters,
                                  decoration: const InputDecoration(
                                    labelText: 'Clé d’activation PRO',
                                    hintText: 'FDPRO-XXXX-XXXX-XXXX',
                                  ),
                                ),
                                const SizedBox(height: 10),
                                FDPrimaryButton(
                                  label: _redeemingKey
                                      ? 'Activation…'
                                      : 'Activer la clé PRO',
                                  icon: Icons.verified_outlined,
                                  onPressed: _redeemingKey
                                      ? null
                                      : _redeemActivationKey,
                                ),
                              ],
                            ],
                          ),
                        ),
                        const SizedBox(height: 14),
                        const Text(
                          'Comprendre nos Offres',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 8),
                        FDCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: const [
                              Text(
                                '• Standard (Gratuit) — Explorer & Simuler',
                                style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 13.5,
                                    color: AppColors.ink),
                              ),
                              SizedBox(height: 2),
                              Text(
                                'Interrogez l’IA sur 8 secteurs, consultez les prévisions de prix et simulez vos campagnes (Plan Campagne & Exploitation).',
                                style: TextStyle(
                                    fontSize: 12.5, color: AppColors.muted),
                              ),
                              SizedBox(height: 10),
                              Text(
                                '• Essai PRO — Valider sur vos premiers dossiers',
                                style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 13.5,
                                    color: AppColors.blue),
                              ),
                              SizedBox(height: 2),
                              Text(
                                'Testez la génération de vos 5 premiers rapports PDF et augmentez vos quotas d’analyse et de projets.',
                                style: TextStyle(
                                    fontSize: 12.5, color: AppColors.muted),
                              ),
                              SizedBox(height: 10),
                              Text(
                                '• FreeData PRO — Production, Certification & Alertes',
                                style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 13.5,
                                    color: AppColors.greenDark),
                              ),
                              SizedBox(height: 2),
                              Text(
                                'Exportez jusqu’à 50 bulletins PDF certifiés/mois (QR code), recevez les alertes Watchlist, auditez des parcelles (Agronome PRO) et débloquez l’analytique avancée.',
                                style: TextStyle(
                                    fontSize: 12.5, color: AppColors.muted),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          isPro
                              ? 'Renouveler ou prolonger votre abonnement PRO'
                              : 'Activer PRO — Mobile Money (Tchad) / Virement / Carte',
                          style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 8),
                        FDCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (_paymentMethodsError != null)
                                _sectionLoadWarning(
                                    'Les moyens de paiement sont indisponibles : $_paymentMethodsError'),
                              if (_paymentMethods?['premium_price_xaf_month']
                                  is num) ...[
                                Text(
                                  'Tarif mensuel PRO : ${formatXaf(_paymentMethods!['premium_price_xaf_month'] as num)} XAF / mois',
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: AppColors.blue,
                                  ),
                                ),
                                const SizedBox(height: 10),
                              ],
                              if (!isAuthenticated) ...[
                                const Text(
                                  'Connectez-vous à votre compte FreeData.AI pour soumettre votre preuve de paiement (Airtel Money, Moov Money ou virement) et activer votre abonnement en toute sécurité.',
                                  style: TextStyle(
                                    fontSize: 13,
                                    color: AppColors.muted,
                                    height: 1.45,
                                  ),
                                ),
                                const SizedBox(height: 12),
                                FDPrimaryButton(
                                  label: 'Se connecter pour activer PRO',
                                  icon: Icons.login_rounded,
                                  onPressed: () => _openAuth(register: false),
                                ),
                              ] else ...[
                                DropdownButtonFormField<String>(
                                  key: ValueKey(_selectedProvider),
                                  initialValue: _selectedProvider,
                                  isExpanded: true,
                                  decoration: const InputDecoration(
                                    labelText: 'Moyen de paiement',
                                  ),
                                  items: const [
                                    DropdownMenuItem(
                                      value: 'airtel_money',
                                      child: Text('Airtel Money (Tchad)'),
                                    ),
                                    DropdownMenuItem(
                                      value: 'moov_money',
                                      child: Text('Moov Money (Tchad)'),
                                    ),
                                    DropdownMenuItem(
                                      value: 'bank_transfer',
                                      child: Text(
                                          'Virement bancaire / Facture B2B'),
                                    ),
                                  ],
                                  onChanged: (v) => setState(() =>
                                      _selectedProvider = v ?? 'airtel_money'),
                                ),
                                if (selectedMeta?['instructions'] != null) ...[
                                  const SizedBox(height: 8),
                                  Text(
                                    selectedMeta!['instructions'].toString(),
                                    style: const TextStyle(
                                      fontSize: 12.5,
                                      color: AppColors.muted,
                                    ),
                                  ),
                                ],
                                const SizedBox(height: 10),
                                TextField(
                                  controller: _phoneCtrl,
                                  decoration: const InputDecoration(
                                    labelText:
                                        'Numéro payeur ou référence compte',
                                  ),
                                ),
                                const SizedBox(height: 10),
                                TextField(
                                  controller: _txCtrl,
                                  decoration: const InputDecoration(
                                    labelText:
                                        'Référence de transaction (SMS / reçu)',
                                  ),
                                ),
                                const SizedBox(height: 10),
                                TextField(
                                  controller: _amountCtrl,
                                  keyboardType: TextInputType.number,
                                  decoration: const InputDecoration(
                                    labelText: 'Montant envoyé (XAF)',
                                  ),
                                ),
                                const SizedBox(height: 10),
                                TextField(
                                  controller: _noteCtrl,
                                  decoration: const InputDecoration(
                                    labelText:
                                        'Note / Organisation (optionnel)',
                                  ),
                                ),
                                const SizedBox(height: 12),
                                Wrap(
                                  spacing: 10,
                                  runSpacing: 8,
                                  children: [
                                    FDPrimaryButton(
                                      label: _submittingPayment
                                          ? 'Envoi en cours…'
                                          : 'Soumettre la preuve de paiement',
                                      icon: Icons.payments_outlined,
                                      onPressed: _submittingPayment
                                          ? null
                                          : _submitPaymentRequest,
                                    ),
                                    if (stripeMethod?['checkout_url'] != null)
                                      FDSecondaryButton(
                                        label: 'Copier le lien carte (Stripe)',
                                        icon: Icons.credit_card_rounded,
                                        onPressed: () {
                                          Clipboard.setData(
                                            ClipboardData(
                                              text:
                                                  stripeMethod!['checkout_url']
                                                      .toString(),
                                            ),
                                          );
                                          ScaffoldMessenger.of(context)
                                              .showSnackBar(
                                            const SnackBar(
                                              content: Text(
                                                  'Lien de paiement carte copié.'),
                                            ),
                                          );
                                        },
                                      ),
                                  ],
                                ),
                              ],
                            ],
                          ),
                        ),
                        if (_requestsError != null || _myRequests.isNotEmpty) ...[
                          const SizedBox(height: 16),
                          const Text(
                            'Mes demandes d’activation',
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink,
                            ),
                          ),
                          const SizedBox(height: 8),
                          if (_requestsError != null)
                            _sectionLoadWarning(
                                'Impossible de charger vos demandes : $_requestsError'),
                          ..._myRequests.map((r) {
                            final st = r['status']?.toString() ?? 'pending';
                            final color = st == 'approved'
                                ? AppColors.greenDark
                                : (st == 'rejected'
                                    ? AppColors.danger
                                    : AppColors.warning);
                            return Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: FDCard(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 14,
                                  vertical: 10,
                                ),
                                child: ListTile(
                                  dense: true,
                                  contentPadding: EdgeInsets.zero,
                                  title: Text(
                                    '${_providerLabel(r['provider']?.toString() ?? '')} · Réf. ${r['transaction_ref']}',
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w600,
                                      color: AppColors.ink,
                                    ),
                                  ),
                                  subtitle: Text(
                                    '${formatXaf((r['amount_xaf'] as num?) ?? 0)} XAF · ${r['created_at'] ?? ''}',
                                    style: const TextStyle(
                                      fontSize: 12,
                                      color: AppColors.muted,
                                    ),
                                  ),
                                  trailing: Text(
                                    _statusLabel(st),
                                    style: TextStyle(
                                      fontWeight: FontWeight.w700,
                                      color: color,
                                    ),
                                  ),
                                ),
                              ),
                            );
                          }),
                        ],
                        const SizedBox(height: 16),
                        const Text(
                          'Comparatif des offres',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 8),
                        ..._plans.map((p) {
                          final pid = p['plan_id']?.toString() ?? '';
                          final isCurrent =
                              hasAccessContext && pid == effectivePlanId;
                          final price = p['price_xaf_month'];
                          final priceText = (price is num && price > 0)
                              ? '${formatXaf(price)} XAF / mois'
                              : 'Gratuit';
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 10),
                            child: FDCard(
                              padding: const EdgeInsets.all(14),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      Expanded(
                                        child: Text(
                                          '${p['label'] ?? _planLabel(pid)} — $priceText',
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w700,
                                            color: AppColors.ink,
                                          ),
                                        ),
                                      ),
                                      if (isCurrent)
                                        const FDBadge(
                                          label: 'OFFRE ACTUELLE',
                                          color: AppColors.greenDark,
                                          backgroundColor: AppColors.greenSoft,
                                        ),
                                    ],
                                  ),
                                  const SizedBox(height: 6),
                                  Text(
                                    'Messages IA/jour : ${p['daily_chat_limit']} · Rapports PDF/mois : ${p['monthly_pdf_limit']} · Prévisions ML/jour : ${p['daily_ml_limit']} · Projets max : ${p['max_projects']}',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      color: AppColors.muted,
                                      height: 1.4,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          );
                        }),
                      ],
                    ),
                  ),
                ),
    );
  }
}
