import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';
import '../widgets/auth_dialog.dart';
import '../core/utils/error_text.dart';

class SupportScreen extends StatefulWidget {
  final ApiService apiService;

  const SupportScreen({super.key, required this.apiService});

  @override
  State<SupportScreen> createState() => _SupportScreenState();
}

class _SupportScreenState extends State<SupportScreen> {
  String _category = 'technical_bug';
  final _subjCtrl = TextEditingController();
  final _descCtrl = TextEditingController();
  String _fbFeature = 'ai_response';
  int _fbRating = 5;
  final _fbCommentCtrl = TextEditingController();
  List<Map<String, dynamic>> _tickets = [];
  bool _loading = true;
  bool _submittingTicket = false;
  bool _submittingFeedback = false;
  String? _loadError;

  bool get _canAccess =>
      widget.apiService.isAuthenticated ||
      widget.apiService.hasExplicitPremiumKey;

  @override
  void initState() {
    super.initState();
    _loadTickets();
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
      await _loadTickets();
    }
  }

  Future<void> _loadTickets() async {
    if (!_canAccess) {
      if (!mounted) return;
      setState(() {
        _tickets = [];
        _loadError = null;
        _loading = false;
      });
      return;
    }
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final list = await widget.apiService.listMyTickets();
      if (!mounted) return;
      setState(() {
        _tickets = list;
        _loadError = null;
        _loading = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _loadError = 'Impossible de charger vos demandes (${errText(e)}).';
          _loading = false;
        });
      }
    }
  }

  Future<void> _sendTicket() async {
    if (_submittingTicket) return;
    if (!_canAccess) {
      await _openAuth(register: false);
      return;
    }
    final subj = _subjCtrl.text.trim();
    final desc = _descCtrl.text.trim();
    if (subj.length < 3 || desc.length < 5) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Veuillez saisir un sujet (min. 3 car.) et une description (min. 5 car.).',
          ),
        ),
      );
      return;
    }
    setState(() => _submittingTicket = true);
    try {
      await widget.apiService.createSupportTicket(
        category: _category,
        subject: subj,
        description: desc,
      );
      _subjCtrl.clear();
      _descCtrl.clear();
      await _loadTickets();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Votre demande a bien été envoyée.')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Envoi impossible : ${errText(e)}')),
      );
    } finally {
      if (mounted) setState(() => _submittingTicket = false);
    }
  }

  Future<void> _sendFeedback() async {
    if (_submittingFeedback) return;
    if (!_canAccess) {
      await _openAuth(register: false);
      return;
    }
    setState(() => _submittingFeedback = true);
    try {
      await widget.apiService.submitFeedback(
        feature: _fbFeature,
        rating: _fbRating,
        comment: _fbCommentCtrl.text.trim(),
      );
      _fbCommentCtrl.clear();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Merci pour votre avis !')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Envoi impossible : ${errText(e)}')),
      );
    } finally {
      if (mounted) setState(() => _submittingFeedback = false);
    }
  }

  static String _categoryLabel(String category) {
    switch (category) {
      case 'technical_bug':
        return 'Problème technique';
      case 'incorrect_ai':
        return 'Réponse IA incorrecte';
      case 'pdf_issue':
        return 'Problème génération PDF';
      case 'account_help':
        return 'Assistance compte / abonnement';
      case 'feature_request':
        return 'Suggestion de fonctionnalité';
      default:
        return category;
    }
  }

  static String _priorityLabel(String priority) {
    switch (priority.toLowerCase()) {
      case 'urgent':
      case 'critical':
        return 'Urgente';
      case 'high':
        return 'Haute';
      case 'low':
        return 'Faible';
      default:
        return 'Normale';
    }
  }

  static String _statusLabel(String status) {
    switch (status.toLowerCase()) {
      case 'open':
      case 'new':
        return 'Ouverte';
      case 'in_progress':
      case 'pending':
        return 'En cours';
      case 'resolved':
        return 'Résolue';
      case 'closed':
        return 'Fermée';
      default:
        return status;
    }
  }

  static Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'resolved':
      case 'closed':
        return AppColors.greenDark;
      case 'in_progress':
      case 'pending':
        return AppColors.warning;
      default:
        return AppColors.blue;
    }
  }

  static Color _statusBg(String status) {
    switch (status.toLowerCase()) {
      case 'resolved':
      case 'closed':
        return AppColors.greenSoft;
      case 'in_progress':
      case 'pending':
        return const Color(0xFFFEF3C7);
      default:
        return AppColors.blueSoft;
    }
  }

  @override
  void dispose() {
    _subjCtrl.dispose();
    _descCtrl.dispose();
    _fbCommentCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final authenticated = _canAccess;

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
        title: const Text(
          'Assistance & Avis',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (!authenticated) ...[
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Besoin d’aide ou envie de partager un avis ?',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Connectez-vous à votre compte FreeData.AI pour contacter le support technique, suivre le traitement de vos demandes et évaluer nos fonctionnalités.',
                        style: TextStyle(
                          fontSize: 13.5,
                          color: AppColors.muted,
                          height: 1.45,
                        ),
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
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Signaler un problème ou proposer une amélioration',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        initialValue: _category,
                        isExpanded: true,
                        decoration:
                            const InputDecoration(labelText: 'Catégorie'),
                        items: const [
                          DropdownMenuItem(
                            value: 'technical_bug',
                            child: Text('Problème technique'),
                          ),
                          DropdownMenuItem(
                            value: 'incorrect_ai',
                            child: Text('Réponse IA incorrecte'),
                          ),
                          DropdownMenuItem(
                            value: 'pdf_issue',
                            child: Text('Problème génération PDF'),
                          ),
                          DropdownMenuItem(
                            value: 'account_help',
                            child: Text('Assistance compte / abonnement'),
                          ),
                          DropdownMenuItem(
                            value: 'feature_request',
                            child: Text('Suggestion de fonctionnalité'),
                          ),
                        ],
                        onChanged: (v) =>
                            setState(() => _category = v ?? 'technical_bug'),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _subjCtrl,
                        decoration: const InputDecoration(labelText: 'Sujet'),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _descCtrl,
                        maxLines: 3,
                        decoration:
                            const InputDecoration(labelText: 'Description'),
                      ),
                      const SizedBox(height: 12),
                      FDPrimaryButton(
                        label: _submittingTicket
                            ? 'Envoi en cours…'
                            : 'Envoyer la demande',
                        icon: Icons.send_rounded,
                        onPressed: _submittingTicket ? null : _sendTicket,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Évaluer une fonctionnalité',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        initialValue: _fbFeature,
                        isExpanded: true,
                        decoration:
                            const InputDecoration(labelText: 'Fonctionnalité'),
                        items: const [
                          DropdownMenuItem(
                            value: 'ai_response',
                            child: Text('Qualité des réponses IA'),
                          ),
                          DropdownMenuItem(
                            value: 'rag_relevance',
                            child: Text('Pertinence des sources documentaires'),
                          ),
                          DropdownMenuItem(
                            value: 'ml_prediction',
                            child: Text('Prévisions des prix'),
                          ),
                          DropdownMenuItem(
                            value: 'pdf_quality',
                            child: Text('Qualité des rapports PDF'),
                          ),
                          DropdownMenuItem(
                            value: 'usability',
                            child: Text('Ergonomie générale'),
                          ),
                        ],
                        onChanged: (v) =>
                            setState(() => _fbFeature = v ?? 'ai_response'),
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          const Text(
                            'Note : ',
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              color: AppColors.ink,
                            ),
                          ),
                          ...List.generate(5, (i) {
                            final star = i + 1;
                            return IconButton(
                              icon: Icon(
                                star <= _fbRating
                                    ? Icons.star_rounded
                                    : Icons.star_border_rounded,
                                color: AppColors.blue,
                              ),
                              onPressed: () => setState(() => _fbRating = star),
                            );
                          }),
                        ],
                      ),
                      TextField(
                        controller: _fbCommentCtrl,
                        decoration: const InputDecoration(
                          labelText: 'Commentaire (optionnel)',
                        ),
                      ),
                      const SizedBox(height: 12),
                      FDSecondaryButton(
                        label: _submittingFeedback
                            ? 'Envoi en cours…'
                            : 'Envoyer mon avis',
                        icon: Icons.thumb_up_alt_outlined,
                        onPressed: _submittingFeedback ? null : _sendFeedback,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                FDCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Mes demandes récentes',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 10),
                      if (_loading)
                        const Padding(
                          padding: EdgeInsets.all(12),
                          child: Center(child: CircularProgressIndicator()),
                        )
                      else if (_loadError != null)
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              _loadError!,
                              style: const TextStyle(color: AppColors.danger),
                            ),
                            const SizedBox(height: 8),
                            FDSecondaryButton(
                              label: 'Réessayer',
                              icon: Icons.refresh_rounded,
                              onPressed: _loadTickets,
                            ),
                          ],
                        )
                      else if (_tickets.isEmpty)
                        const Text(
                          'Aucune demande envoyée pour le moment.',
                          style: TextStyle(color: AppColors.muted),
                        )
                      else
                        ..._tickets.map((t) {
                          final rawStatus = t['status']?.toString() ?? 'open';
                          final rawCategory = t['category']?.toString() ?? '';
                          final rawPriority =
                              t['priority']?.toString() ?? 'normal';
                          return Padding(
                            padding: const EdgeInsets.symmetric(vertical: 6),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        t['subject']?.toString() ?? 'Demande',
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w600,
                                          color: AppColors.ink,
                                        ),
                                      ),
                                      const SizedBox(height: 2),
                                      Text(
                                        '${_categoryLabel(rawCategory)} · Priorité : ${_priorityLabel(rawPriority)}',
                                        style: const TextStyle(
                                          fontSize: 12.5,
                                          color: AppColors.muted,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 8),
                                FDBadge(
                                  label: _statusLabel(rawStatus),
                                  color: _statusColor(rawStatus),
                                  backgroundColor: _statusBg(rawStatus),
                                ),
                              ],
                            ),
                          );
                        }),
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
