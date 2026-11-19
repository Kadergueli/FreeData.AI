import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../core/fd_theme.dart';
import '../../core/models/chat_models.dart';
import '../../core/utils/formatters.dart';
import 'markdown_renderer.dart';
import 'source_card.dart';
import 'data_cards.dart';
import 'error_message.dart';

class AssistantMessage extends StatelessWidget {
  final ChatMessage message;
  final Future<void> Function()? onRetry;
  final VoidCallback? onSaveToLibrary;
  final bool isSavedInLibrary;
  final bool showSaveButton;

  const AssistantMessage({
    super.key,
    required this.message,
    this.onRetry,
    this.onSaveToLibrary,
    this.isSavedInLibrary = false,
    this.showSaveButton = true,
  });

  static final RegExp _trailingDisclaimerRegex = RegExp(
    r'\n{1,2}[_*]*((?:Indicateur informatif|Une prévision est une estimation|Les indicateurs constituent une aide)[^\n]+)[_*]*\s*$',
  );

  ({String body, String? disclaimer}) _extractBodyAndDisclaimer() {
    final explicitDisclaimer =
        message.metadata['disclaimer']?.toString().trim();
    final match = _trailingDisclaimerRegex.firstMatch(message.text);
    if (match != null) {
      final body = message.text.substring(0, match.start).trimRight();
      final extracted =
          match.group(1)?.replaceAll(RegExp(r'^[_*\s]+|[_*\s]+$'), '').trim();
      return (
        body: body.isNotEmpty ? body : message.text,
        disclaimer:
            (explicitDisclaimer != null && explicitDisclaimer.isNotEmpty)
                ? explicitDisclaimer
                : extracted,
      );
    }
    return (
      body: message.text,
      disclaimer: (explicitDisclaimer != null && explicitDisclaimer.isNotEmpty)
          ? explicitDisclaimer
          : null,
    );
  }

  @override
  Widget build(BuildContext context) {
    final bool hasError = message.metadata['error'] == true;
    final List<Map<String, dynamic>> sources =
        (message.sources).cast<Map<String, dynamic>>();
    final dynamic tableData = message.metadata['table'] ??
        message.metadata['data'] ??
        message.metadata['results'];
    final dynamic chartData =
        message.metadata['chart'] ?? message.metadata['chart_data'];
    final dynamic summary =
        message.metadata['summary'] ?? message.metadata['analysis'];
    final parsed = _extractBodyAndDisclaimer();

    return Padding(
      padding: const EdgeInsets.only(bottom: 22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 20,
                height: 20,
                decoration: BoxDecoration(
                  color: FDTheme.blue,
                  borderRadius: BorderRadius.circular(5),
                ),
                alignment: Alignment.center,
                child: const Text(
                  'FD',
                  style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                    fontSize: 9.5,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              const Text(
                'FreeData.AI',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: FDTheme.subtle,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (hasError)
            ErrorMessage(
              message: message.text,
              onRetry: onRetry,
            )
          else ...[
            MarkdownRenderer(content: parsed.body),
            if (summary is Map) ...[
              AnalysisSummary(summary: Map<String, dynamic>.from(summary)),
            ],
            if (tableData is List && tableData.isNotEmpty) ...[
              DataTableCard(
                rows: tableData
                    .map((row) => Map<String, dynamic>.from(row as Map))
                    .toList(),
              ),
            ],
            if (chartData != null) ...[
              ChartCard(data: chartData),
            ],
            if (sources.isNotEmpty) ...[
              ...sources.map((s) => SourceCard(source: s)),
            ],
            if (parsed.disclaimer != null && parsed.disclaimer!.isNotEmpty)
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(top: 10),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: FDTheme.canvas,
                  border: Border.all(color: FDTheme.line),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  parsed.disclaimer!,
                  style: const TextStyle(
                    fontSize: 12,
                    height: 1.45,
                    color: FDTheme.subtle,
                  ),
                ),
              ),
            const SizedBox(height: 8),
            Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 8,
              children: [
                IconButton(
                  icon: const Icon(Icons.copy_rounded,
                      size: 18, color: FDTheme.subtle),
                  tooltip: 'Copier la réponse',
                  padding: const EdgeInsets.all(10),
                  constraints:
                      const BoxConstraints(minWidth: 44, minHeight: 44),
                  onPressed: () {
                    Clipboard.setData(ClipboardData(
                        text: cleanMarkdownForClipboard(message.text)));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Réponse copiée dans le presse-papiers'),
                        duration: Duration(seconds: 2),
                      ),
                    );
                  },
                ),
                if (showSaveButton)
                  TextButton.icon(
                    icon: Icon(
                      isSavedInLibrary
                          ? Icons.bookmark_rounded
                          : Icons.bookmark_border_rounded,
                      size: 18,
                      color: isSavedInLibrary ? FDTheme.blue : FDTheme.subtle,
                    ),
                    label: Text(
                      isSavedInLibrary
                          ? 'Enregistrée dans Library'
                          : 'Sauvegarder dans Library',
                      style: TextStyle(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w500,
                        color: isSavedInLibrary ? FDTheme.blue : FDTheme.subtle,
                      ),
                    ),
                    style: TextButton.styleFrom(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 10),
                      minimumSize: const Size(0, 44),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    onPressed: () {
                      if (onSaveToLibrary != null) {
                        onSaveToLibrary!();
                      } else {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text(
                                'Analyse enregistrée dans la Bibliothèque locale'),
                            duration: Duration(seconds: 2),
                          ),
                        );
                      }
                    },
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
