import 'api_service.dart';
import 'auth_token_storage.dart';
import 'conversation_storage.dart';

class SessionLogoutResult {
  final bool cacheCleared;

  const SessionLogoutResult({required this.cacheCleared});
}

class SessionLogout {
  SessionLogout._();

  /// Removes the active account's local cache before clearing the API identity.
  /// A cache failure is reported but does not trap the user in the session.
  /// A secure-token deletion failure aborts logout while the in-memory session
  /// is still intact, allowing the user to retry safely.
  static Future<SessionLogoutResult> perform({
    required ApiService apiService,
  }) async {
    final storage = LocalConversationStorage.instance;
    final accountStorageKey = storage.activeStorageKey;
    var cacheCleared = true;

    try {
      await storage.clearStorageKey(accountStorageKey);
    } catch (_) {
      cacheCleared = false;
    }

    await AuthTokenStorage.delete();
    await apiService.logoutAccount();

    return SessionLogoutResult(cacheCleared: cacheCleared);
  }
}
