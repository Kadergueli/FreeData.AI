import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';
import '../services/api_service.dart';

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

  @override
  void initState() {
    super.initState();
    _loadTickets();
  }

  Future<void> _loadTickets() async {
    try {
      final list = await widget.apiService.listMyTickets();
      if (!mounted) return;
      setState(() {
        _tickets = list;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _sendTicket() async {
    if (_subjCtrl.text.trim().length < 3 || _descCtrl.text.trim().length < 5) return;
    await widget.apiService.createSupportTicket(
      category: _category,
      subject: _subjCtrl.text.trim(),
      description: _descCtrl.text.trim(),
    );
    _subjCtrl.clear();
    _descCtrl.clear();
    await _loadTickets();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Ticket envoyé au support.')));
  }

  Future<void> _sendFeedback() async {
    await widget.apiService.submitFeedback(
      feature: _fbFeature,
      rating: _fbRating,
      comment: _fbCommentCtrl.text.trim(),
    );
    _fbCommentCtrl.clear();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Merci pour votre avis !')));
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
    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(title: const Text('Assistance & Avis', style: TextStyle(fontWeight: FontWeight.w700))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          FDCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Signaler un problème ou proposer une amélioration',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _category,
                  decoration: const InputDecoration(labelText: 'Catégorie'),
                  items: const [
                    DropdownMenuItem(value: 'technical_bug', child: Text('Problème technique')),
                    DropdownMenuItem(value: 'incorrect_ai', child: Text('Réponse IA incorrecte')),
                    DropdownMenuItem(value: 'pdf_issue', child: Text('Problème génération PDF')),
                    DropdownMenuItem(value: 'account_help', child: Text('Assistance compte / abonnement')),
                    DropdownMenuItem(value: 'feature_request', child: Text('Suggestion de fonctionnalité')),
                  ],
                  onChanged: (v) => setState(() => _category = v ?? 'technical_bug'),
                ),
                const SizedBox(height: 10),
                TextField(controller: _subjCtrl, decoration: const InputDecoration(labelText: 'Sujet')),
                const SizedBox(height: 10),
                TextField(controller: _descCtrl, maxLines: 3, decoration: const InputDecoration(labelText: 'Description')),
                const SizedBox(height: 12),
                FDPrimaryButton(
                  label: 'Envoyer la demande',
                  icon: Icons.send_rounded,
                  onPressed: _sendTicket,
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
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _fbFeature,
                  decoration: const InputDecoration(labelText: 'Fonctionnalité'),
                  items: const [
                    DropdownMenuItem(value: 'ai_response', child: Text('Qualité des réponses IA')),
                    DropdownMenuItem(value: 'rag_relevance', child: Text('Pertinence des sources RAG')),
                    DropdownMenuItem(value: 'ml_prediction', child: Text('Prévisions ML')),
                    DropdownMenuItem(value: 'pdf_quality', child: Text('Qualité des rapports PDF')),
                    DropdownMenuItem(value: 'usability', child: Text('Ergonomie générale')),
                  ],
                  onChanged: (v) => setState(() => _fbFeature = v ?? 'ai_response'),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Text('Note : ', style: TextStyle(fontWeight: FontWeight.w600, color: AppColors.ink)),
                    ...List.generate(5, (i) {
                      final star = i + 1;
                      return IconButton(
                        icon: Icon(
                          star <= _fbRating ? Icons.star_rounded : Icons.star_border_rounded,
                          color: AppColors.blue,
                        ),
                        onPressed: () => setState(() => _fbRating = star),
                      );
                    }),
                  ],
                ),
                TextField(controller: _fbCommentCtrl, decoration: const InputDecoration(labelText: 'Commentaire (optionnel)')),
                const SizedBox(height: 12),
                FDSecondaryButton(
                  label: 'Envoyer mon avis',
                  icon: Icons.thumb_up_alt_outlined,
                  onPressed: _sendFeedback,
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
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.ink),
                ),
                const SizedBox(height: 8),
                if (_loading)
                  const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator()))
                else if (_tickets.isEmpty)
                  const Text('Aucune demande envoyée.', style: TextStyle(color: AppColors.muted))
                else
                  ..._tickets.map(
                    (t) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(t['subject'].toString(), style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.ink)),
                                Text(
                                  '${t['category']} · Priorité : ${t['priority']}',
                                  style: const TextStyle(fontSize: 12.5, color: AppColors.muted),
                                ),
                              ],
                            ),
                          ),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: AppColors.blueSoft,
                              borderRadius: BorderRadius.circular(99),
                            ),
                            child: Text(
                              t['status'].toString(),
                              style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: AppColors.blue),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

