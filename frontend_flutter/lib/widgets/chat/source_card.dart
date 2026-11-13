import 'package:flutter/material.dart';

class SourceCard extends StatelessWidget {
  final Map<String, dynamic> source;

  const SourceCard({super.key, required this.source});

  @override
  Widget build(BuildContext context) {
    final name = source['name']?.toString() ??
        source['title']?.toString() ??
        source['source']?.toString() ??
        'Source';
    final details = source['details']?.toString() ??
        source['provenance']?.toString() ??
        source['description']?.toString();

    final isRecognized = name.toUpperCase().contains('WFP') ||
        name.toUpperCase().contains('FEWS') ||
        (details != null &&
            (details.toUpperCase().contains('WFP') ||
                details.toUpperCase().contains('FEWS')));

    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(5),
            decoration: BoxDecoration(
              color: const Color(0xFFEFF6FF),
              borderRadius: BorderRadius.circular(6),
            ),
            child: const Icon(
              Icons.verified_outlined,
              size: 14,
              color: Color(0xFF1D4ED8),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        name,
                        style: const TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                          color: Color(0xFF0F172A),
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (isRecognized) ...[
                      const SizedBox(width: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xFFEFF6FF),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Text(
                          'Vérifiée',
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                            color: Color(0xFF1D4ED8),
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
                if (details != null && details.isNotEmpty) ...[
                  const SizedBox(height: 3),
                  Text(
                    details,
                    style: const TextStyle(
                      fontSize: 11.5,
                      color: Color(0xFF64748B),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

