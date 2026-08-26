import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart' show Key, Size;
import 'package:flutter_test/flutter_test.dart';
import 'package:rescue_api_client/rescue_api_client.dart';
import 'package:rescue_api_client/src/host_backend_adapter.dart';
import 'package:rescue_api_client/src/host_console_app.dart';
import 'package:rescue_api_client/src/host_controller.dart';

final _onePixelPng = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAAXNSR0IArs4c6QAA'
  'AARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAPSURBVBhXY/j/'
  '/z8DAwMADvgC/gZH5egAAAAASUVORK5CYII=',
);

class _FakeTransport implements RescueTransport {
  _FakeTransport({this.activeMission = false});

  final bool activeMission;
  final List<String> postPaths = [];
  final List<String> bytePaths = [];

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
        if (activeMission)
          'active_mission': {
            'mission_id': 'mission-active',
            'mission_version': 3,
          },
      };
    }
    if (path == 'api/v1/missions/mission-active/3') {
      return {
        'mission_id': 'mission-active',
        'mission_version': 3,
        'mission_name': '자동 동기화 임무',
        'base_map': {'filename': 'base-map.png', 'width': 400, 'height': 200},
        'coordinate_transform': {
          'image_origin': {'x': 100.0, 'y': 50.0},
          'meters_per_pixel': 0.5,
          'rotation_radians': 0.0,
          'invert_y': true,
        },
      };
    }
    if (path == 'api/v1/missions/mission-active/3/results') {
      return <Object?>[];
    }
    if (path.endsWith('/missions')) return <Object?>[];
    return <String, Object?>{};
  }

  @override
  Future<Uint8List> getBytes(
    String path, {
    Map<String, Object?> query = const {},
  }) async {
    bytePaths.add(path);
    if (path == 'api/v1/missions/mission-active/3/base-map') {
      return _onePixelPng;
    }
    return Uint8List(0);
  }

  @override
  Future<Object?> post(
    String path, {
    Object? body,
    Map<String, Object?> query = const {},
  }) async {
    postPaths.add(path);
    return <String, Object?>{};
  }

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
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final controller = HostController(RestHostBackend(_FakeTransport()));
    await tester.pumpWidget(RescueHostConsoleApp(controller: controller));
    await tester.pump();

    expect(find.byType(RescueHostConsoleApp), findsOneWidget);
    expect(find.text('AI Rescue Box · Host'), findsOneWidget);
    expect(find.text('관제'), findsWidgets);
    expect(find.text('분석·검토'), findsOneWidget);
    expect(find.text('JPEG/PNG 구조도 업로드'), findsNothing);
    expect(find.text('임무 생성 및 UWB 전송'), findsNothing);

    await tester.tap(find.text('분석·검토'));
    await tester.pump();
    expect(find.byKey(const Key('semantic-map-fallback')), findsOneWidget);
    expect(find.byKey(const Key('semantic-map-base-image')), findsNothing);
    expect(find.byKey(const Key('semantic-map-overlay')), findsNothing);
  });

  testWidgets(
    'ACTIVE Mission sync hydrates its base map and aligned review canvas without reactivation',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 900);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final transport = _FakeTransport(activeMission: true);
      final controller = HostController(HostRestBackend(transport));
      await tester.pumpWidget(RescueHostConsoleApp(controller: controller));
      await tester.pumpAndSettle();

      expect(controller.missionId, 'mission-active');
      expect(controller.missionVersion, 3);
      expect(controller.imageWidth, 400);
      expect(controller.imageHeight, 200);
      expect(controller.mapBytes, _onePixelPng);
      expect(
        transport.bytePaths,
        contains('api/v1/missions/mission-active/3/base-map'),
      );
      expect(
        transport.postPaths.where(
          (path) => path.endsWith('/activate') || path.endsWith('/send'),
        ),
        isEmpty,
      );
      final transformed = controller.semanticPoint({'x': 10.0, 'y': 5.0});
      expect(transformed?.x, 120.0);
      expect(transformed?.y, 40.0);

      await tester.tap(find.text('분석·검토'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('semantic-map-base-image')), findsOneWidget);
      expect(find.byKey(const Key('semantic-map-overlay')), findsOneWidget);
      expect(find.byKey(const Key('semantic-map-fallback')), findsNothing);
      final imageSize = tester.getSize(
        find.byKey(const Key('semantic-map-base-image')),
      );
      final overlaySize = tester.getSize(
        find.byKey(const Key('semantic-map-overlay')),
      );
      expect(overlaySize, imageSize);
      expect(imageSize.width / imageSize.height, closeTo(2.0, 0.001));
      expect(find.text('RESCUE MAP LAYERS'), findsOneWidget);
      expect(find.text('경로 검토'), findsOneWidget);

      tester.view.physicalSize = const Size(1600, 1000);
      await tester.pumpAndSettle();
      final resizedImage = tester.getSize(
        find.byKey(const Key('semantic-map-base-image')),
      );
      final resizedOverlay = tester.getSize(
        find.byKey(const Key('semantic-map-overlay')),
      );
      expect(resizedImage, isNot(imageSize));
      expect(resizedOverlay, resizedImage);
      expect(resizedImage.width / resizedImage.height, closeTo(2.0, 0.001));
    },
  );
}
