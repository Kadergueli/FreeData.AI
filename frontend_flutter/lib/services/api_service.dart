import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiService {
  // Remplacer en production via --dart-define=API_BASE_URL=https://votre-api.onrender.com
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  Future<Map<String, dynamic>> sendChatMessage(String message) async {
    final uri = Uri.parse('$baseUrl/api/v1/chat');
    final resp = await http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'message': message}),
    );
    if (resp.statusCode == 200) {
      return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    }
    throw Exception('Erreur API Chat (${resp.statusCode})');
  }

  Future<Map<String, dynamic>> getMetadata() async {
    final uri = Uri.parse('$baseUrl/api/v1/metadata');
    final resp = await http.get(uri);
    if (resp.statusCode == 200) {
      return jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    }
    throw Exception('Erreur chargement métadonnées (${resp.statusCode})');
  }

  Future<List<dynamic>> getForecasts({String? province, String? commodity}) async {
    final params = <String, String>{};
    if (province != null && province.isNotEmpty) params['province'] = province;
    if (commodity != null && commodity.isNotEmpty) params['commodity'] = commodity;
    final uri = Uri.parse('$baseUrl/api/v1/forecasts').replace(queryParameters: params);
    final resp = await http.get(uri);
    if (resp.statusCode == 200) {
      final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw Exception('Erreur chargement prévisions (${resp.statusCode})');
  }

  Future<List<dynamic>> getAlerts({double thresholdPct = 15.0}) async {
    final uri = Uri.parse('$baseUrl/api/v1/alerts').replace(
      queryParameters: {'threshold_pct': thresholdPct.toString()},
    );
    final resp = await http.get(uri);
    if (resp.statusCode == 200) {
      final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw Exception('Erreur chargement alertes (${resp.statusCode})');
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
    final resp = await http.get(uri);
    if (resp.statusCode == 200) {
      final data = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      return data['items'] as List<dynamic>;
    }
    throw Exception('Erreur chargement Credit Passport (${resp.statusCode})');
  }
}
