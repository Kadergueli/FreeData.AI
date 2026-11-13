import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter/services.dart';

import '../fd_theme.dart';
import '../models/chat_models.dart';

class UserMessageBubble extends StatelessWidget {
  final ChatMessage message;

  const UserMessageBubble({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 760),
        margin: const EdgeInsets.only(bottom: 18),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            begin: Alignment.centerLeft,
            end: Alignment.centerRight,
            colors: [Color(0xFF1D4ED8), Color(0xFF2563EB)],
          ),
          borderRadius: BorderRadius.circular(18).copyWith(bottomRight: const Radius.circular(6)),
          boxShadow: [
            BoxShadow(
              color: FDTheme.blue.withValues(alpha: 0.22),
              blurRadius: 18,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: SelectableText(
          message.text,
          style: const TextStyle(color: Colors.white, height: 1.5, fontSize: 14, fontWeight: FontWeight.w500),
        ),
      ),
    );
  }
}

class AssistantMessage extends StatelessWidget {
  final ChatMessage message;
  final VoidCallback? onRetry;

  const AssistantMessage({super.key, required this.message, this.onRetry});

  @override
  Widget build(BuildContext context) {
    final bool hasError = message.metadata['error'] == true;
    final List<Map<String, dynamic>> sources = (message.sources).cast<Map<String, dynamic>>();
    final dynamic tableData = message.metadata['table'];
    final dynamic chartData = message.metadata['chart'];
    final dynamic summary = message.metadata['summary'];

    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 840),
        margin: const EdgeInsets.only(bottom: 18),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 30,
              height: 30,
              decoration: BoxDecoration(
                color: FDTheme.blue.withValues(alpha: .10),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: FDTheme.blue.withValues(alpha: 0.15)),
              ),
              child: const Center(
                child: Text('FD', style: TextStyle(color: FDTheme.blue, fontSize: 10, fontWeight: FontWeight.w900)),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (message.metadata['intent'] != null && message.metadata['intent'].toString().isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        message.metadata['intent'].toString().replaceAll('_', ' ').toUpperCase(),
                        style: const TextStyle(
                          color: FDTheme.blue,
                          fontSize: 10,
                          fontWeight: FontWeight.w800,
                          letterSpacing: .7,
                        ),
                      ),
                    ),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: hasError ? const Color(0xFFFFF5F4) : const Color(0xFFFFFFFF),
                      border: Border.all(color: hasError ? const Color(0xFFF3D0CD) : FDTheme.line),
                      borderRadius: BorderRadius.circular(18),
                      boxShadow: [
                        BoxShadow(
                          color: const Color(0x0F0F172A),
                          blurRadius: 18,
                          offset: const Offset(0, 8),
                        ),
                      ],
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (hasError)
                          ErrorMessage(
                            message: message.text,
                            onRetry: onRetry,
                          )
                        else ...[
                          MarkdownRenderer(content: message.text),
                          if (summary != null) ...[
                            const SizedBox(height: 14),
                            AnalysisSummary(summary: Map<String, dynamic>.from(summary)),
                          ],
                          if (tableData is List && tableData.isNotEmpty) ...[
                            const SizedBox(height: 14),
                            StructuredDataTable(rows: tableData.map((row) => Map<String, dynamic>.from(row as Map)).toList()),
                          ],
                          if (chartData != null) ...[
                            const SizedBox(height: 14),
                            ChartCard(data: chartData),
                          ],
                          if (sources.isNotEmpty) ...[
                            const SizedBox(height: 14),
                            ...sources.map((source) => Padding(
                                  padding: const EdgeInsets.only(bottom: 8),
                                  child: SourceCard(source: source),
                                )),
                          ],
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Icon(Icons.auto_awesome, size: 13, color: FDTheme.muted),
                      const SizedBox(width: 5),
                      const Text('Réponse FreeData.AI', style: TextStyle(fontSize: 10, color: FDTheme.muted)),
                      const Spacer(),
                      IconButton(
                        tooltip: 'Copier',
                        visualDensity: VisualDensity.compact,
                        onPressed: () async {
                          await Clipboard.setData(ClipboardData(text: message.text));
                        },
                        icon: const Icon(Icons.copy_all_rounded, size: 14, color: FDTheme.muted),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class MarkdownRenderer extends StatelessWidget {
  final String content;

  const MarkdownRenderer({super.key, required this.content});

  @override
  Widget build(BuildContext context) {
    return MarkdownBody(
      data: content,
      selectable: true,
      styleSheet: MarkdownStyleSheet(
        p: const TextStyle(fontSize: 14, height: 1.7, color: FDTheme.ink),
        h1: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: FDTheme.ink),
        h2: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: FDTheme.ink),
        h3: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: FDTheme.ink),
        strong: const TextStyle(fontWeight: FontWeight.w700, color: FDTheme.ink),
        code: const TextStyle(fontFamily: 'monospace', backgroundColor: Color(0xFFF4F7FC), color: FDTheme.blueDark),
        codeblockDecoration: BoxDecoration(
          color: const Color(0xFFF4F7FC),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: FDTheme.line),
        ),
        blockSpacing: 10,
        listBullet: const TextStyle(color: FDTheme.ink),
        tableBorder: TableBorder.all(color: FDTheme.line),
        tableCellsPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      ),
    );
  }
}

class StructuredDataTable extends StatelessWidget {
  final List<Map<String, dynamic>> rows;

  const StructuredDataTable({super.key, required this.rows});

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) {
      return const SizedBox.shrink();
    }

    final headers = rows.first.keys.toList();

    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: FDTheme.line),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          columns: headers
              .map((header) => DataColumn(label: Text(header, style: const TextStyle(fontWeight: FontWeight.w700))))
              .toList(),
          rows: rows
              .map(
                (row) => DataRow(
                  cells: headers
                      .map((header) => DataCell(Text(row[header]?.toString() ?? '—')))
                      .toList(),
                ),
              )
              .toList(),
        ),
      ),
    );
  }
}

class ChartCard extends StatelessWidget {
  final dynamic data;

  const ChartCard({super.key, required this.data});

  @override
  Widget build(BuildContext context) {
    final values = data is Map ? Map<String, dynamic>.from(data as Map) : <String, dynamic>{};
    final entries = values.entries.toList();
    if (entries.isEmpty) {
      return const SizedBox.shrink();
    }

    final maxValue = entries
        .map((entry) => num.tryParse(entry.value.toString()) ?? 0)
        .fold<double>(0, (sum, value) => sum > value.toDouble() ? sum : value.toDouble());

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FBFF),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: FDTheme.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Vue synthétique', style: TextStyle(fontWeight: FontWeight.w700, color: FDTheme.ink)),
          const SizedBox(height: 12),
          SizedBox(
            height: 140,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: entries.map((entry) {
                final value = num.tryParse(entry.value.toString()) ?? 0;
                final ratio = maxValue == 0 ? 0.0 : value.toDouble() / maxValue;
                return Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        Container(
                          height: 90 * ratio,
                          decoration: BoxDecoration(
                            color: FDTheme.blue.withValues(alpha: 0.9),
                            borderRadius: const BorderRadius.vertical(top: Radius.circular(8)),
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          entry.key.length > 8 ? '${entry.key.substring(0, 7)}…' : entry.key,
                          style: const TextStyle(fontSize: 10, color: FDTheme.muted),
                        ),
                      ],
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
        ],
      ),
    );
  }
}

class SourceCard extends StatelessWidget {
  final Map<String, dynamic> source;

  const SourceCard({super.key, required this.source});

  @override
  Widget build(BuildContext context) {
    final label = source['name']?.toString() ?? 'Source';
    final provenance = source['source']?.toString() ?? source['provenance']?.toString() ?? 'Inconnue';
    final details = source['details']?.toString() ?? source['description']?.toString();

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F9FC),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: FDTheme.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.link_rounded, size: 16, color: FDTheme.blue),
              const SizedBox(width: 8),
              Expanded(
                child: Text(formatSourceLabel(label), style: const TextStyle(fontWeight: FontWeight.w700, color: FDTheme.ink)),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(provenance, style: const TextStyle(fontSize: 12, color: FDTheme.muted)),
          if (details != null && details.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(details, style: const TextStyle(fontSize: 12, color: FDTheme.muted, height: 1.5)),
          ],
        ],
      ),
    );
  }

  String formatSourceLabel(String label) {
    if (label.length > 80) {
      return '${label.substring(0, 77)}...';
    }
    return label;
  }
}

class AnalysisSummary extends StatelessWidget {
  final Map<String, dynamic> summary;

  const AnalysisSummary({super.key, required this.summary});

  @override
  Widget build(BuildContext context) {
    final title = summary['title']?.toString() ?? 'Synthèse';
    final items = summary['items'] is List ? summary['items'] as List : const <dynamic>[];

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFEAF9F6),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFCAEDE7)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w800, color: FDTheme.blueDark)),
          const SizedBox(height: 8),
          ...items.map((item) => Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.check_circle_outline_rounded, size: 15, color: FDTheme.green),
                    const SizedBox(width: 8),
                    Expanded(child: Text(item.toString(), style: const TextStyle(color: FDTheme.ink, height: 1.5))),
                  ],
                ),
              )),
        ],
      ),
    );
  }
}

class LoadingIndicator extends StatelessWidget {
  final String label;

  const LoadingIndicator({super.key, this.label = 'FreeData.AI prépare une réponse…'});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 18),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: const Color(0xFFF5F9FF),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: FDTheme.line),
        ),
        child: Row(
          children: [
            const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(FDTheme.blue),
              ),
            ),
            const SizedBox(width: 10),
            Text(label, style: const TextStyle(color: FDTheme.muted, fontSize: 13)),
          ],
        ),
      ),
    );
  }
}

class ErrorMessage extends StatelessWidget {
  final String message;
  final VoidCallback? onRetry;

  const ErrorMessage({super.key, required this.message, this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Row(
          children: [
            Icon(Icons.error_outline_rounded, color: FDTheme.muted, size: 18),
            SizedBox(width: 8),
            Text('Le service n’a pas répondu', style: TextStyle(fontWeight: FontWeight.w700, color: FDTheme.ink)),
          ],
        ),
        const SizedBox(height: 10),
        Text(message, style: const TextStyle(color: FDTheme.muted, height: 1.6)),
        if (onRetry != null) ...[
          const SizedBox(height: 12),
          TextButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh_rounded, size: 16),
            label: const Text('Réessayer'),
          ),
        ],
      ],
    );
  }
}

class WorkspaceSuggestion extends StatelessWidget {
  final String title;
  final VoidCallback onTap;

  const WorkspaceSuggestion({super.key, required this.title, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            begin: Alignment.centerLeft,
            end: Alignment.centerRight,
            colors: [Color(0xFFFFFFFF), Color(0xFFF5F9FF)],
          ),
          border: Border.all(color: FDTheme.line),
          borderRadius: BorderRadius.circular(14),
          boxShadow: const [
            BoxShadow(
              color: Color(0x0F0F172A),
              blurRadius: 10,
              offset: Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 24,
              height: 24,
              decoration: BoxDecoration(
                color: FDTheme.blue.withValues(alpha: 0.10),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(Icons.north_east, size: 14, color: FDTheme.blue),
            ),
            const SizedBox(width: 8),
            Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: FDTheme.ink)),
          ],
        ),
      ),
    );
  }
}
