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

  String get userPersona {
    final p = _authUser?['persona']?.toString().trim().toLowerCase() ?? '';
    return const {'analyste', 'agronome', 'marche', 'banque'}.contains(p)
        ? p
        : 'analyste';
  }

  Set<String> _entitlements = const {'chat', 'explore', 'markets'};
  List<String> _roles = const ['user'];

  Set<String> get entitlements => _entitlements;
  List<String> get roles => _roles;

  bool can(String capability) {
    if (_entitlements.contains(capability)) return true;
    const proCaps = {
      'agro_pdf',
      'credit_passport',
      'projects',
      'ml_studio',
      'watchlists',
    };
    if (proCaps.contains(capability)) return hasPremiumKey;
    return const {'chat', 'explore', 'markets'}.contains(capability);
  }

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

  Map<String, dynamic>? _cachedBillingPlans;
  DateTime? _cachedBillingPlansAt;
  Map<String, dynamic>? _cachedPaymentMethods;
  DateTime? _cachedPaymentMethodsAt;
  Map<String, dynamic>? _cachedMyBilling;
  List<Map<String, dynamic>>? _cachedMyPaymentRequests;

  static const Duration _billingCatalogCacheTtl = Duration(minutes: 5);

  Map<String, dynamic>? get cachedBillingPlans => _cachedBillingPlans;
  Map<String, dynamic>? get cachedPaymentMethods => _cachedPaymentMethods;
  Map<String, dynamic>? get cachedMyBilling => _cachedMyBilling;
  List<Map<String, dynamic>>? get cachedMyPaymentRequests =>
      _cachedMyPaymentRequests;

  void invalidateUserBillingCache() {
    _cachedMyBilling = null;
    _cachedMyPaymentRequests = null;
  }

  /// Précharge silencieusement les métadonnées, le catalogue d'offres et le statut
  /// d'abonnement pour une ouverture instantanée (« tic au tac ») des écrans.
  void prefetchBillingCatalog() {
    getMetadata().catchError((_) => const <String, dynamic>{});
    getBillingPlans().catchError((_) => const <String, dynamic>{});
    getPaymentMethods().catchError((_) => const <String, dynamic>{});
    if (isAuthenticated || hasExplicitPremiumKey) {
      getMyBilling().catchError((_) => const <String, dynamic>{});
      listMyPaymentRequests().catchError((_) => const <Map<String, dynamic>>[]);
    }
  }

  void setAuthSession({
    String? token,
    Map<String, dynamic>? user,
    bool? isPro,
    Iterable<String>? entitlements,
    Iterable<String>? roles,
  }) {
    final cleanTok = (token ?? '').trim();
    final nextTok = cleanTok.isEmpty ? null : cleanTok;
    if (_authToken != nextTok) {
      invalidateUserBillingCache();
    }
    _authToken = nextTok;
    _authUser = user;
    if (isPro != null) _subscriptionIsPro = isPro;
    if (entitlements != null) {
      _entitlements = entitlements.map((e) => e.toString()).toSet();
    } else if (nextTok == null) {
      _entitlements = const {'chat', 'explore', 'markets'};
    }
    if (roles != null) {
      _roles = roles.map((e) => e.toString()).toList();
    } else if (nextTok == null) {
      _roles = const ['user'];
    }
    // L'identifiant du compte n'est plus recopié dans _userId : l'API ne l'accepte qu'avec le jeton Bearer
    // (un X-User-Id seul ne donne accès qu'à un espace anonyme distinct).
  }

  void clearAuthSession() {
    _authToken = null;
    _authUser = null;
    _subscriptionIsPro = false;
    _entitlements = const {'chat', 'explore', 'markets'};
    _roles = const ['user'];
    invalidateUserBillingCache();
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
    _notifyIfSessionExpired(resp.statusCode);
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

  Stream<Map<String, dynamic>> streamChatMessage(
    String message, {
    List<Map<String, String>> history = const [],
    String tier = 'free',
    Map<String, dynamic>? studyContext,
    String? projectId,
  }) async* {
    final uri = Uri.parse('$baseUrl/api/v1/chat/stream');
    final req = http.Request('POST', uri);
    req.headers.addAll(_projectHeaders(includeJson: true));
    req.headers['Accept'] = 'text/event-stream';
    req.body = jsonEncode({
      'message': message,
      if (history.isNotEmpty) 'history': history,
      'tier': tier,
      if (studyContext != null) 'study_context': studyContext,
      if (projectId != null && projectId.trim().isNotEmpty)
        'project_id': projectId.trim(),
    });

    final streamed =
        await _client.send(req).timeout(const Duration(seconds: 45));
    _notifyIfSessionExpired(streamed.statusCode);
    if (streamed.statusCode == 404 || streamed.statusCode == 405) {
      final fallback = await sendChatMessage(
        message,
        history: history,
        tier: tier,
        studyContext: studyContext,
        projectId: projectId,
      );
      yield {'event': 'done', 'data': fallback};
      return;
    }
    if (streamed.statusCode == 429) {
      throw const ApiHttpException(
        429,
        'Trop de requêtes envoyées (429). Réessayez dans une minute.',
      );
    }
    if (streamed.statusCode != 200) {
      throw ApiHttpException(
        streamed.statusCode,
        'Erreur API Chat (${streamed.statusCode})',
      );
    }

    var currentEvent = 'message';
    final dataBuffer = StringBuffer();
    await for (final line in streamed.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter())) {
      if (line.isEmpty) {
        if (dataBuffer.isNotEmpty) {
          final rawData = dataBuffer.toString().trim();
          dataBuffer.clear();
          try {
            final parsed = jsonDecode(rawData);
            if (parsed is Map<String, dynamic>) {
              yield {'event': currentEvent, 'data': parsed};
            }
          } catch (_) {}
        }
        currentEvent = 'message';
      } else if (line.startsWith('event:')) {
        currentEvent = line.substring(6).trim();
      } else if (line.startsWith('data:')) {
        if (dataBuffer.isNotEmpty) dataBuffer.write('\n');
        dataBuffer.write(line.substring(5).trimLeft());
      }
    }
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

        _notifyIfSessionExpired(resp.statusCode);
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

  // --- Domaine Agriculture : pré-diagnostic agro-climatique de zone ---------

  Map<String, dynamic>? _cachedAgroZones;
  DateTime? _cachedAgroZonesAt;
  final Map<String, Map<String, dynamic>> _cachedAgroProfiles = {};
  final Map<String, DateTime> _cachedAgroProfilesAt = {};

  static const Duration _agroCacheTtl = Duration(minutes: 10);

  Map<String, dynamic>? get cachedAgroZones => _cachedAgroZones;

  Map<String, dynamic>? cachedAgroZoneProfile(String region) =>
      _cachedAgroProfiles[region];

  Future<Map<String, dynamic>> getAgroZones({bool forceRefresh = false}) async {
    if (!forceRefresh &&
        _cachedAgroZones != null &&
        _cachedAgroZonesAt != null &&
        DateTime.now().difference(_cachedAgroZonesAt!) < _agroCacheTtl) {
      return _cachedAgroZones!;
    }
    final uri = Uri.parse('$baseUrl/api/v1/agro/zones');
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      _cachedAgroZones = data;
      _cachedAgroZonesAt = DateTime.now();
      return data;
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur chargement des zones agricoles'));
  }

  Future<Map<String, dynamic>> getAgroZoneProfile(String region,
      {bool forceRefresh = false}) async {
    final at = _cachedAgroProfilesAt[region];
    if (!forceRefresh &&
        _cachedAgroProfiles.containsKey(region) &&
        at != null &&
        DateTime.now().difference(at) < _agroCacheTtl) {
      return _cachedAgroProfiles[region]!;
    }
    final uri = Uri.parse('$baseUrl/api/v1/agro/zone-profile')
        .replace(queryParameters: {'region': region});
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      _cachedAgroProfiles[region] = data;
      _cachedAgroProfilesAt[region] = DateTime.now();
      return data;
    }
    throw ApiHttpException(
        resp.statusCode,
        _extractErrorDetail(
            resp, 'Erreur chargement du profil agro-climatique'));
  }

  // --- Agronome PRO : Diagnostic de terrain & PDF co-brandé ----------------

  Future<Map<String, dynamic>?> getMyAgroProfile() async {
    final uri = Uri.parse('$baseUrl/api/v1/agro/profile');
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      final raw = decoded['profile'];
      return raw is Map ? Map<String, dynamic>.from(raw) : null;
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur chargement profil agronome'));
  }

  Future<Map<String, dynamic>> submitMyAgroProfile({
    required String firmName,
    required String licenseNumber,
    String address = '',
    String contact = '',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/agro/profile');
    final resp = await _client
        .put(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'firm_name': firmName.trim(),
            'license_number': licenseNumber.trim(),
            'address': address.trim(),
            'contact': contact.trim(),
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return Map<String, dynamic>.from(decoded['profile'] as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Enregistrement du profil agronome refusé'));
  }

  Future<List<Map<String, dynamic>>> getAdminAgroProfiles(
    String adminToken, {
    String? status,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/agro-profiles').replace(
      queryParameters:
          (status != null && status.isNotEmpty) ? {'status': status} : null,
    );
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim()
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return (decoded['profiles'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur chargement profils agronomes'));
  }

  Future<Map<String, dynamic>> reviewAdminAgroProfile(
    String adminToken,
    String ownerId, {
    required String status,
    String adminNote = '',
  }) async {
    final uri = Uri.parse(
        '$baseUrl/api/v1/admin/agro-profiles/${Uri.encodeComponent(ownerId)}/review');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json',
          },
          body: jsonEncode({
            'status': status,
            'admin_note': adminNote.trim(),
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Validation profil agronome refusée'));
  }

  Future<Map<String, dynamic>> createAgroFieldAssessment({
    required String provinceHub,
    String? projectId,
    double? gpsLat,
    double? gpsLon,
    double? areaHectares,
    double? customYieldKgHa,
    required Map<String, dynamic> labSoilInputs,
    String agronomistFieldNotes = '',
    List<String> targetCrops = const [
      'millet',
      'sorghum',
      'maize',
      'groundnut_raw',
    ],
  }) async {
    if (areaHectares == null ||
        !areaHectares.isFinite ||
        areaHectares <= 0 ||
        areaHectares > 500000) {
      throw ArgumentError('areaHectares doit être compris entre 0 et 500 000.');
    }
    if ((gpsLat == null) != (gpsLon == null)) {
      throw ArgumentError('gpsLat et gpsLon doivent être fournis ensemble.');
    }
    if (gpsLat != null &&
        (!gpsLat.isFinite ||
            !gpsLon!.isFinite ||
            gpsLat < -90 ||
            gpsLat > 90 ||
            gpsLon < -180 ||
            gpsLon > 180)) {
      throw ArgumentError('Coordonnées GPS hors limites.');
    }
    final uri = Uri.parse('$baseUrl/api/v1/agro/field-assessment');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            if (provinceHub.trim().isNotEmpty) 'province_hub': provinceHub,
            if (projectId != null && projectId.isNotEmpty)
              'project_id': projectId,
            if (gpsLat != null) 'gps_lat': gpsLat,
            if (gpsLon != null) 'gps_lon': gpsLon,
            'area_hectares': areaHectares,
            if (customYieldKgHa != null) 'custom_yield_kg_ha': customYieldKgHa,
            'lab_soil_inputs': labSoilInputs,
            'agronomist_field_notes': agronomistFieldNotes.trim(),
            'target_crops': targetCrops,
          }),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Diagnostic de terrain impossible'));
  }

  Future<Map<String, dynamic>> createAgroCreditPassportFromAssessment(
    String assessmentId, {
    double loanAmountXaf = 500000,
    String? cropId,
  }) async {
    final uri = Uri.parse(
        '$baseUrl/api/v1/agro/field-assessment/$assessmentId/credit-passport');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'loan_amount_xaf': loanAmountXaf,
            if (cropId != null && cropId.trim().isNotEmpty)
              'crop_id': cropId.trim(),
          }),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Génération Credit Passport impossible'));
  }

  Future<Map<String, dynamic>> createProjectShareLink(
    String projectId, {
    int ttlHours = 72,
  }) async {
    final uri = Uri.parse(
        '$baseUrl/api/v1/projects/$projectId/share-link?ttl_hours=$ttlHours');
    final resp = await _client
        .post(uri, headers: _projectHeaders(includeJson: true), body: '{}')
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Création du lien de partage impossible'));
  }

  Future<List<Map<String, dynamic>>> listAgroFieldAssessments(
      {String? projectId}) async {
    final uri = Uri.parse('$baseUrl/api/v1/agro/field-assessments').replace(
      queryParameters: (projectId != null && projectId.isNotEmpty)
          ? {'project_id': projectId}
          : null,
    );
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return (decoded['assessments'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur chargement diagnostics'));
  }

  Future<Uint8List> downloadAgroAssessmentPdf(
    String assessmentId, {
    String agronomistName = '',
    String agronomistLicense = '',
    String agronomistAddress = '',
    String agronomistContact = '',
    List<String> compareAssessmentIds = const [],
  }) async {
    final uri =
        Uri.parse('$baseUrl/api/v1/agro/field-assessment/$assessmentId/pdf');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'agronomist_name': agronomistName.trim(),
            'agronomist_license': agronomistLicense.trim(),
            'agronomist_address': agronomistAddress.trim(),
            'agronomist_contact': agronomistContact.trim(),
            if (compareAssessmentIds.isNotEmpty)
              'compare_assessment_ids': compareAssessmentIds,
          }),
        )
        .timeout(const Duration(seconds: 35));
    if (resp.statusCode == 200) {
      return resp.bodyBytes;
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Génération du PDF agronomique refusée'));
  }

  Future<void> deleteAgroFieldAssessment(String assessmentId) async {
    final uri =
        Uri.parse('$baseUrl/api/v1/agro/field-assessment/$assessmentId');
    final resp = await _client
        .delete(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) return;
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Suppression du diagnostic impossible'));
  }

  Future<Map<String, dynamic>> compareAgroAssessments({
    List<String> assessmentIds = const [],
    List<Map<String, dynamic>> candidates = const [],
    String agronomistName = '',
    String agronomistLicense = '',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/agro/compare-assessments');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            if (assessmentIds.isNotEmpty) 'assessment_ids': assessmentIds,
            if (candidates.isNotEmpty) 'candidates': candidates,
            'agronomist_name': agronomistName.trim(),
            'agronomist_license': agronomistLicense.trim(),
          }),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Comparaison multi-terrains impossible'));
  }

  Future<Uint8List> downloadAgroComparePdf({
    List<String> assessmentIds = const [],
    List<Map<String, dynamic>> candidates = const [],
    String agronomistName = '',
    String agronomistLicense = '',
    String agronomistAddress = '',
    String agronomistContact = '',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/agro/compare-assessments/pdf');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            if (assessmentIds.isNotEmpty) 'assessment_ids': assessmentIds,
            if (candidates.isNotEmpty) 'candidates': candidates,
            'agronomist_name': agronomistName.trim(),
            'agronomist_license': agronomistLicense.trim(),
            'agronomist_address': agronomistAddress.trim(),
            'agronomist_contact': agronomistContact.trim(),
          }),
        )
        .timeout(const Duration(seconds: 35));
    if (resp.statusCode == 200) {
      return resp.bodyBytes;
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Génération du PDF comparatif refusée'));
  }

  Future<Map<String, dynamic>> getAgroCampaignRadar() async {
    final uri = Uri.parse('$baseUrl/api/v1/agro/campaign-radar');
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Radar Agro-Marché indisponible'));
  }

  // --- Marché PRO : Watchlists, Arbitrage & Export CSV ---------------------

  Future<Map<String, dynamic>> computeFarmOperatingAccount({
    required String province,
    required String cropId,
    required double areaHectares,
    double? targetYieldKgHa,
    double farmgateDiscountPct = 8.0,
    double seedCostPerHaXaf = 0,
    double fertilizerCostPerHaXaf = 0,
    double laborCostPerHaXaf = 0,
    double landPrepIrrigationPerHaXaf = 0,
    double harvestPostharvestPerHaXaf = 0,
    double otherOpexPerHaXaf = 0,
    double capexTotalXaf = 0,
    double loanAmountXaf = 0,
    double interestRatePct = 0,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/markets/farm-operating-account');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'province': province,
            'crop_id': cropId,
            'area_hectares': areaHectares,
            if (targetYieldKgHa != null && targetYieldKgHa > 0)
              'target_yield_kg_ha': targetYieldKgHa,
            'farmgate_discount_pct': farmgateDiscountPct,
            'seed_cost_per_ha_xaf': seedCostPerHaXaf,
            'fertilizer_cost_per_ha_xaf': fertilizerCostPerHaXaf,
            'labor_cost_per_ha_xaf': laborCostPerHaXaf,
            'land_prep_irrigation_per_ha_xaf': landPrepIrrigationPerHaXaf,
            'harvest_postharvest_per_ha_xaf': harvestPostharvestPerHaXaf,
            'other_opex_per_ha_xaf': otherOpexPerHaXaf,
            'capex_total_xaf': capexTotalXaf,
            'loan_amount_xaf': loanAmountXaf,
            'interest_rate_pct': interestRatePct,
          }),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Calcul compte d\'exploitation impossible'));
  }

  Future<Map<String, dynamic>> computeCampaignPlan({
    required double capitalXaf,
    required String originProvince,
    String entrepreneurStatus = 'petit_commercant',
    String? cropId,
    int? holdingMonths,
    double coroWeightKg = 2.5,
    double transportPerBagXaf = 0,
    double storagePerBagMonthXaf = 0,
    double lossPct = 0,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/markets/campaign-plan');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'capital_xaf': capitalXaf,
            'origin_province': originProvince,
            'entrepreneur_status': entrepreneurStatus,
            if (cropId != null && cropId.isNotEmpty) 'crop_id': cropId,
            if (holdingMonths != null) 'holding_months': holdingMonths,
            'coro_weight_kg': coroWeightKg,
            'transport_per_bag_xaf': transportPerBagXaf,
            'storage_per_bag_month_xaf': storagePerBagMonthXaf,
            'loss_pct': lossPct,
          }),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Simulation de campagne impossible'));
  }

  Future<Map<String, dynamic>> getMarketProOverview({String? cropId}) async {
    final uri = Uri.parse('$baseUrl/api/v1/market-pro/overview').replace(
      queryParameters:
          (cropId != null && cropId.isNotEmpty) ? {'crop_id': cropId} : null,
    );
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur chargement Marché PRO'));
  }

  Future<Map<String, dynamic>> createMarketWatchlist({
    required String cropId,
    required double thresholdXafKg,
    String direction = 'above',
    String province = '',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/market-pro/watchlists');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'crop_id': cropId,
            'threshold_xaf_kg': thresholdXafKg,
            'direction': direction,
            'province': province.trim(),
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Création de l’alerte impossible'));
  }

  Future<void> deleteMarketWatchlist(String watchId) async {
    final uri = Uri.parse('$baseUrl/api/v1/market-pro/watchlists/$watchId');
    final resp = await _client
        .delete(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      throw ApiHttpException(resp.statusCode,
          _extractErrorDetail(resp, 'Suppression de l’alerte impossible'));
    }
  }

  Future<Map<String, dynamic>> _marketIntelGet(
    String path,
    String fallback,
  ) async {
    final uri = Uri.parse('$baseUrl/api/v1/market-intel/$path');
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    final detail = _extractErrorDetail(resp, fallback);
    throw ApiHttpException(resp.statusCode, detail);
  }

  Future<Map<String, dynamic>> getMarketIntelProduct(String id) {
    return _marketIntelGet('product/$id', 'Fiche produit indisponible');
  }

  Future<Map<String, dynamic>> getMarketIntelEntryBrief(String id) {
    return _marketIntelGet('entry-brief/$id', 'Brief d’entrée indisponible');
  }

  Future<Map<String, dynamic>> getMarketIntelCompare(String id) {
    return _marketIntelGet('compare/$id', 'Comparateur indisponible');
  }

  Future<Map<String, dynamic>> getMarketIntelPulse() {
    return _marketIntelGet('pulse', 'Pouls du marché indisponible');
  }

  Future<Map<String, dynamic>> getMarketIntelWorld(String id) {
    return _marketIntelGet(
      'world-context?product_id=$id',
      'Contexte mondial indisponible',
    );
  }

  Future<Map<String, dynamic>> getMarketIntelAlerts() {
    return _marketIntelGet('alerts', 'Alertes indisponibles');
  }

  Future<Map<String, dynamic>> getMarketIntelBasket() async {
    final uri = Uri.parse('$baseUrl/api/v1/market-intel/basket');
    final weights = {'millet': 1, 'sorghum': 1, 'maize': 1, 'rice_local': 1};
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({'weights': weights}),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    final detail = _extractErrorDetail(resp, 'Panier indisponible');
    throw ApiHttpException(resp.statusCode, detail);
  }

  Future<void> createMarketIntelAlert({
    required String kind,
    required String productId,
    required double value,
    required String direction,
    String marketName = '',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/market-intel/alerts');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'kind': kind,
            'product_id': productId,
            'value': value,
            'direction': direction,
            'market_name': marketName.trim(),
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      final detail = _extractErrorDetail(resp, 'Alerte non créée');
      throw ApiHttpException(resp.statusCode, detail);
    }
  }

  Future<void> deleteMarketIntelAlert(String ruleId) async {
    final uri = Uri.parse('$baseUrl/api/v1/market-intel/alerts/$ruleId');
    final resp = await _client
        .delete(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      final detail = _extractErrorDetail(resp, 'Suppression impossible');
      throw ApiHttpException(resp.statusCode, detail);
    }
  }

  Future<void> ackMarketIntelAlert(String ruleId) async {
    final uri = Uri.parse('$baseUrl/api/v1/market-intel/alerts/$ruleId/ack');
    final resp = await _client
        .post(uri, headers: _projectHeaders())
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode != 200) {
      final detail = _extractErrorDetail(resp, 'Action impossible');
      throw ApiHttpException(resp.statusCode, detail);
    }
  }

  Future<Uint8List> downloadMarketProCsv({String? cropId}) async {
    final uri = Uri.parse('$baseUrl/api/v1/market-pro/export.csv').replace(
      queryParameters:
          (cropId != null && cropId.isNotEmpty) ? {'crop_id': cropId} : null,
    );
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      return resp.bodyBytes;
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Export CSV Marché PRO impossible'));
  }

  Future<Map<String, dynamic>> getSpatialArbitrage({
    required String cropId,
    double? transportCostXafKg,
    double? tonnage,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/markets/spatial-arbitrage').replace(
      queryParameters: {
        'crop_id': cropId,
        if (transportCostXafKg != null)
          'transport_cost_xaf_kg': transportCostXafKg.toString(),
        if (tonnage != null) 'tonnage': tonnage.toString(),
      },
    );
    final resp = await _getWithRetry(uri, headers: _projectHeaders());
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Calcul d’arbitrage spatial impossible'));
  }

  Future<Map<String, dynamic>> computeAgroCreditPassport({
    required String province,
    required String cropId,
    required double areaHectares,
    required double loanAmountXaf,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/markets/credit-passport/agro');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            'province': province.trim(),
            'crop_id': cropId,
            'area_hectares': areaHectares,
            'loan_amount_xaf': loanAmountXaf,
          }),
        )
        .timeout(const Duration(seconds: 25));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Calcul Credit Passport Agro impossible'));
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
          resp.statusCode, 'Abonnement PRO requis pour générer le PDF.');
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
    if (_cachedBillingPlans != null &&
        _cachedBillingPlansAt != null &&
        DateTime.now().difference(_cachedBillingPlansAt!) <
            _billingCatalogCacheTtl) {
      return _cachedBillingPlans!;
    }
    final uri = Uri.parse('$baseUrl/api/v1/billing/plans');
    final resp = await _getWithRetry(uri);
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      _cachedBillingPlans = data;
      _cachedBillingPlansAt = DateTime.now();
      return data;
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
      _cachedMyBilling = data;
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

  Future<Map<String, dynamic>> setAdminDomainStatus(
    String adminToken,
    String domainId,
    bool active, {
    String reason = 'Admin AI Control Center',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/ai/domains/$domainId/status');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json',
          },
          body: jsonEncode({'active': active, 'reason': reason}),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(
        resp.statusCode, _extractErrorDetail(resp, 'Erreur statut domaine IA'));
  }

  Future<Map<String, dynamic>> transitionAdminMlModelStatus(
    String adminToken,
    String modelId, {
    required int version,
    required String lifecycleStatus,
    bool setActive = false,
    bool? enabled,
    String reason = 'Admin AI Control Center',
    bool force = false,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/ai/models/$modelId/status');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json',
          },
          body: jsonEncode({
            'version': version,
            'lifecycle_status': lifecycleStatus,
            'set_active': setActive,
            if (enabled != null) 'enabled': enabled,
            'reason': reason,
            if (force) 'force': true,
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur mise à jour modèle ML'));
  }

  Future<Map<String, dynamic>> rollbackAdminMlModel(
    String adminToken,
    String modelId, {
    required int targetVersion,
    String reason = 'Admin rollback',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/ai/models/$modelId/rollback');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json',
          },
          body: jsonEncode({'target_version': targetVersion, 'reason': reason}),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur rollback modèle ML'));
  }

  /// Éligibilité d'une version à la production : {eligible: bool, blockers: [String]}.
  Future<Map<String, dynamic>> getAdminMlPromotionCheck(
    String adminToken,
    String modelId,
    int version,
  ) async {
    final uri = Uri.parse(
        '$baseUrl/api/v1/admin/ai/models/$modelId/versions/$version/promotion-check');
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim(),
    }).timeout(const Duration(seconds: 15));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Vérification d\'éligibilité impossible'));
  }

  Future<Map<String, dynamic>> compareAdminMlModelVersions(
    String adminToken,
    String modelId,
  ) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/ai/models/$modelId/compare');
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim(),
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur comparaison versions ML'));
  }

  Future<Map<String, dynamic>> launchAdminBenchmark(
    String adminToken, {
    required String domain,
    required String taskType,
    required List<String> featureColumns,
    String? targetColumn,
    String? timeColumn,
    required String datasetName,
    String datasetScope = 'platform_public',
    Map<String, dynamic> datasetProvenance = const {},
    required String csvBase64,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/ai/benchmark');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json',
          },
          body: jsonEncode({
            'domain': domain,
            'task_type': taskType,
            'feature_columns': featureColumns,
            if (targetColumn != null && targetColumn.isNotEmpty)
              'target_column': targetColumn,
            if (timeColumn != null && timeColumn.isNotEmpty)
              'time_column': timeColumn,
            'dataset_name': datasetName,
            'dataset_scope': datasetScope,
            'dataset_provenance': datasetProvenance,
            'csv_base64': csvBase64,
          }),
        )
        .timeout(const Duration(seconds: 30));
    if (resp.statusCode == 200 || resp.statusCode == 202) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur lancement benchmark ML'));
  }

  Future<Map<String, dynamic>> getAdminBenchmarkJob(
    String adminToken,
    String jobId,
  ) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/ai/benchmark/$jobId');
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim(),
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur suivi job benchmark'));
  }

  Future<List<Map<String, dynamic>>> listAdminBenchmarkJobs(
    String adminToken, {
    int limit = 20,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/ai/benchmarks?limit=$limit');
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim(),
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded = jsonDecode(utf8.decode(resp.bodyBytes)) as Map;
      return ((decoded['jobs'] as List?) ?? []).cast<Map<String, dynamic>>();
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur historique benchmarks'));
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
    String persona = 'analyste',
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
            'persona': persona,
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
        isPro: data['is_pro'] == true,
        entitlements: data['entitlements'] is List
            ? (data['entitlements'] as List).map((e) => e.toString())
            : null,
        roles: data['roles'] is List
            ? (data['roles'] as List).map((e) => e.toString())
            : null,
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
      final hasInlinePro = data.containsKey('is_pro');
      setAuthSession(
        token: data['token']?.toString(),
        user: data['user'] is Map
            ? Map<String, dynamic>.from(data['user'] as Map)
            : null,
        isPro: hasInlinePro ? data['is_pro'] == true : null,
        entitlements: data['entitlements'] is List
            ? (data['entitlements'] as List).map((e) => e.toString())
            : null,
        roles: data['roles'] is List
            ? (data['roles'] as List).map((e) => e.toString())
            : null,
      );
      if (!hasInlinePro) {
        try {
          final me = await getAuthMe();
          _subscriptionIsPro = me['is_pro'] == true;
        } catch (_) {}
      }
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
        entitlements: data['entitlements'] is List
            ? (data['entitlements'] as List).map((e) => e.toString())
            : null,
        roles: data['roles'] is List
            ? (data['roles'] as List).map((e) => e.toString())
            : null,
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
      {String? displayName, String? persona}) async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/profile');
    final resp = await _client
        .patch(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({
            if (displayName != null) 'display_name': displayName.trim(),
            if (persona != null) 'persona': persona.trim().toLowerCase(),
          }),
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
    // Les anciens jetons sont invalidés côté serveur : adopter la session neuve renvoyée.
    try {
      final data = jsonDecode(utf8.decode(resp.bodyBytes));
      final session = data is Map ? data['session'] : null;
      final newTok = session is Map ? session['token']?.toString() ?? '' : '';
      if (newTok.isNotEmpty) {
        setAuthSession(token: newTok, user: _authUser);
        // Keep refreshed bearer tokens in memory only; do not persist them in browser storage.
      }
    } catch (_) {}
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
    if (_cachedPaymentMethods != null &&
        _cachedPaymentMethodsAt != null &&
        DateTime.now().difference(_cachedPaymentMethodsAt!) <
            _billingCatalogCacheTtl) {
      return _cachedPaymentMethods!;
    }
    final uri = Uri.parse('$baseUrl/api/v1/billing/payment-methods');
    final resp = await _client.get(uri).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      _cachedPaymentMethods = data;
      _cachedPaymentMethodsAt = DateTime.now();
      return data;
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
      final list = (decoded['requests'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
      _cachedMyPaymentRequests = list;
      return list;
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

  /// Active une clé PRO unique (usage unique, strictement liée au compte connecté).
  Future<Map<String, dynamic>> redeemProActivationKey(
      String activationKey) async {
    final uri = Uri.parse('$baseUrl/api/v1/billing/redeem-key');
    final resp = await _client
        .post(
          uri,
          headers: _projectHeaders(includeJson: true),
          body: jsonEncode({'activation_key': activationKey.trim()}),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final data = Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
      _subscriptionIsPro = data['is_pro'] == true;
      invalidateUserBillingCache();
      return data;
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Activation de la clé impossible'));
  }

  Future<Map<String, dynamic>> createAdminProKey(
    String adminToken, {
    String planId = 'premium',
    int durationDays = 30,
    String note = '',
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/billing/keys');
    final resp = await _client
        .post(
          uri,
          headers: {
            'X-Admin-Token': adminToken.trim(),
            'Content-Type': 'application/json',
          },
          body: jsonEncode({
            'plan_id': planId,
            'duration_days': durationDays,
            'note': note.trim(),
          }),
        )
        .timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur génération clé PRO'));
  }

  Future<List<Map<String, dynamic>>> listAdminProKeys(
    String adminToken, {
    String? status,
  }) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/billing/keys').replace(
      queryParameters: {
        if (status != null && status.isNotEmpty) 'status': status,
        'limit': '100',
      },
    );
    final resp = await _client.get(uri, headers: {
      'X-Admin-Token': adminToken.trim(),
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return (decoded['keys'] as List? ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur chargement clés PRO'));
  }

  Future<Map<String, dynamic>> revokeAdminProKey(
    String adminToken,
    String keyId,
  ) async {
    final uri = Uri.parse('$baseUrl/api/v1/admin/billing/keys/$keyId/revoke');
    final resp = await _client.post(uri, headers: {
      'X-Admin-Token': adminToken.trim(),
    }).timeout(const Duration(seconds: 20));
    if (resp.statusCode == 200) {
      return Map<String, dynamic>.from(
          jsonDecode(utf8.decode(resp.bodyBytes)) as Map);
    }
    throw ApiHttpException(resp.statusCode,
        _extractErrorDetail(resp, 'Erreur révocation clé PRO'));
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
        .timeout(const Duration(seconds: 120));
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
