import 'package:flutter/material.dart';
import '../../core/fd_theme.dart';

class AnalysisSummary extends StatelessWidget {
  final Map<String, dynamic> summary;

  const AnalysisSummary({super.key, required this.summary});

  @override
  Widget build(BuildContext context) {
    final title = summary['title']?.toString() ?? 'Synthèse de l’analyse';
    final items =
        summary['items'] is List ? summary['items'] as List : const <dynamic>[];

    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: FDTheme.greenSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: FDTheme.greenBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.check_circle_outline_rounded,
                  size: 16, color: FDTheme.green),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    color: FDTheme.greenDark,
                    fontSize: 13,
                  ),
                ),
              ),
            ],
          ),
          if (items.isNotEmpty) ...[
            const SizedBox(height: 8),
            ...items.map((item) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('• ',
                          style: TextStyle(
                              color: FDTheme.green,
                              fontWeight: FontWeight.bold)),
                      Expanded(
                        child: Text(
                          item.toString(),
                          style: const TextStyle(
                              fontSize: 12.5,
                              color: FDTheme.greenDark,
                              height: 1.4),
                        ),
                      ),
                    ],
                  ),
                )),
          ],
        ],
      ),
    );
  }
}

class DataTableCard extends StatelessWidget {
  final List<Map<String, dynamic>> rows;

  const DataTableCard({super.key, required this.rows});

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const SizedBox.shrink();

    final headers = rows.first.keys.toList();

    return Container(
      margin: const EdgeInsets.only(top: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: FDTheme.line),
        color: FDTheme.surface,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: const BoxDecoration(
              color: FDTheme.canvas,
              borderRadius: BorderRadius.vertical(top: Radius.circular(10)),
            ),
            child: const Row(
              children: [
                Icon(Icons.table_chart_outlined,
                    size: 15, color: FDTheme.subtle),
                SizedBox(width: 6),
                Text(
                  'Données structurées',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: FDTheme.muted,
                  ),
                ),
              ],
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              headingRowHeight: 36,
              dataRowMinHeight: 36,
              dataRowMaxHeight: 44,
              columns: headers
                  .map(
                    (h) => DataColumn(
                      label: Text(
                        h,
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: FDTheme.ink,
                        ),
                      ),
                    ),
                  )
                  .toList(),
              rows: rows
                  .map(
                    (r) => DataRow(
                      cells: headers
                          .map(
                            (h) => DataCell(
                              Text(
                                r[h]?.toString() ?? '—',
                                style: const TextStyle(
                                    fontSize: 12, color: FDTheme.body),
                              ),
                            ),
                          )
                          .toList(),
                    ),
                  )
                  .toList(),
            ),
          ),
        ],
      ),
    );
  }
}

class ChartCard extends StatelessWidget {
  final dynamic data;

  const ChartCard({super.key, required this.data});

  @override
  Widget build(BuildContext context) {
    final values = data is Map
        ? Map<String, dynamic>.from(data as Map)
        : <String, dynamic>{};
    final entries = values.entries.toList();

    if (entries.isEmpty) return const SizedBox.shrink();

    final maxValue = entries
        .map((e) => num.tryParse(e.value.toString()) ?? 0)
        .fold<double>(
            0, (max, val) => max > val.toDouble() ? max : val.toDouble());

    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: FDTheme.canvas,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: FDTheme.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.bar_chart_rounded, size: 16, color: FDTheme.blue),
              SizedBox(width: 6),
              Text(
                'Aperçu comparatif',
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: FDTheme.ink,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 120,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: entries.map((e) {
                final val = num.tryParse(e.value.toString()) ?? 0;
                final ratio = maxValue <= 0
                    ? 0.0
                    : (val.toDouble() / maxValue).clamp(0.0, 1.0);
                return Expanded(
                  child: Tooltip(
                    message: '${e.key} : ${val.toStringAsFixed(0)}',
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: [
                          Text(
                            val.toStringAsFixed(0),
                            style: const TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w600,
                                color: FDTheme.subtle),
                          ),
                          const SizedBox(height: 4),
                          Container(
                            height: 70 * ratio,
                            decoration: const BoxDecoration(
                              color: FDTheme.blue,
                              borderRadius: BorderRadius.vertical(
                                  top: Radius.circular(4)),
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            e.key.length > 10
                                ? '${e.key.substring(0, 9)}…'
                                : e.key,
                            style: const TextStyle(
                                fontSize: 10, color: FDTheme.subtle),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
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
