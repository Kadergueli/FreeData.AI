import 'package:flutter/material.dart';
import '../../core/fd_theme.dart';
import '../../core/models/chat_models.dart';

class UserMessageBubble extends StatelessWidget {
  final ChatMessage message;

  const UserMessageBubble({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Align(
        alignment: Alignment.centerRight,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 620),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: FDTheme.canvasSoft,
            borderRadius: BorderRadius.circular(18),
          ),
          child: SelectableText(
            message.text,
            style: const TextStyle(
              color: FDTheme.ink,
              fontSize: 16,
              height: 1.5,
              fontWeight: FontWeight.w400,
            ),
          ),
        ),
      ),
    );
  }
}

