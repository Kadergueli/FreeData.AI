import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:freedata_ai/core/utils/error_text.dart';
import 'package:freedata_ai/services/api_service.dart';

void main() {
  const generic = 'Une erreur est survenue. Réessayez.';

  test('errText keeps readable API messages', () {
    const error = ApiHttpException(403, 'Accès refusé');
    expect(errText(error), 'Accès refusé');
  });

  test('errText hides network internals', () {
    final error = Exception('ClientException: Failed to fetch, uri=x');
    expect(errText(error), 'Connexion impossible. Vérifiez votre réseau.');
  });

  test('errText translates timeouts and format errors', () {
    expect(errText(TimeoutException('x')), contains('trop de temps'));
    expect(errText(const FormatException('bad')), contains('inattendue'));
  });

  test('errText never leaks URLs or type errors', () {
    final urlError = Exception('GET https://api.example.com 500');
    final typeError = StateError("type 'Null' is not a subtype of String");
    expect(errText(urlError), generic);
    expect(errText(typeError), generic);
  });

  test('errText strips the Exception prefix', () {
    expect(errText(Exception('Surface requise')), 'Surface requise');
  });
}
