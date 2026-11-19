import 'package:flutter/material.dart';
import '../../core/fd_theme.dart';

class ErrorMessage extends StatefulWidget {
  final String message;
  final Future<void> Function()? onRetry;

  const ErrorMessage({
    super.key,
    required this.message,
    this.onRetry,
  });

  @override
  State<ErrorMessage> createState() => _ErrorMessageState();
}

class _ErrorMessageState extends State<ErrorMessage> {
  bool _retrying = false;

  Future<void> _handleRetry() async {
    if (_retrying || widget.onRetry == null) return;
    setState(() => _retrying = true);
    try {
      await widget.onRetry!();
    } finally {
      if (mounted) {
        setState(() => _retrying = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: FDTheme.dangerSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: FDTheme.dangerBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.error_outline_rounded,
                  color: FDTheme.danger, size: 18),
              SizedBox(width: 8),
              Text(
                'Échec de communication',
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: FDTheme.dangerDark,
                  fontSize: 13,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            widget.message,
            style: const TextStyle(
              fontSize: 13,
              color: FDTheme.dangerDark,
              height: 1.45,
            ),
          ),
          if (widget.onRetry != null) ...[
            const SizedBox(height: 10),
            TextButton.icon(
              onPressed: _retrying ? null : _handleRetry,
              icon: _retrying
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: FDTheme.danger),
                    )
                  : const Icon(Icons.refresh_rounded,
                      size: 16, color: FDTheme.danger),
              label: Text(
                _retrying ? 'Tentative en cours...' : 'Réessayer',
                style: const TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: FDTheme.danger,
                ),
              ),
              style: TextButton.styleFrom(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                backgroundColor: FDTheme.surface,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                  side: const BorderSide(color: FDTheme.dangerBorder),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
