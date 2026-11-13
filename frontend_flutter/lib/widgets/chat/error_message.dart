import 'package:flutter/material.dart';

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
        color: const Color(0xFFFEF2F2),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFFECACA)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.error_outline_rounded, color: Color(0xFFDC2626), size: 18),
              SizedBox(width: 8),
              Text(
                'Échec de communication',
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF991B1B),
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
              color: Color(0xFF7F1D1D),
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
                      child: CircularProgressIndicator(strokeWidth: 2, color: Color(0xFFDC2626)),
                    )
                  : const Icon(Icons.refresh_rounded, size: 16, color: Color(0xFFDC2626)),
              label: Text(
                _retrying ? 'Tentative en cours...' : 'Réessayer',
                style: const TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFFDC2626),
                ),
              ),
              style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                backgroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                  side: const BorderSide(color: Color(0xFFFECACA)),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

