import 'package:flutter/material.dart';

class AnalysisSummary extends StatelessWidget {
  final Map<String, dynamic> summary;

  const AnalysisSummary({super.key, required this.summary});

  @override
  Widget build(BuildContext context) {
    final title = summary['title']?.toString() ?? 'Synthèse de l’analyse';
    final items = summary['items'] is List ? summary['items'] as List : const <dynamic>[];

    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF0FDF4),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFBBF7D0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.check_circle_outline_rounded, size: 16, color: Color(0xFF16A34A)),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    color: Color(0xFF166534),
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
                      const Text('• ', style: TextStyle(color: Color(0xFF16A34A), fontWeight: FontWeight.bold)),
                      Expanded(
                        child: Text(
                          item.toString(),
                          style: const TextStyle(fontSize: 12.5, color: Color(0xFF14532D), height: 1.4),
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
        border: Border.all(color: const Color(0xFFE2E8F0)),
        color: Colors.white,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: const BoxDecoration(
              color: Color(0xFFF8FAFC),
              borderRadius: BorderRadius.vertical(top: Radius.circular(10)),
            ),
            child: const Row(
              children: [
                Icon(Icons.table_chart_outlined, size: 15, color: Color(0xFF64748B)),
                SizedBox(width: 6),
                Text(
                  'Données structurées',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF475569),
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
                          color: Color(0xFF0F172A),
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
                                style: const TextStyle(fontSize: 12, color: Color(0xFF334155)),
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
    final values = data is Map ? Map<String, dynamic>.from(data as Map) : <String, dynamic>{};
    final entries = values.entries.toList();

    if (entries.isEmpty) return const SizedBox.shrink();

    final maxValue = entries
        .map((e) => num.tryParse(e.value.toString()) ?? 0)
        .fold<double>(0, (max, val) => max > val.toDouble() ? max : val.toDouble());

    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.bar_chart_rounded, size: 16, color: Color(0xFF1D4ED8)),
              SizedBox(width: 6),
              Text(
                'Aperçu comparatif',
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF0F172A),
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
                final ratio = maxValue == 0 ? 0.0 : val.toDouble() / maxValue;
                return Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        Text(
                          val.toStringAsFixed(0),
                          style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: Color(0xFF64748B)),
                        ),
                        const SizedBox(height: 4),
                        Container(
                          height: 70 * ratio,
                          decoration: const BoxDecoration(
                            color: Color(0xFF1D4ED8),
                            borderRadius: BorderRadius.vertical(top: Radius.circular(4)),
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          e.key.length > 7 ? '${e.key.substring(0, 6)}…' : e.key,
                          style: const TextStyle(fontSize: 10, color: Color(0xFF64748B)),
                          overflow: TextOverflow.ellipsis,
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

