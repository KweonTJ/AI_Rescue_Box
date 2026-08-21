import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rescue_api_client/rescue_api_client.dart';
import 'package:rescue_api_client/src/host_console_app.dart';
import 'package:rescue_api_client/src/host_controller.dart';

class _FakeTransport implements RescueTransport {
  @override
  Stream<ApiEvent> get events => const Stream<ApiEvent>.empty();

  @override
  Future<Object?> get(
    String path, {
    Map<String, Object?> query = const {},
  }) async {
    if (path.endsWith('/health')) {
      return {'ok': true, 'service': 'ai-rescue-box-host-api'};
    }
    if (path.endsWith('/status')) {
      return {
        'bridge': {'state': 'mock'},
      };
    }
    if (path.endsWith('/missions')) return <Object?>[];
    return <String, Object?>{};
  }

  @override
  Future<Uint8List> getBytes(
    String path, {
    Map<String, Object?> query = const {},
  }) async => Uint8List(0);

  @override
  Future<Object?> post(
    String path, {
    Object? body,
    Map<String, Object?> query = const {},
  }) async => <String, Object?>{};

  @override
  Future<JsonMap> upload(
    String path, {
    required String filename,
    required Uint8List bytes,
    Map<String, Object?> query = const {},
  }) async => <String, Object?>{};

  @override
  Future<void> close() async {}
}

void main() {
  testWidgets('Host starts as monitoring console without floorplan upload', (
    tester,
  ) async {
    final controller = HostController(RestHostBackend(_FakeTransport()));
    await tester.pumpWidget(RescueHostConsoleApp(controller: controller));
    await tester.pump();

    expect(find.byType(RescueHostConsoleApp), findsOneWidget);
    expect(find.text('AI Rescue Box · Host'), findsOneWidget);
    expect(find.text('관제'), findsOneWidget);
    expect(find.text('분석·검토'), findsOneWidget);
    expect(find.text('JPEG/PNG 구조도 업로드'), findsNothing);
    expect(find.text('임무 생성 및 UWB 전송'), findsNothing);
  });
}
