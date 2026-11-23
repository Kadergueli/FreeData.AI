import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../../core/fd_theme.dart';
import '../../core/utils/open_url.dart';

class MarkdownRenderer extends StatelessWidget {
  final String content;

  const MarkdownRenderer({super.key, required this.content});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return MarkdownBody(
      data: content,
      selectable: true,
      onTapLink: (text, href, title) => openExternalUrl(href),
      // Aucune image distante : évite le pistage et l'exfiltration par URL.
      imageBuilder: (uri, title, alt) => const SizedBox.shrink(),
      styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
        p: const TextStyle(
          color: FDTheme.ink,
          fontSize: 16,
          height: 1.6,
        ),
        h1: const TextStyle(
          color: FDTheme.ink,
          fontSize: 21,
          fontWeight: FontWeight.w700,
          height: 1.35,
        ),
        h2: const TextStyle(
          color: FDTheme.ink,
          fontSize: 18.5,
          fontWeight: FontWeight.w700,
          height: 1.35,
        ),
        h2Padding: const EdgeInsets.only(top: 10, bottom: 2),
        h3: const TextStyle(
          color: FDTheme.ink,
          fontSize: 17,
          fontWeight: FontWeight.w700,
          height: 1.35,
        ),
        h3Padding: const EdgeInsets.only(top: 8, bottom: 2),
        h4: const TextStyle(
          color: FDTheme.inkSoft,
          fontSize: 15.5,
          fontWeight: FontWeight.w700,
          height: 1.35,
        ),
        blockSpacing: 10,
        listIndent: 18,
        strong: const TextStyle(
          color: FDTheme.ink,
          fontWeight: FontWeight.w700,
          fontSize: 15.5,
        ),
        code: const TextStyle(
          backgroundColor: FDTheme.canvasSoft,
          color: FDTheme.blueDark,
          fontWeight: FontWeight.w600,
          fontSize: 14,
          fontFamily: 'monospace',
        ),
        codeblockDecoration: BoxDecoration(
          color: FDTheme.canvasSoft,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: FDTheme.line),
        ),
        codeblockPadding: const EdgeInsets.all(12),
        blockquoteDecoration: BoxDecoration(
          color: FDTheme.canvas,
          borderRadius: BorderRadius.circular(4),
          border: const Border(
            left: BorderSide(color: FDTheme.blue, width: 3),
          ),
        ),
        horizontalRuleDecoration: const BoxDecoration(
          border: Border(top: BorderSide(color: FDTheme.line, width: 1)),
        ),
        listBullet: const TextStyle(
          color: FDTheme.blue,
          fontWeight: FontWeight.bold,
        ),
        tableHead: const TextStyle(
          color: FDTheme.ink,
          fontWeight: FontWeight.w700,
          fontSize: 13.5,
          height: 1.3,
        ),
        tableBody: const TextStyle(
          color: FDTheme.inkSoft,
          fontSize: 13.5,
          height: 1.35,
        ),
        tableBorder: TableBorder.all(
          color: FDTheme.line,
          borderRadius: BorderRadius.circular(8),
        ),
        tableCellsPadding:
            const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
      ),
    );
  }
}
