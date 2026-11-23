import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/services/auth_token_storage.dart';
import 'helpers/memory_auth_token_storage.dart';

class _FailingAuthTokenStorage implements AuthTokenStorageBackend {
  @override
  Future<String?> read() async => null;

  @override
  Future<void> write(String token) async {
    throw StateError('secure storage unavailable');
  }

  @override
  Future<void> delete() async {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    AuthTokenStorage.setBackendForTesting(MemoryAuthTokenStorage());
  });

  test('migrates legacy token and removes plaintext preference', () async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kAuthTokenStorageKey, 'legacy-token');
    final secure = MemoryAuthTokenStorage();
    AuthTokenStorage.setBackendForTesting(secure);

    await AuthTokenStorage.migrateLegacy(prefs);

    expect(secure.token, 'legacy-token');
    expect(prefs.getString(kAuthTokenStorageKey), isNull);
  });

  test('removes plaintext preference when secure migration fails', () async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kAuthTokenStorageKey, 'legacy-token');
    AuthTokenStorage.setBackendForTesting(_FailingAuthTokenStorage());

    await expectLater(
      AuthTokenStorage.migrateLegacy(prefs),
      throwsA(isA<StateError>()),
    );

    expect(prefs.getString(kAuthTokenStorageKey), isNull);
  });

  test(
      'does not overwrite an existing secure token during migration',
      () async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kAuthTokenStorageKey, 'legacy-token');
    final secure = MemoryAuthTokenStorage()
      ..token = 'current-secure-token';
    AuthTokenStorage.setBackendForTesting(secure);

    await AuthTokenStorage.migrateLegacy(prefs);

    expect(secure.token, 'current-secure-token');
    expect(prefs.getString(kAuthTokenStorageKey), isNull);
  });
}
