import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

const String kAuthTokenStorageKey = 'fd_auth_token_v1';

/// Stores authentication credentials in the platform secure-storage facility.
/// On Web, flutter_secure_storage uses WebCrypto-backed encrypted local storage;
/// production deployments must use HTTPS (localhost is accepted for development).
abstract interface class AuthTokenStorageBackend {
  Future<String?> read();
  Future<void> write(String token);
  Future<void> delete();
}

class _FlutterSecureAuthTokenStorage implements AuthTokenStorageBackend {
  const _FlutterSecureAuthTokenStorage();

  static const FlutterSecureStorage _storage = FlutterSecureStorage();

  @override
  Future<String?> read() => _storage.read(key: kAuthTokenStorageKey);

  @override
  Future<void> write(String token) =>
      _storage.write(key: kAuthTokenStorageKey, value: token);

  @override
  Future<void> delete() => _storage.delete(key: kAuthTokenStorageKey);
}

class AuthTokenStorage {
  AuthTokenStorage._();

  static AuthTokenStorageBackend _backend =
      const _FlutterSecureAuthTokenStorage();

  /// Allows deterministic in-memory storage in Flutter widget tests.
  @visibleForTesting
  static void setBackendForTesting(AuthTokenStorageBackend backend) {
    _backend = backend;
  }

  @visibleForTesting
  static void resetBackend() {
    _backend = const _FlutterSecureAuthTokenStorage();
  }

  static Future<String?> read() => _backend.read();

  static Future<void> write(String token) async {
    final clean = token.trim();
    if (clean.isEmpty) {
      throw ArgumentError.value(
        token,
        'token',
        'A non-empty token is required.',
      );
    }
    await _backend.write(clean);
  }

  static Future<void> delete() => _backend.delete();

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
    final secureToken = await _backend.read();
    if (secureToken == null || secureToken.trim().isEmpty) {
      await _backend.write(legacyToken.trim());
    }
    await preferences.remove(kAuthTokenStorageKey);
  }
}
