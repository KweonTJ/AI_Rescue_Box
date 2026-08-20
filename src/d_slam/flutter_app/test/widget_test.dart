import 'dart:async';
import 'dart:typed_data';

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
  Future<List<JsonMap>> listMissions() async => [for (final item in missionItems) {...item}];

  @override
  Future<JsonMap?> currentMission() async => current ?? initialCurrent;

  @override
  Future<JsonMap> selectMission(String missionId, int missionVersion) async {
    selectCalls += 1;
    current = _detail(missionId, missionVersion);
    return current!;
  }

  @override
  Future<JsonMap> analyze() async => {'analysis_mode': 'mock', 'result': <String, Object?>{}};

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

void main() {
  testWidgets('cold launch shows Mission Selector even with an active mission', (tester) async {
    final backend = _FakeBackend(
      missions: [_mission('mission-a', 3, active: true)],
      initialCurrent: _detail('mission-a', 3),
    );
    await _pumpApp(tester, backend);

    expect(find.text('구조도 선택'), findsOneWidget);
    expect(find.text('현재 사용 중'), findsOneWidget);
    expect(find.textContaining('현재 Mission ·'), findsNothing);
    expect(backend.selectCalls, 0);
  });

  testWidgets('empty state is explicit', (tester) async {
    await _pumpApp(tester, _FakeBackend());
    expect(find.text('Host에서 수신한 구조도가 없습니다.'), findsOneWidget);
  });

  testWidgets('Jetson disconnected state exposes API address and retry', (tester) async {
    final backend = _FakeBackend(failHealth: true);
    await _pumpApp(tester, backend);

    expect(find.text('Jetson 연결 실패'), findsOneWidget);
    expect(find.textContaining('192.168.50.1:8080'), findsOneWidget);
    expect(find.byKey(const Key('mission-selector-retry')), findsOneWidget);

    backend.failHealth = false;
    await tester.tap(find.byKey(const Key('mission-selector-retry')));
    await tester.pumpAndSettle();
    expect(backend.healthCalls, greaterThanOrEqualTo(2));
    expect(find.text('Host에서 수신한 구조도가 없습니다.'), findsOneWidget);
  });

  testWidgets('mission selection calls API and enters dashboard', (tester) async {
    final backend = _FakeBackend(missions: [_mission('mission-a', 3)]);
    await _pumpApp(tester, backend);

    expect(find.text('지하주차장 A'), findsOneWidget);
    await tester.tap(find.byKey(const Key('select-mission-a-v3')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('mission-select-confirm')));
    await tester.pumpAndSettle();

    expect(backend.selectCalls, 1);
    expect(find.textContaining('현재 Mission · mission-a · v3'), findsOneWidget);
    expect(find.byKey(const Key('choose-another-mission')), findsOneWidget);
  });

  testWidgets('operator can return to selector and switch missions', (tester) async {
    final backend = _FakeBackend(
      missions: [_mission('mission-a', 1), _mission('mission-b', 2)],
    );
    await _pumpApp(tester, backend);

    await tester.tap(find.byKey(const Key('select-mission-a-v1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('mission-select-confirm')));
    await tester.pumpAndSettle();
    expect(find.textContaining('현재 Mission · mission-a · v1'), findsOneWidget);

    await tester.tap(find.byKey(const Key('choose-another-mission')));
    await tester.pumpAndSettle();
    expect(find.text('구조도 선택'), findsOneWidget);

    await tester.tap(find.byKey(const Key('select-mission-b-v2')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('mission-select-confirm')));
    await tester.pumpAndSettle();
    expect(backend.selectCalls, 2);
    expect(find.textContaining('현재 Mission · mission-b · v2'), findsOneWidget);
  });
}
