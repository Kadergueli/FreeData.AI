import 'package:flutter/material.dart';

class AppDestination {
  final String label;
  final IconData icon;
  final IconData selectedIcon;

  const AppDestination({
    required this.label,
    required this.icon,
    required this.selectedIcon,
  });
}

class AppNavigation {
  static const List<AppDestination> destinations = [
    AppDestination(label: 'Accueil', icon: Icons.home_outlined, selectedIcon: Icons.home_rounded),
    AppDestination(label: 'Assistant', icon: Icons.forum_outlined, selectedIcon: Icons.forum_rounded),
    AppDestination(label: 'Explorer', icon: Icons.explore_outlined, selectedIcon: Icons.explore_rounded),
    AppDestination(label: 'Bibliothèque', icon: Icons.library_books_outlined, selectedIcon: Icons.library_books_rounded),
    AppDestination(label: 'Prévisions', icon: Icons.show_chart_outlined, selectedIcon: Icons.show_chart_rounded),
    AppDestination(label: 'Credit Passport', icon: Icons.account_balance_outlined, selectedIcon: Icons.account_balance),
  ];
}
