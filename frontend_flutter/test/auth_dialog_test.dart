import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:freedata_ai/services/api_service.dart';
import 'package:freedata_ai/services/auth_token_storage.dart';
import 'package:freedata_ai/widgets/auth_dialog.dart';

class _FakeAuthApi extends ApiService {
  _FakeAuthApi({this.responseToken = 'test-session-token'});

  final String? responseToken;
  int logoutCalls = 0;

  @override
  Future<void> logoutAccount() async {
    logoutCalls++;
    clearAuthSession();
  }

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
    expect(find.textContaining('impossible de sécuriser votre session'),
        findsOneWidget);
    expect(api.isAuthenticated, isFalse);
    expect(api.logoutCalls, 1);
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

  testWidgets('Auth dialog presents the FreeData brand and a focused signup', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => showDialog<bool>(
                context: context,
                builder: (_) => AuthDialog(
                  apiService: _FakeAuthApi(),
                  initialRegisterMode: true,
                ),
              ),
              child: const Text('Open signup'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open signup'));
    await tester.pumpAndSettle();

    expect(
      find.text('Transformez vos données en décisions intelligentes.'),
      findsOneWidget,
    );
    expect(find.text('by FreeData.td'), findsOneWidget);
    expect(find.text('IA & Analyse documentaire'), findsOneWidget);
    expect(find.text('Analyses prédictives & simulations'), findsOneWidget);
    expect(find.text('Rapports & espaces de travail'), findsOneWidget);
    expect(find.text('Votre profil principal'), findsNothing);
    expect(find.textContaining('8 secteurs clés'), findsNothing);
    expect(find.textContaining('Rapports Certifiés'), findsNothing);
    expect(
      find.text('Nom complet ou organisation (facultatif)'),
      findsOneWidget,
    );
  });
}
2026-11-24T09:23:29.8608628