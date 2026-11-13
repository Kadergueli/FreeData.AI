import 'package:flutter/material.dart';

import 'theme/app_theme.dart';
export 'design_system/fd_design_system.dart';

class FDTheme {
  static const blue = AppColors.blue;
  static const blueDark = AppColors.blueDark;
  static const turquoise = AppColors.turquoise;
  static const green = AppColors.green;
  static const ink = AppColors.ink;
  static const muted = AppColors.muted;
  static const canvas = AppColors.canvas;
  static const line = AppColors.line;
  static const surface = AppColors.surface;

  static ThemeData light() => AppTheme.light();
}
