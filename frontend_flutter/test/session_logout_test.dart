import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/auth_token_storage.dart';
import 'package:freedata_ai/services/conversation_storage.dart';
import 'package:freedata_ai/services/session_logout.dart';

class _MemoryTokenStorage implements AuthTokenStorageBackend {
  String? token;
  bool failDelete = false;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String value) async {
    token = value;
  }

  @override
  Future<void> delete() async {
    if (failDelete) throw StateError('secure storage unavailable');
    token = null;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late _MemoryTokenStorage tokenStorage;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    tokenStorage = _MemoryTokenStorage();
    AuthTokenStorage.setBackendForTesting(tokenStorage);
  });

  tearDown(AuthTokenStorage.resetBackend);

  test('logout clears the account-scoped cache and local session', () async {
    final api = ApiService()
      ..setAuthSession(
        token: 'test-token',
        user: {'id': 'user-1', 'email': 'user@example.com'},
      );
    final storage = LocalConversationStorage.instance..attachCloudApi(api);
    final accountKey = storage.activeStorageKey;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(accountKey, '[{"id":"private-conversation"}]');
    tokenStorage.token = 'test-token';

    final result = await SessionLogout.perform(apiService: api);

    expect(result.cacheCleared, isTrue);
    expect(prefs.containsKey(accountKey), isFalse);
    expect(tokenStorage.token, isNull);
    expect(api.isAuthenticated, isFalse);
  });

  test('secure token deletion failure preserves the active session', () async {
    final api = ApiService()
      ..setAuthSession(
        token: 'test-token',
        user: {'id': 'user-2', 'email': 'user2@example.com'},
      );
    LocalConversationStorage.instance.attachCloudApi(api);
    tokenStorage.token = 'test-token';
    tokenStorage.failDelete = true;

    await expectLater(
      SessionLogout.perform(apiService: api),
      throwsA(isA<StateError>()),
    );

    expect(api.isAuthenticated, isTrue);
    expect(api.authToken, 'test-token');
    expect(tokenStorage.token, 'test-token');
  });
}
