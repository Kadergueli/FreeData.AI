import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/auth_token_storage.dart';
import 'package:freedata_ai/widgets/auth_dialog.dart';

class _MemoryTokenStorage implements AuthTokenStorageBackend {
  String? value;
  bool failWrites = false;

  @override
  Future<String?> read() async => value;

  @override
  Future<void> write(String token) async {
    if (failWrites) throw StateError('secure storage unavailable');
    value = token;
  }

  @override
  Future<void> delete() async {
    value = null;
  }
}

class _AuthApi extends ApiService {
  _AuthApi({this.token = 'session-token'});

  final String token;
  int logoutCalls = 0;

  @override
  Future<Map<String, dynamic>> loginAccount({
    required String email,
    required String password,
  }) async {
    setAuthSession(token: token, user: {'email': email});
    return {'token': token, 'user': {'email': email}};
  }

  @override
  Future<void> logoutAccount() async {
    logoutCalls++;
    clearAuthSession();
  }
}

void main() {
  late _MemoryTokenStorage storage;

  setUp(() {
    storage = _MemoryTokenStorage();
    AuthTokenStorage.setBackendForTesting(storage);
  });

  tearDown(() {
    AuthTokenStorage.resetBackend();
  });

  Future<void> openLoginDialog(
    WidgetTester tester,
    _AuthApi api,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => showDialog<bool>(
                context: context,
                builder: (_) => AuthDialog(apiService: api),
              ),
              child: const Text('Open login'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Open login'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextField, 'Adresse e-mail'),
      'user@example.td',
    );
    await tester.enterText(
      find.widgetWithText(TextField, 'Mot de passe'),
      'ValidPass123!',
    );
  }

  testWidgets('AuthDialog persists the token before closing successfully',
      (tester) async {
    final api = _AuthApi();
    await openLoginDialog(tester, api);

    await tester.tap(find.text('Se connecter').last);
    await tester.pumpAndSettle();

    expect(storage.value, 'session-token');
    expect(api.isAuthenticated, isTrue);
    expect(find.byType(AuthDialog), findsNothing);
  });

  testWidgets('AuthDialog rejects a successful response without a token',
      (tester) async {
    final api = _AuthApi(token: '');
    await openLoginDialog(tester, api);

    await tester.tap(find.text('Se connecter').last);
    await tester.pumpAndSettle();

    expect(find.byType(AuthDialog), findsOneWidget);
    expect(
      find.text(
        'Le serveur n’a pas fourni de jeton de session. Veuillez réessayer.',
      ),
      findsOneWidget,
    );
    expect(api.isAuthenticated, isFalse);
    expect(storage.value, isNull);
  });

  testWidgets('AuthDialog clears the in-memory session when secure storage fails',
      (tester) async {
    storage.failWrites = true;
    final api = _AuthApi();
    await openLoginDialog(tester, api);

    await tester.tap(find.text('Se connecter').last);
    await tester.pumpAndSettle();

    expect(find.byType(AuthDialog), findsOneWidget);
    expect(
      find.textContaining('impossible de sécuriser votre session'),
      findsOneWidget,
    );
    expect(api.isAuthenticated, isFalse);
    expect(api.logoutCalls, 1);
  });
}
