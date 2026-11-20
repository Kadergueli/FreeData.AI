// ignore: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:html' as html;

/// Ouvre un lien dans un nouvel onglet, uniquement pour http(s) (jamais javascript:, data:, etc.).
/// `noopener,noreferrer` empêche la page ouverte d'accéder à l'application ou à son origine.
bool openExternalUrl(String? href) {
  final uri = Uri.tryParse((href ?? '').trim());
  if (uri == null || !(uri.scheme == 'https' || uri.scheme == 'http') || uri.host.isEmpty) {
    return false;
  }
  html.window.open(uri.toString(), '_blank', 'noopener,noreferrer');
  return true;
}
