import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/widgets.dart' show Key;
import 'package:flutter_test/flutter_test.dart';
import 'package:rescue_api_client/rescue_api_client.dart';
import 'package:rescue_api_client/src/jetson_app.dart';
import 'package:rescue_api_client/src/jetson_controller.dart';

JsonMap _mission(String id, int version, {bool active = false}) => {
      'mission_id': id,
      'mission_version': version,
      'mission_name': id == 'mission-a' ? '지하주차장 A' : '지하주차장 B',
      'verified': true,
      'verification_status': 'verified',
      'received_at': '2026-08-20T12:00:00Z',
      'active': active,
    };

JsonMap _detail(String id, int version) => {
      'mission_id': id,
      'mission_version': version,
      'manifest': {
        'mission_id': id,
        'mission_version': version,
        'mission_name': id == 'mission-a' ? '지하주차장 A' : '지하주차장 B',
      },
      'verification': {'status': 'verified'},
    };

class _FakeBackend implements JetsonBackend {
  _FakeBackend({
    List<JsonMap>? missions,
    this.initialCurrent,
    this.failHealth = false,
  }) : missionItems = missions ?? <JsonMap>[];

  final List<JsonMap> missionItems;
  final JsonMap? initialCurrent;
  bool failHealth;
  JsonMap? current;
  int selectCalls = 0;
  int healthCalls = 0;

  @override
  Stream<ApiEvent> get events => const Stream<ApiEvent>.empty();

  @override
  Future<JsonMap> health() async {
    healthCalls += 1;
    if (failHealth) throw StateError('connection refused');
    return {'status': 'ok', 'mode': 'mock'};
  }

  @override
  Future<JsonMap> status() async => {
        'mode': 'mock',
        'providers': <String, Object?>{},
      };

  @override
  Future<List<JsonMap>> listMissions() async => [
        for (final item in missionItems) {...item},
      ];

  @override
  Future<JsonMap> getMission(String missionId, int missionVersion) async =>
      _detail(missionId, missionVersion);

  @override
  Future<JsonMap?> currentMission() async => current ?? initialCurrent;

  @override
  Future<JsonMap> storeTabletMission(
    JsonMap draft, {
    String? filename,
    Uint8List? bytes,
    int? reuseFromVersion,
  }) async {
    final id = (draft['mission_id'] as String?) ?? 'mission-new';
    final versions = missionItems
        .where((item) => item['mission_id'] == id)
        .map((item) => (item['mission_version'] as num).toInt());
    final version = versions.isEmpty ? 1 : versions.reduce((a, b) => a > b ? a : b) + 1;
    missionItems.add(_mission(id, version));
    return {..._detail(id, version), 'state': 'STORED'};
  }

  @override
  Future<JsonMap> selectMission(String missionId, int missionVersion) async {
    selectCalls += 1;
    current = _detail(missionId, missionVersion);
    for (final item in missionItems) {
      item['active'] =
          item['mission_id'] == missionId && item['mission_version'] == missionVersion;
    }
    return current!;
  }

  @override
  Future<JsonMap> analyze() async => {
        'analysis_mode': 'mock',
        'result': <String, Object?>{},
      };

  @override
  Future<JsonMap> currentResult() async => throw StateError('no result');

  @override
  Future<JsonMap> sendCurrentResult() async => {'state': 'not_wired'};

  @override
  Future<JsonMap> createPreview({bool force = false}) async => <String, Object?>{};

  @override
  Future<JsonMap?> currentPreview() async => null;

  @override
  Future<JsonMap> sendPreview({bool force = false}) async => {'state': 'not_wired'};

  @override
  Future<JsonMap> currentApprovedPlan() async => throw StateError('no plan');

  @override
  Future<Uint8List> downloadArtifact(String path) async => Uint8List(0);

  @override
  Future<void> close() async {}
}

Future<void> _pumpApp(WidgetTester tester, _FakeBackend backend) async {
  final controller = JetsonController(
    backend,
    apiBaseUri: Uri.parse('http://192.168.50.1:8080'),
    autoRefreshInterval: const Duration(days: 1),
  );
  await tester.pumpWidget(RescueJetsonApp(controller: controller));
  await tester.pumpAndSettle();
}

Future<void> _openActive(WidgetTester tester) async {
  await tester.tap(find.text('ACTIVE').last);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('cold launch starts in Mission management even with ACTIVE mission', (tester) async {
    final backend = _FakeBackend(
      missions: [_mission('mission-a', 3, active: true)],
      initialCurrent: _detail('mission-a', 3),
    );
    await _pumpApp(tester, backend);

    expect(find.text('Mission 관리'), findsWidgets);
    expect(find.text('새 Mission 만들기'), findsOneWidget);
    expect(find.text('기존 Mission 수정'), findsOneWidget);
    expect(backend.selectCalls, 0);
  });

  testWidgets('ACTIVE empty state is explicit', (tester) async {
    await _pumpApp(tester, _FakeBackend());
    await _openActive(tester);
    expect(find.text('실제 사용할 Mission 선택'), findsOneWidget);
    expect(find.text('저장된 Mission이 없습니다.'), findsOneWidget);
  });

  testWidgets('Jetson disconnected Mission management exposes retry', (tester) async {
    final backend = _FakeBackend(failHealth: true);
    await _pumpApp(tester, backend);

    expect(find.textContaining('Jetson 연결을 먼저 확인하세요.'), findsOneWidget);
    expect(find.text('재시도'), findsOneWidget);

    backend.failHealth = false;
    await tester.tap(find.text('재시도'));
    await tester.pumpAndSettle();
    expect(backend.healthCalls, greaterThanOrEqualTo(2));
  });

  testWidgets('ACTIVE selection calls API but remains separate from operations', (tester) async {
    final backend = _FakeBackend(missions: [_mission('mission-a', 3)]);
    await _pumpApp(tester, backend);
    await _openActive(tester);

    expect(find.text('지하주차장 A'), findsOneWidget);
    await tester.tap(find.byKey(const Key('select-mission-a-v3')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('mission-select-confirm')));
    await tester.pumpAndSettle();

    expect(backend.selectCalls, 1);
    expect(find.text('실제 사용할 Mission 선택'), findsOneWidget);
    expect(find.text('현재 ACTIVE'), findsOneWidget);
  });

  testWidgets('operator can enter operations after ACTIVE selection', (tester) async {
    final backend = _FakeBackend(missions: [_mission('mission-b', 2)]);
    await _pumpApp(tester, backend);
    await _openActive(tester);

    await tester.tap(find.byKey(const Key('select-mission-b-v2')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('mission-select-confirm')));
    await tester.pumpAndSettle();

    await tester.tap(find.text('운영').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('현재 Mission · mission-b · v2'), findsOneWidget);
    expect(find.byKey(const Key('choose-another-mission')), findsOneWidget);
  });
}
