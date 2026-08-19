import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rescue_api_client/rescue_api_client.dart';
import 'package:rescue_api_client/src/host_app.dart';
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
  testWidgets('Host app builds its first screen with a mock backend', (
    tester,
  ) async {
    final controller = HostController(RestHostBackend(_FakeTransport()));
    await tester.pumpWidget(RescueHostApp(controller: controller));
    await tester.pump();

    expect(find.byType(RescueHostApp), findsOneWidget);
    expect(find.text('AI Rescue Box · Host'), findsOneWidget);
    expect(find.text('임무'), findsOneWidget);
  });
}
