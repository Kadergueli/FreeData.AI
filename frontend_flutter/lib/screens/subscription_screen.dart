import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/formatters.dart';
import '../services/api_service.dart';
import '../widgets/auth_dialog.dart';

class SubscriptionScreen extends StatefulWidget {
  final ApiService apiService;
  final Future<void> Function()? onConfigureKey;

  const SubscriptionScreen(
      {super.key, required this.apiService, this.onConfigureKey});

  @override
  State<SubscriptionScreen> createState() => _SubscriptionScreenState();
}

class _SubscriptionScreenState extends State<SubscriptionScreen> {
  Map<String, dynamic>? _me;
  List<Map<String, dynamic>> _plans = [];
  Map<String, dynamic>? _paymentMethods;
  List<Map<String, dynamic>> _myRequests = [];
  bool _loading = true;
  bool _submittingPayment = false;
  String? _error;

  String _selectedProvider = 'airtel_money';
  final _phoneCtrl = TextEditingController();
  final _txCtrl = TextEditingController();
  final _amountCtrl = TextEditingController();
  final _noteCtrl = TextEditingController();

  String _lastLoadedKey = '';

  @override
  void initState() {
    super.initState();
    _lastLoadedKey = widget.apiService.activePremiumKey;
    _load();
  }

  @override
  void didUpdateWidget(covariant SubscriptionScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_lastLoadedKey != widget.apiService.activePremiumKey) {
      _lastLoadedKey = widget.apiService.activePremiumKey;
      _load();
    }
  }

  @override
  void dispose() {
    _phoneCtrl.dispose();
    _txCtrl.dispose();
    _amountCtrl.dispose();
    _noteCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final res = await Future.wait([
        widget.apiService.getMyBilling(),
        widget.apiService.getBillingPlans(),
      ]);
      Map<String, dynamic>? methods;
      List<Map<String, dynamic>> reqs = const [];
      try {
        methods = await widget.apiService.getPaymentMethods();
      } catch (_) {}
      try {
        reqs = await widget.apiService.listMyPaymentRequests();
      } catch (_) {}
      if (!mounted) return;
      final defaultPrice = methods?['premium_price_xaf_month'];
      if (_amountCtrl.text.isEmpty && defaultPrice is num && defaultPrice > 0) {
        _amountCtrl.text = defaultPrice.toInt().toString();
      }
      setState(() {
        _me = res[0];
        _plans =
            ((res[1]['plans'] as List?) ?? []).cast<Map<String, dynamic>>();
        _paymentMethods = methods;
        _myRequests = reqs;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _submitPaymentRequest() async {
    if (_submittingPayment) return;
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
              'Demande d’activation PRO envoyée. Validation administrateur sous 24 h ouvrées.'),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Envoi impossible : $e')),
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
        return 'Recherches RAG / jour';
      default:
        return key;
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
        return 'Stripe (Carte)';
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

  @override
  Widget build(BuildContext context) {
    final sub =
        _me?['subscription'] is Map ? _me!['subscription'] as Map : const {};
    final quotas = _me?['quotas'] is Map ? _me!['quotas'] as Map : const {};
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
                  child: FDCard(
                    child: Text(_error!,
                        style: const TextStyle(color: AppColors.danger)),
                  ),
                )
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    FDCard(
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Plan actif : ${sub['effective_plan_id'] ?? 'free'} (${sub['status'] ?? 'active'})',
                                  style: const TextStyle(
                                      fontSize: 15,
                                      fontWeight: FontWeight.w700,
                                      color: AppColors.ink),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  sub['current_period_end'] != null
                                      ? 'Échéance : ${sub['current_period_end']}'
                                      : 'Activation par Mobile Money, carte Stripe ou clé partenaire PRO.',
                                  style: const TextStyle(
                                      fontSize: 13, color: AppColors.muted),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 12),
                          FDPrimaryButton(
                            label: 'Clé PRO',
                            icon: Icons.vpn_key_outlined,
                            onPressed: widget.onConfigureKey == null
                                ? null
                                : () async {
                                    await widget.onConfigureKey!();
                                    if (mounted) {
                                      _lastLoadedKey =
                                          widget.apiService.activePremiumKey;
                                      await _load();
                                    }
                                  },
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    const Text(
                      'Utilisation & Quotas restants',
                      style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink),
                    ),
                    const SizedBox(height: 8),
                    ...quotas.entries.where((e) => e.value is Map).map((e) {
                      final q = e.value as Map;
                      final used = (q['used'] as num?)?.toInt() ?? 0;
                      final limit = (q['limit'] as num?)?.toInt() ?? 0;
                      final pct =
                          limit > 0 ? (used / limit).clamp(0.0, 1.0) : 0.0;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: FDCard(
                          padding: const EdgeInsets.all(14),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                mainAxisAlignment:
                                    MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(
                                    _quotaLabel(e.key.toString()),
                                    style: const TextStyle(
                                        fontWeight: FontWeight.w600,
                                        color: AppColors.ink),
                                  ),
                                  Text('$used / $limit',
                                      style: const TextStyle(
                                          fontWeight: FontWeight.w700,
                                          color: AppColors.blue)),
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
                    const SizedBox(height: 10),
                    const Text(
                      'Activer PRO — Mobile Money (Tchad) / Virement / Carte',
                      style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink),
                    ),
                    const SizedBox(height: 8),
                    FDCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          if (!widget.apiService.isAuthenticated) ...[
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 12, vertical: 10),
                              decoration: BoxDecoration(
                                color: AppColors.blueSoft,
                                borderRadius: BorderRadius.circular(10),
                                border: Border.all(
                                    color:
                                        AppColors.blue.withValues(alpha: 0.2)),
                              ),
                              child: Row(
                                children: [
                                  const Expanded(
                                    child: Text(
                                      'Connectez-vous pour lier votre abonnement PRO à votre compte sur tous vos appareils.',
                                      style: TextStyle(
                                          fontSize: 12.5,
                                          color: AppColors.blueDark),
                                    ),
                                  ),
                                  TextButton(
                                    onPressed: () async {
                                      final ok = await showDialog<bool>(
                                        context: context,
                                        builder: (_) => AuthDialog(
                                            apiService: widget.apiService),
                                      );
                                      if (ok == true && mounted) {
                                        await _load();
                                      }
                                    },
                                    child: const Text('Se connecter'),
                                  ),
                                ],
                              ),
                            ),
                            const SizedBox(height: 12),
                          ],
                          if (_paymentMethods?['premium_price_xaf_month']
                              is num) ...[
                            Text(
                              'Tarif mensuel PRO : ${formatXaf(_paymentMethods!['premium_price_xaf_month'] as num)} XAF / mois',
                              style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.blue),
                            ),
                            const SizedBox(height: 10),
                          ],
                          DropdownButtonFormField<String>(
                            key: ValueKey(_selectedProvider),
                            initialValue: _selectedProvider,
                            isExpanded: true,
                            decoration: const InputDecoration(
                                labelText: 'Moyen de paiement'),
                            items: const [
                              DropdownMenuItem(
                                  value: 'airtel_money',
                                  child: Text('Airtel Money (Tchad)')),
                              DropdownMenuItem(
                                  value: 'moov_money',
                                  child: Text('Moov Money (Tchad)')),
                              DropdownMenuItem(
                                  value: 'bank_transfer',
                                  child:
                                      Text('Virement bancaire / Facture B2B')),
                            ],
                            onChanged: (v) => setState(
                                () => _selectedProvider = v ?? 'airtel_money'),
                          ),
                          if (selectedMeta?['instructions'] != null) ...[
                            const SizedBox(height: 8),
                            Text(
                              selectedMeta!['instructions'].toString(),
                              style: const TextStyle(
                                  fontSize: 12.5, color: AppColors.muted),
                            ),
                          ],
                          const SizedBox(height: 10),
                          TextField(
                            controller: _phoneCtrl,
                            decoration: const InputDecoration(
                                labelText: 'Numéro payeur ou référence compte'),
                          ),
                          const SizedBox(height: 10),
                          TextField(
                            controller: _txCtrl,
                            decoration: const InputDecoration(
                                labelText:
                                    'Référence de transaction (SMS / reçu)'),
                          ),
                          const SizedBox(height: 10),
                          TextField(
                            controller: _amountCtrl,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(
                                labelText: 'Montant envoyé (XAF)'),
                          ),
                          const SizedBox(height: 10),
                          TextField(
                            controller: _noteCtrl,
                            decoration: const InputDecoration(
                                labelText: 'Note / Organisation (optionnel)'),
                          ),
                          const SizedBox(height: 12),
                          Wrap(
                            spacing: 10,
                            runSpacing: 8,
                            children: [
                              FDPrimaryButton(
                                label: _submittingPayment
                                    ? 'Envoi…'
                                    : 'Soumettre la preuve de paiement',
                                icon: Icons.payments_outlined,
                                onPressed: _submittingPayment
                                    ? null
                                    : _submitPaymentRequest,
                              ),
                              if (stripeMethod?['checkout_url'] != null)
                                FDSecondaryButton(
                                  label: 'Copier lien Stripe',
                                  icon: Icons.credit_card_rounded,
                                  onPressed: () {
                                    Clipboard.setData(
                                      ClipboardData(
                                          text: stripeMethod!['checkout_url']
                                              .toString()),
                                    );
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      const SnackBar(
                                          content: Text(
                                              'Lien de paiement Stripe copié.')),
                                    );
                                  },
                                ),
                            ],
                          ),
                        ],
                      ),
                    ),
                    if (_myRequests.isNotEmpty) ...[
                      const SizedBox(height: 14),
                      const Text(
                        'Mes demandes d’activation',
                        style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink),
                      ),
                      const SizedBox(height: 8),
                      ..._myRequests.map((r) {
                        final st = r['status']?.toString() ?? 'pending';
                        final color = st == 'approved'
                            ? AppColors.green
                            : (st == 'rejected'
                                ? AppColors.danger
                                : AppColors.warning);
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: FDCard(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 14, vertical: 10),
                            child: ListTile(
                              dense: true,
                              contentPadding: EdgeInsets.zero,
                              title: Text(
                                '${_providerLabel(r['provider']?.toString() ?? '')} · Réf. ${r['transaction_ref']}',
                                style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                    color: AppColors.ink),
                              ),
                              subtitle: Text(
                                '${r['amount_xaf'] ?? 0} XAF · ${r['created_at'] ?? ''}',
                                style: const TextStyle(
                                    fontSize: 12, color: AppColors.muted),
                              ),
                              trailing: Text(
                                _statusLabel(st),
                                style: TextStyle(
                                    fontWeight: FontWeight.w700, color: color),
                              ),
                            ),
                          ),
                        );
                      }),
                    ],
                    const SizedBox(height: 10),
                    const Text(
                      'Plans disponibles (quotas appliqués côté serveur)',
                      style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink),
                    ),
                    const SizedBox(height: 8),
                    ..._plans.map(
                      (p) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: FDCard(
                          padding: const EdgeInsets.all(14),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${p['label']} (${p['plan_id']})'
                                '${p['price_xaf_month'] is num ? ' — ${formatXaf(p['price_xaf_month'] as num)} XAF/mois' : ''}',
                                style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: AppColors.ink),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                'Chat/jour : ${p['daily_chat_limit']} · PDF/mois : ${p['monthly_pdf_limit']} · ML/jour : ${p['daily_ml_limit']} · Projets max : ${p['max_projects']}',
                                style: const TextStyle(
                                    fontSize: 13, color: AppColors.muted),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
    );
  }
}
