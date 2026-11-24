import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:freedata_ai/screens/settings_screen.dart';
import 'package:freedata_ai/services/api_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('SettingsScreen persists preferences and confirms the save',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    var savedCallbacks = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: SettingsScreen(
          apiService: ApiService(),
          onPreferencesSaved: () => savedCallbacks++,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Enregistrer'));
    await tester.pumpAndSettle();

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('fd_pref_domain'), 'auto');
    expect(prefs.getString('fd_pref_agro_hub'), "N'Djamena");
    expect(savedCallbacks, 1);
    expect(find.text('Préférences enregistrées.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('SettingsScreen exposes account actions only when authenticated',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(
      MaterialApp(home: SettingsScreen(apiService: ApiService())),
    );
    await tester.pumpAndSettle();

    expect(find.text('Se connecter'), findsOneWidget);
    expect(find.text('Créer un compte'), findsOneWidget);
    expect(find.text('Se déconnecter'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
