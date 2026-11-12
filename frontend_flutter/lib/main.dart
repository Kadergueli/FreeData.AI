import 'package:flutter/material.dart';
import 'services/api_service.dart';
import 'screens/chat_screen.dart';
import 'screens/forecast_screen.dart';
import 'screens/passport_screen.dart';

void main() {
  runApp(const FreeDataAIApp());
}

class FreeDataAIApp extends StatelessWidget {
  const FreeDataAIApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'FreeData.AI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF1B4F72),
        useMaterial3: true,
      ),
      home: const HomeShell(),
    );
  }
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;
  final ApiService _apiService = ApiService();

  @override
  Widget build(BuildContext context) {
    final pages = [
      ChatScreen(apiService: _apiService),
      ForecastScreen(apiService: _apiService),
      PassportScreen(apiService: _apiService),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text('FreeData.AI — Intelligence des Marchés (Tchad)'),
      ),
      body: pages[_index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.chat_bubble_outline), label: 'Agent IA'),
          NavigationDestination(icon: Icon(Icons.trending_up), label: 'Prévisions t+1'),
          NavigationDestination(icon: Icon(Icons.account_balance_outlined), label: 'Credit Passport'),
        ],
      ),
    );
  }
}
