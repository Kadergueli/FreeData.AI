import 'dart:typed_data';

void triggerPdfDownload(Uint8List bytes, String filename) {
  // Plateforme non-web : téléchargement navigateur non applicable en test VM.
}

void triggerFileDownload(Uint8List bytes, String filename, String mimeType) {
  // Browser downloads are unavailable on non-web platforms and in VM tests.
}
