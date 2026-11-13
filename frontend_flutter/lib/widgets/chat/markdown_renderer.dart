import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

class MarkdownRenderer extends StatelessWidget {
  final String content;

  const MarkdownRenderer({super.key, required this.content});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return MarkdownBody(
      data: content,
      selectable: true,
      styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
        p: const TextStyle(
          color: Color(0xFF0F172A),
          fontSize: 16,
          height: 1.6,
        ),
        h1: const TextStyle(
          color: Color(0xFF0F172A),
          fontSize: 22,
          fontWeight: FontWeight.w700,
          height: 1.4,
        ),
        h2: const TextStyle(
          color: Color(0xFF0F172A),
          fontSize: 19,
          fontWeight: FontWeight.w700,
          height: 1.4,
        ),
        h3: const TextStyle(
          color: Color(0xFF0F172A),
          fontSize: 17,
          fontWeight: FontWeight.w600,
          height: 1.4,
        ),
        strong: const TextStyle(
          color: Color(0xFF0F172A),
          fontWeight: FontWeight.w700,
          fontSize: 16,
        ),
        code: const TextStyle(
          backgroundColor: Color(0xFFEFF6FF),
          color: Color(0xFF1D4ED8),
          fontWeight: FontWeight.w700,
          fontSize: 14.5,
          fontFamily: 'monospace',
        ),
        codeblockDecoration: BoxDecoration(
          color: const Color(0xFFF1F5F9),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFFE2E8F0)),
        ),
        codeblockPadding: const EdgeInsets.all(12),
        blockquoteDecoration: BoxDecoration(
          color: const Color(0xFFF8FAFC),
          borderRadius: BorderRadius.circular(4),
          border: const Border(
            left: BorderSide(color: Color(0xFF1D4ED8), width: 3),
          ),
        ),
        listBullet: const TextStyle(
          color: Color(0xFF1D4ED8),
          fontWeight: FontWeight.bold,
        ),
        tableBorder: TableBorder.all(color: const Color(0xFFE2E8F0)),
        tableCellsPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      ),
    );
  }
}

