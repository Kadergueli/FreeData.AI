import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:freedata_ai/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets(
      'Workspace starts up and shows navigation entries in mobile Drawer',
      (WidgetTester tester) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    await tester.pumpWidget(const FreeDataAIApp());
    await tester.pumpAndSettle();

    // Vérifie le titre FreeData.AI et l'accueil conversationnel
    expect(find.text('FreeData.AI'), findsWidgets);
    expect(find.text('Que souhaitez-vous analyser ?'), findsOneWidget);

    // Vérifie le bouton moderne nouvelle conversation et ouvre le Drawer
    expect(find.byIcon(Icons.edit_square), findsOneWidget);
    final menuButton = find.byIcon(Icons.menu_rounded);
    expect(menuButton, findsOneWidget);
    await tester.tap(menuButton);
    await tester.pumpAndSettle();

    // Vérifie les entrées du Workspace
    expect(find.text('Assistant IA'), findsOneWidget);
    expect(find.text('Explore'), findsOneWidget);
    expect(find.text('Library'), findsOneWidget);
    expect(find.text('Prévisions'), findsOneWidget);
    expect(find.text('Credit Passport'), findsOneWidget);
    expect(find.text('Nouvelle conversation'), findsOneWidget);
    expect(find.text('+ Nouvelle conversation'), findsNothing);
  });

  testWidgets('Workspace shows fixed Sidebar on Desktop (>= 900px)',
      (WidgetTester tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.physicalSize = const Size(800, 600);
      tester.view.devicePixelRatio = 1.0;
    });

    await tester.pumpWidget(const FreeDataAIApp());
    await tester.pumpAndSettle();

    // Sur Desktop, pas de bouton menu_rounded AppBar
    expect(find.byIcon(Icons.menu_rounded), findsNothing);

    // Sidebar directement visible
    expect(find.text('Assistant IA'), findsOneWidget);
    expect(find.text('Explore'), findsOneWidget);
    expect(find.text('Library'), findsOneWidget);
    expect(find.text('Prévisions'), findsOneWidget);
    expect(find.text('Credit Passport'), findsOneWidget);
    expect(find.text('Nouvelle conversation'), findsOneWidget);
    expect(find.text('+ Nouvelle conversation'), findsNothing);
  });
}
