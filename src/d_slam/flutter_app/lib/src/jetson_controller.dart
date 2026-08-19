import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

/// UI state for the API-only Jetson console.
///
/// Hardware ownership stays in the Python FastAPI process.  This controller
/// depends only on [JetsonBackend], which also makes the complete workflow
/// deterministic in widget tests.
typedef ArtifactLoader = Future<Uint8List> Function(String path);

final class JetsonController extends ChangeNotifier {
  JetsonController(
    this.backend, {
    this.apiBaseUri,
    ArtifactLoader? artifactLoader,
    this.autoRefreshInterval = const Duration(seconds: 3),
  }) : _artifactLoader = artifactLoader ?? _loaderFor(backend) {
    _eventSubscription = backend.events.listen(
      _onEvent,
      onError: (Object error) {
        webSocketConnected = false;
        _recordEvent('WebSocket 오류: ${_errorText(error)}');
        _notify();
      },
      onDone: () {
        webSocketConnected = false;
        _recordEvent('WebSocket 연결 종료');
        _notify();
      },
    );
  }

  final JetsonBackend backend;
  final Uri? apiBaseUri;
  final ArtifactLoader? _artifactLoader;
  final Duration autoRefreshInterval;
  StreamSubscription<ApiEvent>? _eventSubscription;
  Timer? _refreshTimer;
  bool _disposed = false;

  bool busy = false;
  String? activeOperation;
  String? error;
  JsonMap health = const {};
  JsonMap backendStatus = const {};
  List<JsonMap> missions = const [];
  JsonMap? selectedMission;
  JsonMap? currentResult;
  bool currentResultSendable = false;
  JsonMap? resultSendReceipt;
  JsonMap? preview;
  JsonMap? previewSendReceipt;
  JsonMap? approvedPlan;
  Uint8List? baseMapPng;
  Uint8List? previewPng;
  bool analysisWasMock = false;
  bool webSocketConnected = false;
  double transferProgress = 0;
  String progressStage = '대기';
  final List<String> eventLog = <String>[];

  String? get selectedMissionId {
    final detail = selectedMission;
    final manifest = _mapAt(detail, 'manifest');
    return _stringAt(manifest, const ['mission_id']) ??
        _stringAt(detail, const ['mission_id']);
  }

  int? get selectedMissionVersion {
    final detail = selectedMission;
    final manifest = _mapAt(detail, 'manifest');
    return _intAt(manifest, const ['mission_version', 'version']) ??
        _intAt(detail, const ['mission_version', 'version']);
  }

  JsonMap get providers => _mapAt(backendStatus, 'providers') ?? const {};
  JsonMap? get uwbProvider => _mapAt(providers, 'uwb');
  JsonMap? get liveMap => _mapAt(backendStatus, 'live_map');
  JsonMap get hardware => _mapAt(backendStatus, 'hardware') ?? const {};
  JsonMap get runtime => _mapAt(backendStatus, 'runtime') ?? const {};

  bool get isMockMode {
    final mode =
        _stringAt(backendStatus, const ['mode']) ??
        _stringAt(health, const ['mode']);
    return mode?.toLowerCase() == 'mock';
  }

  Future<void> initialise() => _run('초기 상태 확인', () async {
    final values = await Future.wait<JsonMap>([
      backend.health(),
      backend.status(),
    ]);
    health = unwrapEnvelope(values[0]);
    backendStatus = unwrapEnvelope(values[1]);
    missions = await backend.listMissions();
    await _loadServerCurrentMission();
    await _refreshSelectedArtifacts();
    _recordEvent('FastAPI 상태와 임무 ${missions.length}개를 불러왔습니다.');
    _startAutoRefresh();
  });

  Future<void> refresh() => _run('상태 새로고침', () async {
    health = unwrapEnvelope(await backend.health());
    backendStatus = unwrapEnvelope(await backend.status());
    missions = await backend.listMissions();
    await _loadServerCurrentMission();
    await _refreshSelectedArtifacts();
    _startAutoRefresh();
  });

  Future<void> selectMission(JsonMap mission) => _run('임무 선택', () async {
    final missionId = _stringAt(mission, const ['mission_id', 'id']);
    final missionVersion = _intAt(mission, const [
      'mission_version',
      'version',
    ]);
    if (missionId == null || missionVersion == null || missionVersion < 1) {
      throw const FormatException('임무 항목에 mission_id/version이 없습니다.');
    }
    final selected = unwrapEnvelope(
      await backend.selectMission(missionId, missionVersion),
    );
    _clearMissionArtifacts(clearSelection: true);
    selectedMission = selected;
    progressStage = '임무 선택됨';
    await _loadCurrentResult();
    approvedPlan = await _optionalObject(
      backend.currentApprovedPlan,
      key: 'plan',
    );
    await _loadBaseMapPng();
    backendStatus = unwrapEnvelope(await backend.status());
    await _loadCurrentPreview();
    missions = [
      for (final item in missions)
        {
          ...item,
          'active':
              _stringAt(item, const ['mission_id']) == missionId &&
              _intAt(item, const ['mission_version', 'version']) ==
                  missionVersion,
        },
    ];
    _recordEvent('임무 선택: $missionId v$missionVersion');
  });

  Future<void> runAnalysis() {
    final modeLabel = isMockMode ? 'Mock 분석' : '센서 분석';
    return _run(modeLabel, () async {
      _requireMission();
      transferProgress = 0;
      progressStage = '$modeLabel 중';
      final response = unwrapEnvelope(await backend.analyze());
      currentResult = _extractObject(response, 'result') ?? response;
      currentResultSendable = true;
      analysisWasMock = isMockMode;
      transferProgress = 1;
      progressStage = '$modeLabel 완료';
      _recordEvent(
        '$modeLabel 완료: result v${_intAt(currentResult, const ['result_version', 'version']) ?? '-'}',
      );
      backendStatus = unwrapEnvelope(await backend.status());
    });
  }

  Future<void> refreshCurrentResult() => _run('현재 분석 결과', () async {
    _requireMission();
    await _loadCurrentResult();
  });

  Future<void> sendResult() => _run('semantic_result 전송', () async {
    _requireMission();
    if (currentResult == null || !currentResultSendable) {
      throw StateError('전송할 semantic_result가 없습니다.');
    }
    transferProgress = 0;
    progressStage = '결과 전송 시작';
    resultSendReceipt = unwrapEnvelope(await backend.sendCurrentResult());
    transferProgress = 1;
    final transfer = resultSendReceipt?['transfer'];
    final simulated = transfer is Map && transfer['simulated'] == true;
    progressStage = simulated ? 'Mock · 무선 미전송' : '결과 전송 완료';
    _recordEvent(
      simulated
          ? 'semantic_result Mock 처리(무선 미전송)'
          : 'semantic_result UWB 전송 완료',
    );
  });

  Future<void> createPreview() => _run('Preview 생성', () async {
    _requireMission();
    preview = unwrapEnvelope(await backend.createPreview());
    await _loadPreviewPng();
    progressStage = 'Preview 생성 완료';
    _recordEvent('현재 SLAM map preview 생성 완료');
  });

  Future<void> sendCurrentPreview() => _run('Preview 전송', () async {
    _requireMission();
    if (preview == null) {
      throw StateError('먼저 preview를 생성하세요.');
    }
    transferProgress = 0;
    progressStage = 'Preview 전송 시작';
    previewSendReceipt = unwrapEnvelope(await backend.sendPreview());
    final response = previewSendReceipt!;
    if (_looksLikePreview(response)) preview = {...?preview, ...response};
    await _loadCurrentPreview();
    transferProgress = 1;
    final transfer = response['transfer'];
    final simulated = transfer is Map && transfer['simulated'] == true;
    progressStage = simulated ? 'Mock · 무선 미전송' : 'Preview 전송 완료';
    _recordEvent(
      simulated ? 'map_preview Mock 처리(무선 미전송)' : 'map_preview UWB 전송 완료',
    );
  });

  Future<void> refreshApprovedPlan() => _run('승인 계획 확인', () async {
    _requireMission();
    final response = unwrapEnvelope(await backend.currentApprovedPlan());
    approvedPlan = _extractObject(response, 'plan') ?? response;
    _recordEvent('Host approved_plan을 확인했습니다.');
  });

  void clearError() {
    error = null;
    _notify();
  }

  void _startAutoRefresh() {
    if (autoRefreshInterval <= Duration.zero || _refreshTimer != null) return;
    _refreshTimer = Timer.periodic(
      autoRefreshInterval,
      (_) => unawaited(_periodicRefresh()),
    );
  }

  Future<void> _periodicRefresh() async {
    if (_disposed || busy) return;
    try {
      backendStatus = unwrapEnvelope(await backend.status());
      missions = await backend.listMissions();
      await _loadServerCurrentMission();
      await _refreshSelectedArtifacts();
      _notify();
    } on Object catch (caught) {
      _recordEvent('주기 갱신 실패: ${_errorText(caught)}');
      _notify();
    }
  }

  Future<void> _refreshSelectedArtifacts() async {
    if (selectedMissionId == null) return;
    await _loadCurrentResult();
    final plan = await _optionalObject(
      backend.currentApprovedPlan,
      key: 'plan',
    );
    if (plan != null) approvedPlan = plan;
    await _loadCurrentPreview();
  }

  Future<void> _loadCurrentResult() async {
    try {
      final response = unwrapEnvelope(await backend.currentResult());
      currentResult = _extractObject(response, 'result') ?? response;
      currentResultSendable = response['sendable'] != false;
      final transfer = response['transfer'];
      if (transfer is Map) {
        resultSendReceipt = {
          'state': response['state'],
          'transfer': requireJsonMap(transfer),
        };
      }
    } on Object {
      currentResult = null;
      currentResultSendable = false;
    }
  }

  Future<void> _loadBaseMapPng() async {
    final base = _mapAt(selectedMission, 'base_map');
    final path = _stringAt(base, const ['download_url']);
    if (path == null || _artifactLoader == null) return;
    baseMapPng = await _loadPng(path, 'base map');
  }

  Future<void> _loadPreviewPng() async {
    final path = _stringAt(preview, const ['download_url']);
    if (path == null || _artifactLoader == null) return;
    previewPng = await _loadPng(path, 'map preview');
  }

  Future<void> _loadCurrentPreview() async {
    final value = await backend.currentPreview();
    preview = value;
    if (value == null) {
      previewPng = null;
      return;
    }
    await _loadPreviewPng();
  }

  Future<void> _loadServerCurrentMission() async {
    final detail = await backend.currentMission();
    if (detail != null) {
      final manifest = _mapAt(detail, 'manifest');
      final missionId = _stringAt(manifest, const ['mission_id']);
      final missionVersion = _intAt(manifest, const ['mission_version']);
      if (missionId == null || missionVersion == null) return;
      final identityChanged =
          selectedMissionId != missionId ||
          selectedMissionVersion != missionVersion;
      if (identityChanged) {
        _clearMissionArtifacts(clearSelection: true);
      }
      selectedMission = detail;
      missions = [
        for (final item in missions)
          {
            ...item,
            'active':
                _stringAt(item, const ['mission_id']) == missionId &&
                _intAt(item, const ['mission_version', 'version']) ==
                    missionVersion,
          },
      ];
      await _loadBaseMapPng();
      return;
    }
    _clearMissionArtifacts(clearSelection: true);
    missions = [
      for (final item in missions) {...item, 'active': false},
    ];
  }

  void _clearMissionArtifacts({required bool clearSelection}) {
    if (clearSelection) selectedMission = null;
    currentResult = null;
    currentResultSendable = false;
    resultSendReceipt = null;
    preview = null;
    previewSendReceipt = null;
    approvedPlan = null;
    baseMapPng = null;
    previewPng = null;
    analysisWasMock = false;
    transferProgress = 0;
    progressStage = '대기';
  }

  Future<Uint8List> _loadPng(String path, String name) async {
    final bytes = await _artifactLoader!(path);
    const signature = <int>[137, 80, 78, 71, 13, 10, 26, 10];
    if (bytes.length < signature.length ||
        !listEquals(bytes.sublist(0, signature.length), signature)) {
      throw FormatException('$name 응답이 PNG가 아닙니다.');
    }
    return bytes;
  }

  static ArtifactLoader? _loaderFor(JetsonBackend backend) {
    return backend.downloadArtifact;
  }

  Future<void> _run(String operation, Future<void> Function() action) async {
    if (busy) return;
    busy = true;
    activeOperation = operation;
    error = null;
    _notify();
    try {
      await action();
    } on Object catch (caught) {
      error = _errorText(caught);
      _recordEvent('$operation 실패: $error');
    } finally {
      busy = false;
      activeOperation = null;
      _notify();
    }
  }

  Future<JsonMap?> _optionalObject(
    Future<JsonMap> Function() load, {
    required String key,
  }) async {
    try {
      final value = unwrapEnvelope(await load());
      return _extractObject(value, key) ?? value;
    } on Object {
      return null;
    }
  }

  void _requireMission() {
    if (selectedMissionId == null || selectedMissionVersion == null) {
      throw StateError('먼저 임무와 버전을 선택하세요.');
    }
  }

  void _onEvent(ApiEvent event) {
    final progress = event.payload['progress'];
    if (progress is num && progress.isFinite) {
      transferProgress = progress.toDouble().clamp(0, 1);
    }
    if (event.eventType == 'events.connected' ||
        event.eventType == 'events.heartbeat') {
      webSocketConnected = true;
    }
    if (event.eventType.endsWith('.started')) {
      transferProgress = 0;
    } else if (event.eventType.endsWith('.completed')) {
      transferProgress = 1;
    }
    progressStage = event.eventType;
    _recordEvent('${event.eventType} · ${_shortJson(event.payload)}');
    if (event.eventType == 'approved_plan.applied') {
      unawaited(_reloadApprovedPlanFromEvent());
    }
    if (event.eventType.startsWith('mission.') ||
        event.eventType.startsWith('analysis.') ||
        event.eventType.startsWith('preview.') ||
        event.eventType == 'perception.candidates') {
      unawaited(_synchroniseFromEvent(event.eventType));
    }
    _notify();
  }

  Future<void> _synchroniseFromEvent(String eventType) async {
    if (_disposed || busy) return;
    try {
      backendStatus = unwrapEnvelope(await backend.status());
      if (eventType.startsWith('mission.')) {
        missions = await backend.listMissions();
        await _loadServerCurrentMission();
      }
      if (eventType == 'analysis.completed') {
        final result = await _optionalObject(
          backend.currentResult,
          key: 'result',
        );
        if (result != null) currentResult = result;
      }
      if (eventType.startsWith('preview.')) await _loadCurrentPreview();
      _notify();
    } on Object catch (caught) {
      _recordEvent('이벤트 상태 동기화 실패: ${_errorText(caught)}');
      _notify();
    }
  }

  Future<void> _reloadApprovedPlanFromEvent() async {
    if (_disposed) return;
    try {
      final value = await _optionalObject(
        backend.currentApprovedPlan,
        key: 'plan',
      );
      if (_disposed) return;
      if (value != null) approvedPlan = value;
      _notify();
    } on Object catch (caught) {
      if (_disposed) return;
      _recordEvent('승인 계획 이벤트 동기화 실패: ${_errorText(caught)}');
      _notify();
    }
  }

  void _recordEvent(String value) {
    eventLog.insert(0, value);
    if (eventLog.length > 100) eventLog.removeRange(100, eventLog.length);
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _refreshTimer?.cancel();
    _refreshTimer = null;
    unawaited(_eventSubscription?.cancel());
    _eventSubscription = null;
    unawaited(backend.close());
    super.dispose();
  }
}

JsonMap unwrapEnvelope(JsonMap value) {
  final data = value['data'];
  return data is Map ? requireJsonMap(data, context: 'response data') : value;
}

JsonMap? _extractObject(JsonMap value, String key) {
  final nested = value[key];
  return nested is Map ? requireJsonMap(nested, context: key) : null;
}

JsonMap? _mapAt(JsonMap? value, String key) {
  if (value == null) return null;
  return _extractObject(value, key);
}

String? _stringAt(JsonMap? value, List<String> keys) {
  if (value == null) return null;
  for (final key in keys) {
    final item = value[key];
    if (item is String && item.trim().isNotEmpty) return item;
  }
  return null;
}

int? _intAt(JsonMap? value, List<String> keys) {
  if (value == null) return null;
  for (final key in keys) {
    final item = value[key];
    if (item is num) return item.toInt();
  }
  return null;
}

String _errorText(Object error) {
  if (error is ApiFailure) return error.message;
  return error.toString().replaceFirst(
    RegExp(r'^[A-Za-z]+(?:Error|Exception): '),
    '',
  );
}

String _shortJson(Object? value) {
  final encoded = jsonEncode(value);
  return encoded.length <= 140 ? encoded : '${encoded.substring(0, 137)}…';
}

bool _looksLikePreview(JsonMap value) =>
    value.containsKey('map_version') ||
    value.containsKey('artifact_version') ||
    value.containsKey('byte_size');
