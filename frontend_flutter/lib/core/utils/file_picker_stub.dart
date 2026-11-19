import 'dart:typed_data';

class PickedDocumentFile {
  final String name;
  final Uint8List bytes;
  final String? mimeType;

  const PickedDocumentFile({
    required this.name,
    required this.bytes,
    this.mimeType,
  });
}

Future<PickedDocumentFile?> pickUserDocumentFile() async => null;
