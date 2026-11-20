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
  String _selectedCategory = 'Toutes';

  static const List<String> _categories = [
    'Toutes',
    'Catalogue des données',
    'Documents privés',
    'Méthodologie',
    'FAQ',
  ];

  static const List<Map<String, String>> _entries = [
    {
      'category': 'Catalogue des données',
      'title': 'Les 8 domaines d’analyse dédiés au Tchad',
      'body':
          'FreeData.AI est conçu pour le contexte tchadien autour de 8 domaines : Marchés et prix des produits (données actives et prévisions mensuelles) ainsi que 7 domaines en cours de préparation (Agriculture, Économie, Santé, Population, Environnement, Infrastructures et Transport).',
    },
    {
      'category': 'Catalogue des données',
      'title': 'Sources primaires, normalisation et prévisions',
      'body':
          'Les relevés de prix proviennent des marchés tchadiens (FreeData.td / PAM-WFP), normalisés en XAF/kg. Les indicateurs de tendance, les prévisions mensuelles, le Credit Passport et la détection d’anomalies sont calculés automatiquement à partir de ces séries vérifiées.',
    },
    {
      'category': 'Documents privés',
      'title': 'Analyser vos propres fichiers (PDF, CSV, TXT)',
      'body':
          'Depuis le chat, vous pouvez joindre vos rapports, tableaux ou notes. Chaque document est découpé et indexé pour la recherche sémantique IA, tout en restant strictement privé et isolé sur votre compte. Vous pouvez consulter ou supprimer vos documents à tout moment dans Mon compte.',
    },
    {
      'category': 'Méthodologie',
      'title': 'Moteur financier déterministe (80/8/12 & 88/0/12)',
      'body':
          'Allocation par défaut d’un capital commercial : 80 % fonds de roulement (BFR), 8 % investissement matériel (CAPEX), 12 % réserve de sécurité (ou 88/0/12 si CAPEX = 0). Le point mort est calculé de façon transparente hors charges locales non mesurées.',
    },
    {
      'category': 'Méthodologie',
      'title': 'Contrôle Qualité (QA) des rapports PDF PRO',
      'body':
          'Chaque étude de marché PRO est contrôlée automatiquement sur 6 critères (conformité, qualité des données, cohérence financière, traçabilité des sources, complétude et transparence). Si un critère critique échoue, la génération est bloquée et les corrections nécessaires sont indiquées.',
    },
    {
      'category': 'FAQ',
      'title':
          'Pourquoi certaines sections (concurrence, demande) sont indiquées non mesurées ?',
      'body':
          'FreeData.AI mesure les prix de marché et leur volatilité, mais ne dispose pas des volumes de demande des ménages ni des parts de marché des concurrents. Par exigence de fiabilité, aucun chiffre n’est jamais inventé.',
    },
    {
      'category': 'FAQ',
      'title':
          'Comment ajuster un budget ou exclure une section en cours de discussion ?',
      'body':
          'Écrivez simplement « Finalement budget 1 200 000 XAF », « BFR constant » ou « Exclure projection 6 mois ». Le contexte de votre étude est mis à jour immédiatement sans avoir à tout ressaisir.',
    },
  ];

  @override
  Widget build(BuildContext context) {
    final q = _query.trim().toLowerCase();
    final filtered = _entries.where((e) {
      final matchCat =
          _selectedCategory == 'Toutes' || e['category'] == _selectedCategory;
      if (!matchCat) return false;
      if (q.isEmpty) return true;
      return e['title']!.toLowerCase().contains(q) ||
          e['body']!.toLowerCase().contains(q) ||
          e['category']!.toLowerCase().contains(q);
    }).toList();

    return Scaffold(
      backgroundColor: AppColors.canvas,
      appBar: AppBar(
        title: const Text(
          'Documentation & Méthodologie',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 10),
                child: TextField(
                  decoration: const InputDecoration(
                    prefixIcon: Icon(Icons.search_rounded),
                    hintText:
                        'Rechercher (Tchad, documents privés, formules, FAQ)...',
                  ),
                  onChanged: (v) => setState(() => _query = v),
                ),
              ),
              SizedBox(
                height: 38,
                child: ListView.separated(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  scrollDirection: Axis.horizontal,
                  itemCount: _categories.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, i) {
                    final cat = _categories[i];
                    final selected = cat == _selectedCategory;
                    return ChoiceChip(
                      label: Text(cat),
                      selected: selected,
                      onSelected: (_) =>
                          setState(() => _selectedCategory = cat),
                    );
                  },
                ),
              ),
              const SizedBox(height: 10),
              Expanded(
                child: filtered.isEmpty
                    ? Center(
                        child: Padding(
                          padding: const EdgeInsets.all(24),
                          child: FDCard(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Icon(Icons.search_off_rounded,
                                    size: 32, color: AppColors.muted),
                                const SizedBox(height: 8),
                                Text(
                                  'Aucun article ne correspond à « $_query ».',
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(
                                    fontSize: 13.5,
                                    color: AppColors.muted,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      )
                    : ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 4, 16, 20),
                        itemCount: filtered.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 10),
                        itemBuilder: (_, i) {
                          final item = filtered[i];
                          return FDCard(
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                FDBadge(
                                  label: item['category']!,
                                  color: AppColors.blue,
                                  backgroundColor: AppColors.blueSoft,
                                ),
                                const SizedBox(height: 8),
                                Text(
                                  item['title']!,
                                  style: const TextStyle(
                                    fontSize: 15,
                                    fontWeight: FontWeight.w700,
                                    color: AppColors.ink,
                                  ),
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  item['body']!,
                                  style: const TextStyle(
                                    fontSize: 13.5,
                                    height: 1.5,
                                    color: AppColors.body,
                                  ),
                                ),
                              ],
                            ),
                          );
                        },
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
