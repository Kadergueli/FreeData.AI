import 'package:flutter/material.dart';

class AppColors {
  static const blue = Color(0xFF1D4ED8);
  static const blueDark = Color(0xFF1E40AF);
  static const blueSoft = Color(0xFFEFF6FF);
  static const turquoise = Color(0xFF35D2C5);
  static const green = Color(0xFF16A34A);
  static const greenDark = Color(0xFF166534);
  static const greenSoft = Color(0xFFF0FDF4);
  static const greenBorder = Color(0xFFBBF7D0);
  static const mint = Color(0xFFE9F9F6);
  static const ink = Color(0xFF0F172A);
  static const inkSoft = Color(0xFF1E293B);
  static const body = Color(0xFF334155);
  static const muted = Color(0xFF475569);
  static const subtle = Color(0xFF64748B);
  static const canvas = Color(0xFFF8FAFC);
  static const canvasSoft = Color(0xFFF1F5F9);
  static const line = Color(0xFFE2E8F0);
  static const borderStrong = Color(0xFFCBD5E1);
  static const surface = Colors.white;
  static const danger = Color(0xFFDC2626);
  static const dangerDark = Color(0xFF991B1B);
  static const dangerSoft = Color(0xFFFEF2F2);
  static const dangerBorder = Color(0xFFFECACA);
  static const warning = Color(0xFFD98B24);
  static const warningDark = Color(0xFFB45309);
  static const shadow = Color(0x1A172033);
}

class AppTheme {
  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(
      seedColor: AppColors.blue,
      brightness: Brightness.light,
      primary: AppColors.blue,
      secondary: AppColors.turquoise,
      surface: AppColors.surface,
      error: AppColors.danger,
    );

    return ThemeData(
      useMaterial3: true,
      fontFamily: 'Roboto',
      colorScheme: scheme,
      scaffoldBackgroundColor: AppColors.canvas,
      canvasColor: AppColors.canvas,
      cardColor: AppColors.surface,
      dividerColor: AppColors.line,
      dialogTheme: const DialogThemeData(backgroundColor: AppColors.surface),
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.canvas,
        foregroundColor: AppColors.ink,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
      ),
      navigationBarTheme: const NavigationBarThemeData(
        backgroundColor: AppColors.surface,
        elevation: 0,
        indicatorColor: Color(0xFFEAF3FF),
        labelTextStyle: WidgetStatePropertyAll(
          TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
        ),
      ),
      navigationRailTheme: const NavigationRailThemeData(
        backgroundColor: AppColors.canvas,
        selectedIconTheme: IconThemeData(color: AppColors.blue),
        unselectedIconTheme: IconThemeData(color: AppColors.muted),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surface,
        hintStyle: const TextStyle(color: AppColors.muted),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppColors.line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppColors.line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppColors.blue, width: 1.5),
        ),
        labelStyle: const TextStyle(color: AppColors.muted),
      ),
      textTheme: ThemeData.light().textTheme.apply(
        bodyColor: AppColors.ink,
        displayColor: AppColors.ink,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.blue,
          foregroundColor: Colors.white,
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.surface,
          foregroundColor: AppColors.ink,
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          side: const BorderSide(color: AppColors.line),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppColors.blue,
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.canvas,
        selectedColor: AppColors.blue.withValues(alpha: 0.12),
        labelStyle: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.ink),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      ),
      cardTheme: CardThemeData(
        color: AppColors.surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
    );
  }
}
