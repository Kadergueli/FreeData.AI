import 'dart:async';

import '../../services/api_service.dart';

const String _genericError = 'Une erreur est survenue. Réessayez.';

bool _looksLikeNetworkError(String text) {
  return text.contains('ClientException') ||
      text.contains('SocketException') ||
      text.contains('Failed to fetch');
}

bool _looksTechnical(String text) {
  return text.contains('http://') ||
      text.contains('https://') ||
      text.contains('Instance of') ||
      text.contains('is not a subtype');
}

/// Transforme une erreur technique en message lisible pour l'utilisateur.
String errText(Object error) {
  if (error is ApiHttpException) return error.message;
  if (error is TimeoutException) {
    return 'Le serveur met trop de temps à répondre. Réessayez.';
  }
  if (error is FormatException) {
    return 'Réponse inattendue du serveur. Réessayez.';
  }
  final text = error.toString().replaceFirst('Exception: ', '').trim();
  if (_looksLikeNetworkError(text)) {
    return 'Connexion impossible. Vérifiez votre réseau.';
  }
  if (text.isEmpty || _looksTechnical(text)) return _genericError;
  return text;
}
