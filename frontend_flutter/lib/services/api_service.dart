import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiHttpException implements Exception {
  final int statusCode;
  final String message;

  const ApiHttpException(this.statusCode, this.message);

  @override
  String toString() => message;
}

class ApiService {
  // Remplacer en production via --dart-define=API_BASE_URL=https://votre-api.onrender.com
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://freedata-ai.onrender.com',
  );

  static const Duration _metadataCacheTtl = Duration(minutes: 5);

  final http.Client _client;
  String? _runtimePremiumKey;
  Future<Map<String, dynamic>>? _metadataCache;
  DateTime? _metadataCachedAt;

  ApiService({http.Client? client}) : _client = client ?? http.Client();

  String get activePremiumKey => _runtimePremiumKey?.trim() ?? '';

  bool get hasPremiumKey => activePremiumKey.isNotEmpty;

  static String _cleanKey(String? key) {
    return (key ?? '').trim().replaceAll(RegExp(r'^["\x27]+|["\x27]+$'), '').trim();
  }

  void setRuntimePremiumKey(String? key) {
    final cleaned = _cleanKey(key);
    _runtimePremiumKey = cleaned.isEmpty ? null : cleaned;
  }

  Future<http.Response> _getWithRetry(
    Uri uri, {
    Map<String, String>? headers,
    bool retryOn503 = true,
  }) async {
    for (var attempt = 0; attempt < 2; attempt++) {
      try {
        final resp = await _client
            .get(uri, headers: headers)
            .timeout(const Duration(seconds: 25));
        if (attempt == 0 &&
            (resp.statusCode == 502 ||
                resp.statusCode == 504 ||
                (retryOn503 &&
                    resp.statusCode == 503 &&
                    !utf8
                        .decode(resp.bodyBytes, allowMalformed: true)
                        .contains('PREMIUM_API_KEYS')))) {
          await Future.delayed(const Duration(seconds: 2));
          continue;
        }
        return resp;
      } on TimeoutException {
        if (attempt == 0) continue;
        rethrow;
      } catch (e) {
        if (e is ApiHttpException || e is FormatException) {
          rethrow;
        }
        if (attempt == 0) {
          await Future.delayed(const Duration(seconds: 2));
          continue;
        }
        rethrow;
      }
    }
    throw Exception('Impossible de joindre le serveur.');
  }

  Future<bool> verifyPremiumKey(String candidateKey) async {
    final trimmed = _cleanKey(candidateKey);
    if (trimmed.isEmpty) return false;
    final uri = Uri.parse('$baseUrl/api/v1/studies/seasonality').replace(
      queryParameters: const {
        'commodity': 'Millet',
        'format': 'json',
      },
    );
    final resp = await _getWithRetry(
      uri,
      headers: {'X-Premium-Key': trimmed},
    );
    if (resp.statusCode == 200 || resp.statusCode == 404) {
      return true;
    }
    if (resp.statusCode == 403 || resp.statusCode == 401) {
      return false;
    }
    if (resp.statusCode == 503) {
      throw const ApiHttpException(
        503,
        'Les études avancées (PREMIUM_API_KEYS) ne sont pas activées sur ce serveur.',
      );
    }
    throw ApiHttpException(
      resp.statusCode,
      'Impossible de vérifier la clé auprès du serveur (${resp.statusCode}).',
    );
  }

  Future<Map<String, dynamic>> sendChatMessage(
    String message, {
    List<Map<String, String>> history = const [],
    String tier = 'free',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/chat');
    final body = jsonEncode({
      'message': message,
      if (history.isNotEmpty) 'history': history,
      'tier': tier,
    });
    final headers = <String, String>{
      'Content-Type': 'application/json',
      if (hasPremiumKey) 'X-Premium-Key': activePremiumKey,
    };

    for (var attempt = 0; attempt < 2; attempt++) {
      try {
        final resp = await _client
            .post(
              uri,
              headers: headers,
              body: body,
            )
            .timeout(const Duration(seconds: 20));

        if (resp.statusCode == 200) {
          return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
        }
        if (resp.statusCode == 429) {
          throw const ApiHttpException(
            429,
            'Trop de requêtes envoyées (429). Réessayez dans une minute.',
          );
        }
        if (attempt == 0 && (resp.statusCode == 502 || resp.statusCode == 503 || resp.statusCode == 504)) {
          await Future.delayed(const Duration(seconds: 2));
          continue;
        }
        throw ApiHttpException(resp.statusCode, 'Erreur API Chat (${resp.statusCode})');
      } on TimeoutException {
        if (attempt == 0) continue;
        rethrow;
      } catch (e) {
        if (e is ApiHttpException || e is FormatException) {
          rethrow;
        }
        if (attempt == 0) {
          await Future.delayed(const Duration(seconds: 2));
          continue;
        }
        rethrow;
      }
    }
    throw Exception('Impossible de joindre le serveur.');
  }

  void invalidateMetadataCache() {
    _metadataCache = null;
    _metadataCachedAt = null;
  }

  Future<Map<String, dynamic>> getMetadata() {
    final now = DateTime.now();
    if (_metadataCache != null &&
        _metadataCachedAt != null &&
        now.difference(_metadataCachedAt!) < _metadataCacheTtl) {
      return _metadataCache!;
    }

    _metadataCachedAt = now;
    final future = _fetchMetadata().catchError((Object err, StackTrace st) {
      _metadataCache = null;
      _metadataCachedAt = null;
      Error.throwWithStackTrace(err, st);
    });
    _metadataCache = future;
    return future;
  }

  Future<Map<String, dynamic>> _fetchMetadata() async {
    final uri = Uri.parse('$baseUrl/api/v1/metadata');
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    }
    throw ApiHttpException(resp.statusCode, 'Erreur chargement métadonnées (${resp.statusCode})');
  }

  Future<List<dynamic>> getForecasts({String? province, String? commodity}) async {
    final params = <String, String>{};
    if (province != null && province.isNotEmpty) params['province'] = province;
    if (commodity != null && commodity.isNotEmpty) params['commodity'] = commodity;
    final uri = Uri.parse('$baseUrl/api/v1/forecasts').replace(queryParameters: params);
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw ApiHttpException(resp.statusCode, 'Erreur chargement prévisions (${resp.statusCode})');
  }

  Future<List<dynamic>> getAlerts({
    double thresholdPct = 15.0,
    String? province,
    String? commodity,
  }) async {
    final params = <String, String>{
      'threshold_pct': thresholdPct.toString(),
      if (province != null && province.isNotEmpty) 'province': province,
      if (commodity != null && commodity.isNotEmpty) 'commodity': commodity,
    };
    final uri = Uri.parse('$baseUrl/api/v1/alerts').replace(queryParameters: params);
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw ApiHttpException(resp.statusCode, 'Erreur chargement alertes (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getSeasonalityStudy({
    required String commodity,
    String? province,
    double? storageCostPctMonth,
  }) async {
    final params = <String, String>{
      'commodity': commodity,
      'format': 'json',
      if (province != null && province.isNotEmpty) 'province': province,
      if (storageCostPctMonth != null)
        'storage_cost_pct_month': storageCostPctMonth.toString(),
    };
    final uri = Uri.parse('$baseUrl/api/v1/studies/seasonality')
        .replace(queryParameters: params);
    final headers = <String, String>{
      if (hasPremiumKey) 'X-Premium-Key': activePremiumKey,
    };
    final resp = await _getWithRetry(
      uri,
      headers: headers.isEmpty ? null : headers,
    );
    if (resp.statusCode == 200) {
      return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    }
    if (resp.statusCode == 403) {
      _runtimePremiumKey = null;
      throw const ApiHttpException(
        403,
        'Clé Premium requise ou invalide pour consulter les études saisonnières.',
      );
    }
    if (resp.statusCode == 503) {
      throw const ApiHttpException(
        503,
        'Les études saisonnières avancées ne sont pas activées sur ce serveur.',
      );
    }
    throw ApiHttpException(
      resp.statusCode,
      'Erreur chargement étude saisonnière (${resp.statusCode})',
    );
  }

  Future<List<dynamic>> getCreditPassports({
    String? province,
    String? commodity,
    int loanAmount = 1000000,
  }) async {
    final params = <String, String>{'loan_amount': loanAmount.toString()};
    if (province != null && province.isNotEmpty) params['province'] = province;
    if (commodity != null && commodity.isNotEmpty) params['commodity'] = commodity;
    final uri = Uri.parse('$baseUrl/api/v1/credit-passport').replace(queryParameters: params);
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw ApiHttpException(resp.statusCode, 'Erreur chargement Credit Passport (${resp.statusCode})');
  }
}
