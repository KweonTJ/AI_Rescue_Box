import 'package:file_picker/file_picker.dart';

import 'host_controller.dart';

final class PlatformMapFilePicker implements MapFilePicker {
  @override
  Future<PickedMap?> pick() async {
    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['jpg', 'jpeg', 'png'],
      allowMultiple: false,
      withData: true,
    );
    if (result == null || result.files.isEmpty) return null;
    final file = result.files.single;
    final bytes = file.bytes;
    if (bytes == null) {
      throw StateError('선택한 파일을 메모리로 읽지 못했습니다.');
    }
    return PickedMap(filename: file.name, bytes: bytes);
  }
}
