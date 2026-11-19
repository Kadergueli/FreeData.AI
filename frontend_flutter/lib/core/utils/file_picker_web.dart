// ignore: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:async';
// ignore: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:html' as html;
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

Future<PickedDocumentFile?> pickUserDocumentFile() async {
  final input = html.FileUploadInputElement()
    ..accept =
        '.pdf,.csv,.txt,.md,.json,application/pdf,text/csv,text/plain,text/markdown,application/json';
  input.click();

  final completer = Completer<PickedDocumentFile?>();
  StreamSubscription<html.Event>? sub;
  sub = input.onChange.listen((_) {
    sub?.cancel();
    final files = input.files;
    if (files == null || files.isEmpty) {
      if (!completer.isCompleted) completer.complete(null);
      return;
    }
    final file = files.first;
    final reader = html.FileReader();
    reader.onLoadEnd.listen((_) {
      if (completer.isCompleted) return;
      final res = reader.result;
      if (res is ByteBuffer) {
        completer.complete(
          PickedDocumentFile(
            name: file.name,
            bytes: res.asUint8List(),
            mimeType: file.type.isNotEmpty ? file.type : null,
          ),
        );
      } else if (res is Uint8List) {
        completer.complete(
          PickedDocumentFile(
            name: file.name,
            bytes: res,
            mimeType: file.type.isNotEmpty ? file.type : null,
          ),
        );
      } else {
        completer.complete(null);
      }
    });
    reader.onError.listen((_) {
      if (!completer.isCompleted) completer.complete(null);
    });
    reader.readAsArrayBuffer(file);
  });

  return completer.future.timeout(
    const Duration(minutes: 3),
    onTimeout: () => null,
  );
}
