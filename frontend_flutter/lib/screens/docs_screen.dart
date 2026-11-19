import 'package:flutter/material.dart';

import '../core/design_system/fd_design_system.dart';
import '../core/theme/app_theme.dart';

class DocsScreen extends StatefulWidget {
  const DocsScreen({super.key});

  @override
  State<DocsScreen> createState() => _DocsScreenState();
}

class _DocsScreenState extends State<DocsScreen> {
  String _query = '';

  static const List<Map<String, String>> _entries = [
    {
      'category': 'Catalogue des données',
      'title': 'Sources primaires & Couches Silver / Gold',
      'body':
          'Les prix proviennent des relevés marchés (FreeData.td / WFP) normalisés en XAF/kg dans v_clean_markets (Silver), puis publiés dans table_ml_forecasts, table_ml_credit_passport, table_ml_seasonality_studies et table_ml_anomalies (Gold).',
    },
    {
      'category': 'Méthodologie',
      'title': 'Moteur financier déterministe (80/8/12 & 88/0/12)',
      'body':
          'Allocation par défaut : 80 % BFR, 8 % CAPEX, 12 % Réserve (ou 88/0/12 si CAPEX = 0). Réinvestissement par défaut : 75 % du résultat net (ou BFR constant M1-M6 sur consigne). Point mort calculé hors coûts non mesurés (taxes communales, gardiennage).',
    },
    {
      'category': 'Méthodologie',
      'title': 'Validation Qualité (QA) & Blocage PDF',
      'body':
          'Chaque étude PRO est évaluée sur 6 dimensions (conformité, qualité des données, cohérence financière, traçabilité, complétude, transparence). Tout échec critique bloque le PDF (HTTP 422) et indique les corrections requises.',
    },
    {
      'category': 'FAQ',
      'title':
          'Pourquoi certaines sections (concurrence, demande) sont marquées indisponibles ?',
      'body':
          'FreeData.AI suit les prix de marché et la volatilité mais ne mesure pas les volumes de demande des ménages ni les parts de marché des concurrents. Aucun chiffre n’est jamais inventé.',
    },
    {
      'category': 'FAQ',
      'title':
          'Comment corriger un budget ou exclure une section en cours de discussion ?',
      'body':
          'Écrivez simplement « Finalement budget 1 200 000 XAF », « BFR constant » ou « Exclure projection 6 mois ». Le StudyContext persistant met à jour uniquement le paramètre concerné.',
    },
    {
      'category': 'Historique des versions',
      'title': 'Version 1.2.0 — Plateforme IA Multi-Domaines',
      'body':
          'Assistant IA sur 10 domaines, StudyContext persistant, génération PDF modulaire avec porte QA (422), gestion de projets & versions d’études, backtest chronologique 70/30, RAG hybride, quotas serveur et console d’administration RBAC.',
    },
  ];

  @override
  Widget build(BuildContext context) {
    final q = _query.trim().toLowerCase();
    final filtered = q.isEmpty
        ? _entries
        : _entries
            .where((e) =>
                e['title']!.toLowerCase().contains(q) ||
                e['body']!.toLowerCase().contains(q) ||
                e['category']!.toLowerCase().contains(q))
            .toList();

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
          title: const Text('Documentation & Méthodologie',
              style: TextStyle(fontWeight: FontWeight.w700))),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search_rounded),
                hintText: 'Rechercher (données, formules, QA, FAQ)...',
              ),
              onChanged: (v) => setState(() => _query = v),
            ),
          ),
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              itemCount: filtered.length,
              separatorBuilder: (_, __) => const SizedBox(height: 10),
              itemBuilder: (_, i) {
                final item = filtered[i];
                return FDCard(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item['category']!,
                        style: const TextStyle(
                            fontSize: 11.5,
                            fontWeight: FontWeight.w700,
                            color: AppColors.blue),
                      ),
                      const SizedBox(height: 4),
                      Text(item['title']!,
                          style: const TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink)),
                      const SizedBox(height: 6),
                      Text(item['body']!,
                          style: const TextStyle(
                              fontSize: 13.5,
                              height: 1.45,
                              color: AppColors.body)),
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
