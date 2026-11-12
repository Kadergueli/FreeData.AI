import 'package:flutter/material.dart';
import '../services/api_service.dart';

class ChatScreen extends StatefulWidget {
  final ApiService apiService;
  const ChatScreen({super.key, required this.apiService});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final List<Map<String, String>> _messages = [
    {
      'role': 'assistant',
      'text': 'Bonjour ! Je suis FreeData.AI, connecté aux séries WFP et FEWS NET du Tchad.\n\n'
          'Exemples de questions :\n'
          '• Quelle est la prévision du prix du mil à N\'Djamena ?\n'
          '• Évalue le risque de financer 3 millions de FCFA de mil au Salamat.\n'
          '• Quelles sont les alertes de hausse de prix actuelles ?',
    }
  ];
  bool _loading = false;

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _controller.text).trim();
    if (text.isEmpty || _loading) return;
    setState(() {
      _messages.add({'role': 'user', 'text': text});
      _loading = true;
      if (preset == null) _controller.clear();
    });

    try {
      final res = await widget.apiService.sendChatMessage(text);
      setState(() {
        _messages.add({'role': 'assistant', 'text': res['reply'] ?? 'Réponse vide.'});
      });
    } catch (e) {
      setState(() {
        _messages.add({
          'role': 'assistant',
          'text': 'Impossible de joindre le serveur FreeData.AI ($e). Vérifiez que FastAPI tourne sur ${ApiService.baseUrl}.',
        });
      });
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              ActionChip(
                label: const Text('Prévision Mil N\'Djamena'),
                onPressed: () => _send('Quelle est la prévision du prix du mil à N\'Djamena ?'),
              ),
              ActionChip(
                label: const Text('Crédit 3M FCFA Mil Salamat'),
                onPressed: () => _send('Quel est le risque de financer 3 millions de FCFA de mil au Salamat ?'),
              ),
              ActionChip(
                label: const Text('Alertes prix actuelles'),
                onPressed: () => _send('Quelles sont les alertes de hausse de prix actuelles ?'),
              ),
            ],
          ),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: _messages.length,
            itemBuilder: (context, idx) {
              final msg = _messages[idx];
              final isUser = msg['role'] == 'user';
              return Align(
                alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
                child: Container(
                  constraints: const BoxConstraints(maxWidth: 720),
                  margin: const EdgeInsets.symmetric(vertical: 6),
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: isUser
                        ? Theme.of(context).colorScheme.primaryContainer
                        : Theme.of(context).colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: SelectableText(
                    msg['text'] ?? '',
                    style: const TextStyle(fontSize: 15, height: 1.4),
                  ),
                ),
              );
            },
          ),
        ),
        if (_loading) const LinearProgressIndicator(),
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _controller,
                  onSubmitted: (_) => _send(),
                  decoration: const InputDecoration(
                    hintText: 'Posez votre question à FreeData.AI...',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                onPressed: _loading ? null : _send,
                icon: const Icon(Icons.send),
                label: const Text('Envoyer'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
