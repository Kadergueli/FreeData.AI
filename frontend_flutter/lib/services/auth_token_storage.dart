import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String kAuthTokenStorageKey = 'fd_auth_token_v1';

/// Stores authentication credentials in the platform secure-storage facility.
/// On Web, flutter_secure_storage uses WebCrypto-backed encrypted local storage;
/// production deployments must use HTTPS (localhost is accepted for development).
class AuthTokenStorage {
  AuthTokenStorage._();

  static const FlutterSecureStorage _storage = FlutterSecureStorage();

  static Future<String?> read() => _storage.read(key: kAuthTokenStorageKey);

  static Future<void> write(String token) async {
    final clean = token.trim();
    if (clean.isEmpty) {
      throw ArgumentError.value(token, 'token', 'A non-empty token is required.');
    }
    await _storage.write(key: kAuthTokenStorageKey, value: clean);
  }

  static Future<void> delete() => _storage.delete(key: kAuthTokenStorageKey);

  /// One-time migration from the legacy plaintext SharedPreferences entry.
  /// The old value is removed only after secure storage confirms the write.
  static Future<void> migrateLegacy(SharedPreferences preferences) async {
    final legacyToken = preferences.getString(kAuthTokenStorageKey);
    if (legacyToken == null || legacyToken.trim().isEmpty) {
      if (legacyToken != null) {
        await preferences.remove(kAuthTokenStorageKey);
      }
      return;
    }
    final secureToken = await read();
    if (secureToken == null || secureToken.trim().isEmpty) {
      await write(legacyToken);
    }
    await preferences.remove(kAuthTokenStorageKey);
  }
}
