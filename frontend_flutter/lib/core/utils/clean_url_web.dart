// ignore: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:html' as html;

/// Retire de la barre d'adresse les paramètres sensibles (clé PRO) sans recharger la page.
void removeSensitiveQueryParams(List<String> names) {
  final uri = Uri.parse(html.window.location.href);
  if (!names.any(uri.queryParameters.containsKey)) return;
  final kept = Map<String, String>.from(uri.queryParameters)
    ..removeWhere((key, _) => names.contains(key));
  final query = kept.isEmpty ? '' : '?${Uri(queryParameters: kept).query}';
  final fragment = uri.hasFragment ? '#${uri.fragment}' : '';
  html.window.history.replaceState(null, '', '${uri.path}$query$fragment');
}
