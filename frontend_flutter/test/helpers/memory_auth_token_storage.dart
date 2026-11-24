import 'package:freedata_ai/services/auth_token_storage.dart';

class MemoryAuthTokenStorage implements AuthTokenStorageBackend {
  String? token;

  @override
  Future<String?> read() async => token;

  @override
  Future<void> write(String value) async {
    token = value;
  }

  @override
  Future<void> delete() async {
    token = null;
  }
}
