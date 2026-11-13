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

