import 'package:flutter_test/flutter_test.dart';

import 'package:freedata_ai/main.dart';

void main() {
  testWidgets('L\'application démarre sur l\'écran Agent IA', (WidgetTester tester) async {
    await tester.pumpWidget(const FreeDataAIApp());

    expect(find.text('FreeData.AI — Intelligence des Marchés (Tchad)'), findsOneWidget);
    // Libellés de la barre de navigation
    expect(find.text('Agent IA'), findsOneWidget);
    expect(find.text('Prévisions t+1'), findsOneWidget);
    expect(find.text('Credit Passport'), findsOneWidget);
  });
}
