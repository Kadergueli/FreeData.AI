import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
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
  String? _authToken;
  Map<String, dynamic>? _authUser;
  bool _subscriptionIsPro = false;

  /// Appelé quand le serveur refuse la clé PRO (403) : l'interface doit se mettre à jour.
  Future<void> Function()? onPremiumKeyRejected;

  /// Appelé quand le serveur renvoie 401 sur une session Bearer active (jeton expiré ou révoqué).
  Future<void> Function()? onAuthSessionExpired;

  void _notifyIfSessionExpired(int statusCode) {
    if (statusCode == 401 && _authToken != null && _authToken!.isNotEmpty) {
      clearAuthSession();
      final cb = onAuthSessionExpired;
      if (cb != null) {
        unawaited(cb());
      }
    }
  }

  // Identifiant d'espace : aléatoire et propre à ce navigateur (un identifiant partagé donnerait les mêmes projets à tous).
  String _userId = generateUserId();
  Future<Map<String, dynamic>>? _metadataCache;
  DateTime? _metadataCachedAt;

  ApiService({http.Client? client}) : _client = client ?? http.Client();

  String get activePremiumKey => _runtimePremiumKey?.trim() ?? '';

  bool get hasPremiumKey => activePremiumKey.isNotEmpty || _subscriptionIsPro;

  bool get hasExplicitPremiumKey => activePremiumKey.isNotEmpty;

  bool get hasSubscriptionPro => _subscriptionIsPro;

  String? get authToken => _authToken;

  bool get isAuthenticated => (_authToken?.isNotEmpty ?? false);

  Map<String, dynamic>? get authUser => _authUser;

  String get userId => _userId;

  static String generateUserId() {
    final rnd = Random.secure();
    final bytes = List<int>.generate(16, (_) => rnd.nextInt(256));
    return 'u${bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join()}';
  }

  static bool isStrongUserId(String id) =>
      RegExp(r'^[A-Za-z0-9_-]{32,80}$').hasMatch(id.trim());

  /// Retourne false (sans rien changer) si l'identifiant est trop faible pour être accepté par l'API.
  bool setUserId(String id) {
    final cleaned = id.trim();
    if (!isStrongUserId(cleaned)) return false;
    _userId = cleaned;
    return true;
  }

  void setAuthSession({
    String? token,
    Map<String, dynamic>? user,
    bool? isPro,
  }) {
    final cleanTok = (token ?? '').trim();
    _authToken = cleanTok.isEmpty ? null : cleanTok;
    _authUser = user;
    if (isPro != null) _subscriptionIsPro = isPro;
    final uid = user?['user_id']?.toString().trim() ?? '';
    if (isStrongUserId(uid)) {
      _userId = uid;
    }
  }

  void clearAuthSession() {
    _authToken = null;
    _authUser = null;
    _subscriptionIsPro = false;
  }

  Map<String, String> _projectHeaders({bool includeJson = false}) {
    final hasBearer = _authToken != null && _authToken!.isNotEmpty;
    return <String, String>{
      if (!hasBearer) 'X-User-Id': _userId,
      if (includeJson) 'Content-Type': 'application/json',
      if (activePremiumKey.isNotEmpty) 'X-Premium-Key': activePremiumKey,
      if (hasBearer) 'Authorization': 'Bearer $_authToken',
    };
  }

  Map<String, String> _proReadHeaders() {
    return <String, String>{
      if (activePremiumKey.isNotEmpty) 'X-Premium-Key': activePremiumKey,
      if (_authToken != null && _authToken!.isNotEmpty)
        'Authorization': 'Bearer $_authToken',
    };
  }

  static String _cleanKey(String? key) {
    return (key ?? '')
        .trim()
        .replaceAll(RegExp(r'^["\x27]+|["\x27]+$'), '')
        .trim();
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
        _notifyIfSessionExpired(resp.statusCode);
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

  Future<Map<String, dynamic>> sendPlatformChatMessage(
    String message, {
    String? domain,
    List<Map<String, String>> history = const [],
    String tier = 'free',
    Map<String, dynamic>? studyContext,
    String? projectId,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/platform/chat');
    final body = jsonEncode({
      'message': message,
      if (domain != null && domain.isNotEmpty) 'domain': domain,
      if (history.isNotEmpty) 'history': history,
      'tier': tier,
      if (studyContext != null) 'study_context': studyContext,
      if (projectId != null && projectId.trim().isNotEmpty)
        'project_id': projectId.trim(),
    });
    final resp = await _client
        .post(uri, headers: _projectHeaders(includeJson: true), body: body)
        .timeout(const Duration(seconds: 45));
    if (resp.statusCode == 200) {
      return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    }
    if (resp.statusCode == 429) {
      throw const ApiHttpException(
          429, 'Quota journalier ou limite de requêtes atteint (429).');
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur API Plateforme (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> sendChatMessage(
    String message, {
    List<Map<String, String>> history = const [],
    String tier = 'free',
    Map<String, dynamic>? studyContext,
    String? projectId,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/chat');
    final body = jsonEncode({
      'message': message,
      if (history.isNotEmpty) 'history': history,
      'tier': tier,
      if (studyContext != null) 'study_context': studyContext,
      if (projectId != null && projectId.trim().isNotEmpty)
        'project_id': projectId.trim(),
    });
    final headers = _projectHeaders(includeJson: true);

    for (var attempt = 0; attempt < 2; attempt++) {
      try {
        final resp = await _client
            .post(
              uri,
              headers: headers,
              body: body,
            )
            .timeout(const Duration(seconds: 45));

        if (resp.statusCode == 200) {
          return jsonDecode(utf8.decode(resp.bodyBytes))
              as Map<String, dynamic>;
        }
        if (resp.statusCode == 429) {
          throw const ApiHttpException(
            429,
            'Trop de requêtes envoyées (429). Réessayez dans une minute.',
          );
        }
        if (attempt == 0 &&
            (resp.statusCode == 502 ||
                resp.statusCode == 503 ||
                resp.statusCode == 504)) {
          await Future.delayed(const Duration(seconds: 2));
          continue;
        }
        throw ApiHttpException(
            resp.statusCode, 'Erreur API Chat (${resp.statusCode})');
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
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement métadonnées (${resp.statusCode})');
  }

  Future<List<dynamic>> getForecasts(
      {String? province, String? commodity}) async {
    final params = <String, String>{};
    if (province != null && province.isNotEmpty) params['province'] = province;
    if (commodity != null && commodity.isNotEmpty)
      params['commodity'] = commodity;
    final uri =
        Uri.parse('$baseUrl/api/v1/forecasts').replace(queryParameters: params);
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      final data =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement prévisions (${resp.statusCode})');
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
    final uri =
        Uri.parse('$baseUrl/api/v1/alerts').replace(queryParameters: params);
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      final data =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement alertes (${resp.statusCode})');
  }

  Future<List<dynamic>> getAnomalies({
    String? province,
    String? commodity,
    String? kind,
    String? severity,
    int limit = 100,
  }) async {
    final params = <String, String>{
      'limit': limit.toString(),
      if (province != null && province.isNotEmpty) 'province': province,
      if (commodity != null && commodity.isNotEmpty) 'commodity': commodity,
      if (kind != null && kind.isNotEmpty) 'kind': kind,
      if (severity != null && severity.isNotEmpty) 'severity': severity,
    };
    final uri =
        Uri.parse('$baseUrl/api/v1/anomalies').replace(queryParameters: params);
    // L'API réserve ce radar à l'offre premium : la clé ou la session Bearer doit être envoyée.
    final headers = _proReadHeaders();
    final resp = await _getWithRetry(
      uri,
      headers: headers.isEmpty ? null : headers,
    );
    if (resp.statusCode == 200) {
      final data =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement anomalies (${resp.statusCode})');
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
    final headers = _proReadHeaders();
    final resp = await _getWithRetry(
      uri,
      headers: headers.isEmpty ? null : headers,
    );
    if (resp.statusCode == 200) {
      return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    }
    if (resp.statusCode == 403) {
      _runtimePremiumKey = null;
      final cb = onPremiumKeyRejected;
      if (cb != null) {
        cb();
      }
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
    if (commodity != null && commodity.isNotEmpty)
      params['commodity'] = commodity;
    final uri = Uri.parse('$baseUrl/api/v1/credit-passport')
        .replace(queryParameters: params);
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      final data =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw ApiHttpException(resp.statusCode,
        'Erreur chargement Credit Passport (${resp.statusCode})');
  }

  Future<Uint8List> downloadMarketStudyPdf({
    required String commodity,
    required String originProvince,
    String? destProvince,
    required double capitalXaf,
    double? transportCostPerKg,
    String? promoterName,
    List<String> userInstructions = const [],
    Map<String, dynamic>? studyContext,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/reports/market-study/pdf');
    final body = <String, dynamic>{
      'commodity': commodity,
      'origin_province': originProvince,
      if (destProvince != null && destProvince.isNotEmpty)
        'dest_province': destProvince,
      'capital_xaf': capitalXaf,
      if (transportCostPerKg != null)
        'transport_cost_per_kg': transportCostPerKg,
      if (promoterName != null && promoterName.trim().isNotEmpty)
        'promoter_name': promoterName.trim(),
      'user_instructions': userInstructions,
      if (studyContext != null) 'study_context': studyContext,
    };
    final headers = _projectHeaders(includeJson: true);
    final resp = await _client
        .post(uri, headers: headers, body: jsonEncode(body))
        .timeout(const Duration(seconds: 45));
    if (resp.statusCode == 200) {
      return resp.bodyBytes;
    }
    if (resp.statusCode == 403 || resp.statusCode == 503) {
      throw ApiHttpException(
          resp.statusCode, 'Accès Partenaire PRO requis pour générer le PDF.');
    }
    if (resp.statusCode == 422) {
      try {
        final decoded = jsonDecode(utf8.decode(resp.bodyBytes));
        final detail = decoded is Map ? decoded['detail'] : null;
        if (detail is Map && detail['validation'] is Map) {
          final corr = (detail['validation']['required_corrections'] as List?)
                  ?.join(' ; ') ??
              '';
          throw ApiHttpException(
              422,
              corr.isNotEmpty
                  ? 'Validation QA échouée : $corr'
                  : 'Validation QA du rapport échouée.');
        }
      } catch (e) {
        if (e is ApiHttpException) rethrow;
      }
      throw ApiHttpException(422, 'Validation QA du rapport échouée (422).');
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur génération PDF (${resp.statusCode})');
  }

  Future<List<Map<String, dynamic>>> listProjects(
      {bool includeArchived = false}) async {
    final uri =
        Uri.parse('$baseUrl/api/v1/projects?include_archived=$includeArchived');
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      final list = decoded['projects'] as List? ?? [];
      return list.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement projets (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> createProject({
    required String name,
    String description = '',
    Map<String, dynamic>? studyContext,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/projects');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'name': name,
            'description': description,
            if (studyContext != null) 'study_context': studyContext,
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur création projet (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getProject(String projectId) async {
    final uri = Uri.parse('$baseUrl/api/v1/projects/$projectId');
    final resp = await _client
        .get(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Projet introuvable (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> updateProject(
    String projectId, {
    String? name,
    String? description,
    String? status,
    Map<String, dynamic>? studyContext,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/projects/$projectId');
    final resp = await _client
        .patch(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            if (name != null) 'name': name,
            if (description != null) 'description': description,
            if (status != null) 'status': status,
            if (studyContext != null) 'study_context': studyContext,
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur mise à jour projet (${resp.statusCode})');
  }

  Future<void> deleteProject(String projectId) async {
    final uri = Uri.parse('$baseUrl/api/v1/projects/$projectId?confirm=true');
    final resp = await _client
        .delete(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      throw ApiHttpException(
          resp.statusCode, 'Erreur suppression projet (${resp.statusCode})');
    }
  }

  Future<Map<String, dynamic>> createProjectStudy(
    String projectId, {
    required String commodity,
    required String originProvince,
    String? destProvince,
    required double capitalXaf,
    String? promoterName,
    String? studyId,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/projects/$projectId/studies');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            if (studyId != null && studyId.trim().isNotEmpty)
              'study_id': studyId.trim(),
            'commodity': commodity,
            'origin_province': originProvince,
            if (destProvince != null && destProvince.trim().isNotEmpty)
              'dest_province': destProvince.trim(),
            'capital_xaf': capitalXaf,
            if (promoterName != null && promoterName.trim().isNotEmpty)
              'promoter_name': promoterName.trim(),
          }),
        )
        .timeout(const Duration(seconds: 45));
    if (resp.statusCode == 200 || resp.statusCode == 201) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur génération étude projet (${resp.statusCode})');
  }

  Future<List<Map<String, dynamic>>> listStudyVersions(
      String projectId, String studyId) async {
    final uri = Uri.parse(
        '$baseUrl/api/v1/projects/$projectId/studies/$studyId/versions');
    final resp = await _client
        .get(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      final list = decoded['versions'] as List? ?? [];
      return list.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement versions (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> compareStudyVersions(
      String projectId, String studyId, int v1, int v2) async {
    final uri = Uri.parse(
        '$baseUrl/api/v1/projects/$projectId/studies/$studyId/compare?v1=$v1&v2=$v2');
    final resp = await _client
        .get(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur comparaison versions (${resp.statusCode})');
  }

  Future<Uint8List> downloadStudyVersionPdf(
      String projectId, String studyId, int versionNumber) async {
    final uri = Uri.parse(
        '$baseUrl/api/v1/projects/$projectId/studies/$studyId/versions/$versionNumber/pdf');
    final resp = await _client
        .get(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 45));
    if (resp.statusCode == 200) {
      return resp.bodyBytes;
    }
    throw ApiHttpException(resp.statusCode,
        'Erreur téléchargement PDF version $versionNumber (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getAnalyticsProfile() async {
    final uri = Uri.parse('$baseUrl/api/v1/analytics/profile');
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur profil analytique (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getAnalyticsSummary(
      {String? commodity, String? province}) async {
    final q = <String, String>{
      if (commodity != null && commodity.isNotEmpty) 'commodity': commodity,
      if (province != null && province.isNotEmpty) 'province': province,
    };
    final uri = Uri.parse('$baseUrl/api/v1/analytics/summary')
        .replace(queryParameters: q.isEmpty ? null : q);
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur résumé analytique (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getRegionalComparison(
      {String? commodity}) async {
    final q = <String, String>{
      if (commodity != null && commodity.isNotEmpty) 'commodity': commodity,
    };
    final uri = Uri.parse('$baseUrl/api/v1/analytics/regional-comparison')
        .replace(queryParameters: q.isEmpty ? null : q);
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur comparaison régionale (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getAnalyticsTrends(
      {String? commodity, String? province, int limit = 24}) async {
    final q = <String, String>{
      if (commodity != null && commodity.isNotEmpty) 'commodity': commodity,
      if (province != null && province.isNotEmpty) 'province': province,
      'limit': '$limit',
    };
    final uri = Uri.parse('$baseUrl/api/v1/analytics/trends')
        .replace(queryParameters: q);
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur tendances historiques (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getForecastBenchmark({
    required String commodity,
    required String province,
  }) async {
    final uri =
        Uri.parse('$baseUrl/api/v1/analytics/forecast-benchmark').replace(
      queryParameters: {
        'commodity': commodity.trim(),
        'province': province.trim()
      },
    );
    final resp = await _client.get(uri).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur benchmark modèle (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getBillingPlans() async {
    final uri = Uri.parse('$baseUrl/api/v1/billing/plans');
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement plans (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getMyBilling() async {
    final uri = Uri.parse('$baseUrl/api/v1/billing/me');
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      final sub = data['subscription'];
      final effPlan = sub is Map ? sub['effective_plan_id']?.toString() : null;
      _subscriptionIsPro =
          data['is_pro'] == true || effPlan == 'premium' || effPlan == 'trial';
      return data;
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement abonnement (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getAdminMe(String adminToken) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/me');
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim()
    }).timeout(const Duration(seconds: 15));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Accès admin refusé (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getAdminOverview(String adminToken,
      {bool liveProbe = false}) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/overview').replace(
      queryParameters: liveProbe ? const {'live_probe': 'true'} : null,
    );
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim()
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Accès admin refusé (${resp.statusCode})');
  }

  Future<void> setAdminUserStatus(
      String adminToken, String userId, String status) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/users/$userId/status');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json'
          },
          body: jsonEncode(
              {'status': status, 'reason': 'Admin dashboard action'}),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      throw ApiHttpException(
          resp.statusCode, 'Erreur mise à jour statut (${resp.statusCode})');
    }
  }

  Future<List<Map<String, dynamic>>> getAdminUsers(String adminToken,
      {String search = ''}) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/users').replace(
      queryParameters: {
        if (search.trim().isNotEmpty) 'q': search.trim(),
        'limit': '100',
      },
    );
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim()
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      final list = decoded['users'] as List? ?? [];
      return list.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement utilisateurs (${resp.statusCode})');
  }

  Future<void> activateAdminSubscription(
    String adminToken, {
    required String targetUserId,
    required String planId,
    int periodDays = 30,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/billing/admin/activate');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json'
          },
          body: jsonEncode({
            'target_user_id': targetUserId.trim(),
            'plan_id': planId,
            'status': 'active',
            'period_days': periodDays,
            'reason': 'Admin console activation',
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      throw ApiHttpException(
          resp.statusCode, 'Erreur activation plan (${resp.statusCode})');
    }
  }

  Future<void> toggleAdminModel(
      String adminToken, String profileId, bool enabled) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/models/$profileId');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json'
          },
          body: jsonEncode(
              {'enabled': enabled, 'reason': 'Admin console toggle'}),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      throw ApiHttpException(
          resp.statusCode, 'Erreur bascule modèle (${resp.statusCode})');
    }
  }

  Future<Map<String, dynamic>> triggerAdminBackup(String adminToken) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/backup');
    final resp = await _client.post(uri, headers: {
      'X-Admin-Token': adminToken.trim()
    }).timeout(const Duration(seconds: 30));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur sauvegarde (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> triggerAdminRefreshData(
      String adminToken) async {
    final uri = Uri.parse('$baseUrl/api/v1/refresh');
    final resp = await _client.post(uri, headers: {
      'X-Admin-Token': adminToken.trim()
    }).timeout(const Duration(seconds: 45));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur rechargement données (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> refreshAdminData(String adminToken) async {
    final uri = Uri.parse('$baseUrl/api/v1/refresh');
    final resp = await _client.post(uri, headers: {
      'X-Admin-Token': adminToken.trim()
    }).timeout(const Duration(seconds: 30));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur rafraîchissement (${resp.statusCode})');
  }

  Future<List<Map<String, dynamic>>> getAdminSupportTickets(
      String adminToken) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/support/tickets?limit=50');
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim()
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      final list = decoded['tickets'] as List? ?? [];
      return list.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement tickets (${resp.statusCode})');
  }

  Future<void> updateAdminTicketStatus(
      String adminToken, String ticketId, String status) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/support/tickets/$ticketId');
    final resp = await _client
        .patch(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json'
          },
          body: jsonEncode({'status': status}),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      throw ApiHttpException(
          resp.statusCode, 'Erreur mise à jour ticket (${resp.statusCode})');
    }
  }

  Future<Map<String, dynamic>> createSupportTicket({
    required String category,
    required String subject,
    required String description,
    String priority = 'normal',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/support/tickets');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'category': category,
            'subject': subject,
            'description': description,
            'priority': priority
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur envoi ticket (${resp.statusCode})');
  }

  Future<List<Map<String, dynamic>>> listMyTickets() async {
    final uri = Uri.parse('$baseUrl/api/v1/support/tickets');
    final resp = await _client
        .get(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return (decoded['tickets'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
    }
    throw ApiHttpException(
        resp.statusCode, 'Erreur chargement tickets (${resp.statusCode})');
  }

  Future<void> submitFeedback({
    required String feature,
    required int rating,
    String comment = '',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/feedback');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode(
              {'feature': feature, 'rating': rating, 'comment': comment}),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      throw ApiHttpException(
          resp.statusCode, 'Erreur envoi avis (${resp.statusCode})');
    }
  }

  String _extractErrorDetail(http.Response resp, String fallback) {
    _notifyIfSessionExpired(resp.statusCode);
    try {
      final decoded = jsonDecode(utf8.decode(resp.bodyBytes));
      if (decoded is Map &&
          decoded['detail'] is String &&
          (decoded['detail'] as String).trim().isNotEmpty) {
        return (decoded['detail'] as String).trim();
      }
    } catch (_) {}
    return '$fallback (${resp.statusCode})';
  }

  // --- Comptes utilisateurs (JWT Bearer) -----------------------------------

  Future<Map<String, dynamic>> registerAccount({
    required String email,
    required String password,
    String displayName = '',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/register');
    final resp = await _client
        .post(
          uri,
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'email': email.trim(),
            'password': password,
            'display_name': displayName.trim(),
          }),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      setAuthSession(
        token: data['token']?.toString(),
        user: data['user'] is Map
            ? Map<String, dynamic>.from(data['user'] as Map)
            : null,
        isPro: false,
      );
      return data;
    }
    throw ApiHttpException(
        resp.statusCode, _extractErrorDetail(resp, 'Inscription impossible'));
  }

  Future<Map<String, dynamic>> loginAccount({
    required String email,
    required String password,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/login');
    final resp = await _client
        .post(
          uri,
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'email': email.trim(), 'password': password}),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      setAuthSession(
        token: data['token']?.toString(),
        user: data['user'] is Map
            ? Map<String, dynamic>.from(data['user'] as Map)
            : null,
      );
      try {
        final me = await getAuthMe();
        _subscriptionIsPro = me['is_pro'] == true;
      } catch (_) {}
      return data;
    }
    throw ApiHttpException(
        resp.statusCode, _extractErrorDetail(resp, 'Connexion impossible'));
  }

  Future<Map<String, dynamic>> getAuthMe() async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/me');
    final resp = await _client
        .get(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      setAuthSession(
        token: _authToken,
        user: data['user'] is Map
            ? Map<String, dynamic>.from(data['user'] as Map)
            : null,
        isPro: data['is_pro'] == true,
      );
      return data;
    }
    _notifyIfSessionExpired(resp.statusCode);
    throw ApiHttpException(
        resp.statusCode, _extractErrorDetail(resp, 'Session invalide'));
  }

  Future<Map<String, dynamic>> refreshAuthSession() async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/refresh');
    final resp = await _client
        .post(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      setAuthSession(
        token: data['token']?.toString(),
        user: data['user'] is Map
            ? Map<String, dynamic>.from(data['user'] as Map)
            : _authUser,
      );
      return data;
    }
    _notifyIfSessionExpired(resp.statusCode);
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Renouvellement de session impossible'));
  }

  Future<void> logoutAccount() async {
    final tok = _authToken;
    clearAuthSession();
    if (tok == null || tok.isEmpty) return;
    try {
      final uri = Uri.parse('$baseUrl/api/v1/auth/logout');
      await _client.post(uri, headers: {
        'Authorization': 'Bearer $tok'
      }).timeout(const Duration(seconds: 15));
    } catch (_) {}
  }

  Future<Map<String, dynamic>> updateProfile(
      {required String displayName}) async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/profile');
    final resp = await _client
        .patch(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({'display_name': displayName.trim()}),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      if (data['user'] is Map) {
        _authUser = Map<String, dynamic>.from(data['user'] as Map);
      }
      return data;
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Mise à jour profil impossible'));
  }

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/change-password');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'current_password': currentPassword,
            'new_password': newPassword,
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      throw ApiHttpException(resp.statusCode,
          _extractErrorDetail(resp, 'Changement de mot de passe refusé'));
    }
  }

  Future<void> deleteAccount({required String password}) async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/delete-account');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({'password': password}),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      clearAuthSession();
      return;
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Suppression du compte refusée'));
  }

  Future<Map<String, dynamic>> exportMyPrivacyData() async {
    final uri = Uri.parse('$baseUrl/api/v1/privacy/export');
    final resp = await _client
        .get(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, _extractErrorDetail(resp, 'Export RGPD impossible'));
  }

  // --- Synchronisation cloud des conversations (multi-appareils) -----------

  Future<List<Map<String, dynamic>>> syncCloudConversations(
      List<Map<String, dynamic>> conversations) async {
    final uri = Uri.parse('$baseUrl/api/v1/conversations/sync');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({'conversations': conversations}),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return (decoded['conversations'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
    }
    throw ApiHttpException(
        resp.statusCode, _extractErrorDetail(resp, 'Synchro cloud impossible'));
  }

  Future<void> upsertCloudConversation(
      Map<String, dynamic> conversation) async {
    final id = conversation['id']?.toString().trim() ?? '';
    if (id.isEmpty) return;
    final uri = Uri.parse('$baseUrl/api/v1/conversations/$id');
    await _client
        .put(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode(conversation),
        )
        .timeout(const Duration(seconds: 20));
  }

  Future<void> deleteCloudConversation(String conversationId) async {
    final uri = Uri.parse('$baseUrl/api/v1/conversations/$conversationId');
    await _client
        .delete(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
  }

  // --- Monétisation & Paiements PRO (Mobile Money + Stripe) ----------------

  Future<Map<String, dynamic>> getPaymentMethods() async {
    final uri = Uri.parse('$baseUrl/api/v1/billing/payment-methods');
    final resp = await _client.get(uri).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur méthodes de paiement'));
  }

  Future<Map<String, dynamic>> createPaymentRequest({
    required String provider,
    required String phoneOrRef,
    required String transactionRef,
    String planId = 'premium',
    int amountXaf = 0,
    String note = '',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/billing/payment-requests');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'provider': provider,
            'plan_id': planId,
            'phone_or_ref': phoneOrRef.trim(),
            'transaction_ref': transactionRef.trim(),
            'amount_xaf': amountXaf,
            'note': note.trim(),
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur soumission paiement'));
  }

  Future<List<Map<String, dynamic>>> listMyPaymentRequests() async {
    final uri = Uri.parse('$baseUrl/api/v1/billing/payment-requests/me');
    final resp = await _client
        .get(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return (decoded['requests'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur chargement paiements'));
  }

  Future<List<Map<String, dynamic>>> getAdminPaymentRequests(String adminToken,
      {String? status}) async {
    final uri =
        Uri.parse('$baseUrl/api/v1/admin/billing/payment-requests').replace(
      queryParameters: {
        if (status != null && status.isNotEmpty) 'status': status,
        'limit': '100',
      },
    );
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim()
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return (decoded['requests'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
    }
    throw ApiHttpException(
        resp.statusCode, _extractErrorDetail(resp, 'Erreur paiements admin'));
  }

  Future<Map<String, dynamic>> reviewAdminPaymentRequest(
    String adminToken,
    String requestId, {
    required String decision,
    int periodDays = 30,
    String note = '',
  }) async {
    final uri = Uri.parse(
        '$baseUrl/api/v1/admin/billing/payment-requests/$requestId/review');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json'
          },
          body: jsonEncode({
            'decision': decision,
            'period_days': periodDays,
            'note': note.trim(),
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur validation paiement'));
  }

  // --- Coffre-fort de documents privés (Jina Embeddings v3 + RAG isolé) ----

  Future<Map<String, dynamic>> uploadUserDocument({
    required String filename,
    required Uint8List bytes,
    String? mimeType,
    String? projectId,
    int chunkOffset = 0,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/documents/upload');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'filename': filename.trim(),
            'content_base64': base64Encode(bytes),
            if (mimeType != null && mimeType.trim().isNotEmpty)
              'mime_type': mimeType.trim(),
            if (projectId != null && projectId.trim().isNotEmpty)
              'project_id': projectId.trim(),
            if (chunkOffset > 0) 'chunk_offset': chunkOffset,
          }),
        )
        .timeout(const Duration(seconds: 40));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Téléversement du document impossible'));
  }

  Future<List<Map<String, dynamic>>> listUserDocuments(
      {String? projectId}) async {
    final uri = Uri.parse('$baseUrl/api/v1/documents').replace(
      queryParameters: (projectId != null && projectId.trim().isNotEmpty)
          ? {'project_id': projectId.trim()}
          : null,
    );
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return (decoded['documents'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur chargement documents'));
  }

  Future<void> deleteUserDocument(String docId) async {
    final uri = Uri.parse('$baseUrl/api/v1/documents/$docId');
    final resp = await _client
        .delete(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      throw ApiHttpException(resp.statusCode,
          _extractErrorDetail(resp, 'Suppression du document impossible'));
    }
  }
}
