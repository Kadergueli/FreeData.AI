/// Formate un montant numérique XAF avec un séparateur de milliers par espace.
/// Exemple : `650000` -> `'650 000'`, `232.57` -> `'233'`.
String formatXaf(num value) {
  final rounded = value.round();
  final sign = rounded < 0 ? '-' : '';
  final digits = rounded.abs().toString();
  final buffer = StringBuffer(sign);
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) {
      buffer.write(' ');
    }
    buffer.write(digits[i]);
  }
  return buffer.toString();
}

/// Convertit une valeur dynamique (`num` ou `String`) en `num` si possible.
num? parseNum(dynamic value) {
  if (value is num) return value;
  if (value is String) {
    final normalized = value.trim().replaceAll(' ', '').replaceAll(',', '.');
    return num.tryParse(normalized);
  }
  return null;
}

/// Nettoie les marqueurs Markdown et l'avertissement de produit par défaut
/// pour afficher des aperçus lisibles dans la Bibliothèque.
String stripMarkdown(String text) {
  if (text.isEmpty) return '';
  var cleaned = text.replaceAll(
    RegExp(r'ℹ️\s*Produit non précisé ou non reconnu\s*:[^\n]+\n*'),
    '',
  );
  cleaned = cleaned.replaceAll(RegExp(r'^\s{0,3}#{1,6}\s*', multiLine: true), '');
  cleaned = cleaned.replaceAll(RegExp(r'^\s*[-*_]{3,}\s*$', multiLine: true), '');
  cleaned = cleaned.replaceAll(RegExp(r'^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*$', multiLine: true), '');
  cleaned = cleaned
      .replaceAll('###', '')
      .replaceAll('**', '')
      .replaceAll('*', '')
      .replaceAll('`', '')
      .replaceAll('_', '')
      .replaceAll('|', ' ');
  return cleaned.replaceAll(RegExp(r'\s+'), ' ').trim();
}

/// Nettoie le Markdown tout en conservant les sauts de ligne pour un collage propre.
String cleanMarkdownForClipboard(String text) {
  if (text.isEmpty) return '';
  final lines = text.replaceAll('\r\n', '\n').split('\n');
  final cleanedLines = <String>[];
  final separatorRow = RegExp(r'^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*$');
  final hrRow = RegExp(r'^\s*[-*_]{3,}\s*$');

  for (var line in lines) {
    if (separatorRow.hasMatch(line) || hrRow.hasMatch(line)) {
      continue;
    }
    line = line.replaceAll(RegExp(r'^\s{0,3}#{1,6}\s*'), '');
    if (line.contains('|')) {
      final cells = line
          .split('|')
          .map((c) => c.trim())
          .where((c) => c.isNotEmpty)
          .toList();
      line = cells.join(' · ');
    }
    line = line
        .replaceAll('###', '')
        .replaceAll('**', '')
        .replaceAll('`', '')
        .replaceAll(RegExp(r'(^|\s)_+|_+(\s|$)'), r'$1$2');
    cleanedLines.add(line.trimRight());
  }

  return cleanedLines
      .join('\n')
      .replaceAll(RegExp(r'\n{3,}'), '\n\n')
      .trim();
}

const Map<String, String> commodityNamesFr = {
  'Millet': 'Mil (Millet)',
  'Sorghum (red)': 'Sorgho rouge',
  'Maize (white)': 'Maïs blanc',
  'Rice (imported)': 'Riz importé',
  'Rice (local)': 'Riz local',
  'Groundnuts (shelled)': 'Arachide décortiquée',
  'Beans (niebe)': 'Niébé (haricot)',
  'Sesame': 'Sésame',
  'Onions (red)': 'Oignon rouge',
  'Sugar': 'Sucre',
  'Pasta': 'Pâtes alimentaires',
  'Sweet potatoes': 'Patate douce',
  'Fish (dry)': 'Poisson séché',
  'Salt': 'Sel',
  'Garlic': 'Ail',
  'Dates': 'Dattes',
  'Tomatoes (dried)': 'Tomates séchées',
  'Okra (dry)': 'Gombo sec',
  'Wheat flour': 'Farine de blé',
  'Groundnut Oil (Refined)': "Huile d'arachide raffinée",
  'Cassava (cossette)': 'Manioc (cossettes)',
  'Cassava Chips': 'Manioc (cossettes)',
  'Beans (niebe, red)': 'Niébé rouge',
  'Cowpeas (Red)': 'Niébé rouge',
  'Cowpeas (White)': 'Niébé blanc',
  'Onions': 'Oignon',
  'Pasta (Mixed)': 'Pâtes alimentaires (mélange)',
  'Macaroni': 'Macaroni',
  'Peanut': 'Arachide',
  'Spaghetti': 'Spaghetti',
  'Wheat': 'Blé',
  'Sesame (White)': 'Sésame blanc',
  'Refined sugar': 'Sucre raffiné',
  'Rice (Milled)': 'Riz décortiqué',
  'Sorghum (Berbere)': 'Sorgho berbéré',
  'Sorghum (White)': 'Sorgho blanc',
  'Cowpeas (Mixed)': 'Niébé (mélange)',
};

/// Traduit un code produit backend (`commodity_std`) en libellé français lisible.
String commodityLabelFr(String commodityStd) {
  return commodityNamesFr[commodityStd] ?? commodityStd;
}

