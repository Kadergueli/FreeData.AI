import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
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
      appBar: AppBar(title: const Text('Assistance & Avis')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Signaler un problème ou proposer une amélioration', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            value: _category,
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
          const SizedBox(height: 8),
          TextField(controller: _subjCtrl, decoration: const InputDecoration(labelText: 'Sujet')),
          const SizedBox(height: 8),
          TextField(controller: _descCtrl, maxLines: 3, decoration: const InputDecoration(labelText: 'Description')),
          const SizedBox(height: 10),
          ElevatedButton(onPressed: _sendTicket, child: const Text('Envoyer la demande')),
          const Divider(height: 32),
          const Text('Évaluer une fonctionnalité', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            value: _fbFeature,
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
              const Text('Note : '),
              ...List.generate(5, (i) {
                final star = i + 1;
                return IconButton(
                  icon: Icon(star <= _fbRating ? Icons.star_rounded : Icons.star_border_rounded, color: FDTheme.blue),
                  onPressed: () => setState(() => _fbRating = star),
                );
              }),
            ],
          ),
          TextField(controller: _fbCommentCtrl, decoration: const InputDecoration(labelText: 'Commentaire (optionnel)')),
          const SizedBox(height: 10),
          OutlinedButton(onPressed: _sendFeedback, child: const Text('Envoyer mon avis')),
          const Divider(height: 32),
          const Text('Mes demandes récentes', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
          if (_loading)
            const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator()))
          else if (_tickets.isEmpty)
            const Padding(padding: EdgeInsets.only(top: 8), child: Text('Aucune demande envoyée.'))
          else
            ..._tickets.map((t) => ListTile(
                  dense: true,
                  title: Text(t['subject'].toString()),
                  subtitle: Text('${t['category']} · Statut : ${t['status']} · Priorité : ${t['priority']}'),
                )),
        ],
      ),
    );
  }
}

