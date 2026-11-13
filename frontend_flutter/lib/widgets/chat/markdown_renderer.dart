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
          fontSize: 21,
          fontWeight: FontWeight.w700,
          height: 1.35,
        ),
        h2: const TextStyle(
          color: Color(0xFF0F172A),
          fontSize: 18.5,
          fontWeight: FontWeight.w700,
          height: 1.35,
        ),
        h2Padding: const EdgeInsets.only(top: 10, bottom: 2),
        h3: const TextStyle(
          color: Color(0xFF0F172A),
          fontSize: 17,
          fontWeight: FontWeight.w700,
          height: 1.35,
        ),
        h3Padding: const EdgeInsets.only(top: 8, bottom: 2),
        h4: const TextStyle(
          color: Color(0xFF1E293B),
          fontSize: 15.5,
          fontWeight: FontWeight.w700,
          height: 1.35,
        ),
        blockSpacing: 10,
        listIndent: 18,
        strong: const TextStyle(
          color: Color(0xFF0F172A),
          fontWeight: FontWeight.w700,
          fontSize: 15.5,
        ),
        code: const TextStyle(
          backgroundColor: Color(0xFFF1F5F9),
          color: Color(0xFF1E40AF),
          fontWeight: FontWeight.w600,
          fontSize: 14,
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
        horizontalRuleDecoration: const BoxDecoration(
          border: Border(top: BorderSide(color: Color(0xFFE2E8F0), width: 1)),
        ),
        listBullet: const TextStyle(
          color: Color(0xFF1D4ED8),
          fontWeight: FontWeight.bold,
        ),
        tableHead: const TextStyle(
          color: Color(0xFF0F172A),
          fontWeight: FontWeight.w700,
          fontSize: 13.5,
          height: 1.3,
        ),
        tableBody: const TextStyle(
          color: Color(0xFF1E293B),
          fontSize: 13.5,
          height: 1.35,
        ),
        tableBorder: TableBorder.all(
          color: const Color(0xFFE2E8F0),
          borderRadius: BorderRadius.circular(8),
        ),
        tableCellsPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
      ),
    );
  }
}

