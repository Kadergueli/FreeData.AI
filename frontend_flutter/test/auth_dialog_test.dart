import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/auth_token_storage.dart';
import 'package:freedata_ai/widgets/auth_dialog.dart';

class _FakeAuthApi extends ApiService {
  _FakeAuthApi({this.responseToken = 'test-session-token'});

  final String? responseToken;

  @override
  Future<Map<String, dynamic>> loginAccount({
    required String email,
    required String password,
  }) async {
    setAuthSession(token: responseToken, user: {'email': email});
    return {
      if (responseToken != null) 'token': responseToken,
      'user': {'email': email},
    };
  }
}

class _FailingTokenStorage implements AuthTokenStorageBackend {
  @override
  Future<String?> read() async => null;

  @override
  Future<void> write(String token) async {
    throw Exception('platform storage failure');
  }

  @override
  Future<void> delete() async {}
}

class _MemoryTokenStorage implements AuthTokenStorageBackend {
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

Future<void> _openAndSubmit(
  WidgetTester tester,
  _FakeAuthApi api,
) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (context) => TextButton(
            onPressed: () => showDialog<bool>(
              context: context,
              builder: (_) => AuthDialog(apiService: api),
            ),
            child: const Text('Open auth'),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('Open auth'));
  await tester.pumpAndSettle();
  await tester.enterText(find.byType(TextField).at(0), 'user@example.com');
  await tester.enterText(find.byType(TextField).at(1), 'correct-password');
  await tester.tap(find.text('Se connecter').last);
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  tearDown(AuthTokenStorage.resetBackend);

  testWidgets('Auth dialog stays open when the API returns no session token',
      (tester) async {
    AuthTokenStorage.setBackendForTesting(_MemoryTokenStorage());
    final api = _FakeAuthApi(responseToken: null);

    await _openAndSubmit(tester, api);

    expect(find.text('Connexion à votre espace'), findsOneWidget);
    expect(find.textContaining('jeton de session'), findsOneWidget);
    expect(api.isAuthenticated, isFalse);
  });

  testWidgets('Auth dialog clears memory session when secure storage fails',
      (tester) async {
    AuthTokenStorage.setBackendForTesting(_FailingTokenStorage());
    final api = _FakeAuthApi();

    await _openAndSubmit(tester, api);

    expect(find.text('Connexion à votre espace'), findsOneWidget);
    expect(find.textContaining('Impossible de sécuriser votre session'),
        findsOneWidget);
    expect(api.isAuthenticated, isFalse);
  });

  testWidgets('Auth dialog closes after the session token is persisted',
      (tester) async {
    final storage = _MemoryTokenStorage();
    AuthTokenStorage.setBackendForTesting(storage);
    final api = _FakeAuthApi();

    await _openAndSubmit(tester, api);

    expect(find.text('Connexion à votre espace'), findsNothing);
    expect(api.isAuthenticated, isTrue);
    expect(storage.token, 'test-session-token');
  });
}
