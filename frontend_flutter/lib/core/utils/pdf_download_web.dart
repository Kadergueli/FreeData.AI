// ignore: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';

void triggerFileDownload(Uint8List bytes, String filename, String mimeType) {
  final blob = html.Blob([bytes], mimeType);
  final url = html.Url.createObjectUrlFromBlob(blob);
  final anchor = html.AnchorElement(href: url)
    ..setAttribute('download', filename)
    ..style.display = 'none';
  html.document.body?.append(anchor);
  anchor.click();
  anchor.remove();
  // Allow the browser to begin consuming the Blob before releasing its URL.
  Timer(const Duration(seconds: 1), () => html.Url.revokeObjectUrl(url));
}

void triggerPdfDownload(Uint8List bytes, String filename) {
  triggerFileDownload(bytes, filename, 'application/pdf');
}
