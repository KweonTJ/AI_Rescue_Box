import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'host_backend_adapter.dart';

enum MapEditMode { robotStart, scaleFirst, scaleSecond, entrance }

@immutable
final class MapPoint {
  const MapPoint(this.x, this.y);
  final double x;
  final double y;

  JsonMap toJson() => {'x': x, 'y': y};
}

@immutable
final class PickedMap {
  const PickedMap({required this.filename, required this.bytes});
  final String filename;
  final Uint8List bytes;
}

abstract interface class MapFilePicker {
  Future<PickedMap?> pick();
}

final class HostController extends ChangeNotifier {
  HostController(this.backend) {
    _eventSubscription = backend.events.listen(
      _onEvent,
      onError: (Object value) {
        if (_disposed) return;
        webSocketState = '재연결 중';
        eventLog.insert(0, 'WebSocket: $value');
        _notify();
      },
      onDone: () {
        if (_disposed) return;
        webSocketState = '연결 종료';
        _notify();
      },
    );
  }

  static const semanticLayers = <String>[
    'slam_preview',
    'robot_pose',
    'robot_trajectory',
    'victim_candidates',
    'confirmed_victims',
    'obstacles',
    'risk_zones',
    'explored_areas',
    'unknown_areas',
    'entry_routes',
    'return_routes',
    'team_recommendations',
    'safe_waiting_points',
  ];

  final HostBackend backend;
  StreamSubscription<ApiEvent>? _eventSubscription;
  bool _disposed = false;

  HostAssetBackend? get _assets =>
      backend is HostAssetBackend ? backend as HostAssetBackend : null;

  bool busy = false;
  String? error;
  JsonMap health = const {};
  JsonMap backendStatus = const {};
  JsonMap? uploadReceipt;
  Uint8List? mapBytes;
  String? mapFilename;
  int imageWidth = 1;
  int imageHeight = 1;
  MapEditMode editMode = MapEditMode.robotStart;
  MapPoint? robotStart;
  double robotYawRadians = 0;
  bool yawSpecified = false;
  MapPoint? scaleFirst;
  MapPoint? scaleSecond;
  double scaleDistanceMeters = 1;
  double? _loadedMetersPerPixel;
  final List<MapPoint> entrances = [];
  String missionName = '현장 임무';
  String missionId = '';
  int missionVersion = 1;
  int teamCount = 1;
  int availableRescuers = 2;
  String missionNotes = '';
  int missionFormRevision = 0;
  List<JsonMap> missions = const [];
  JsonMap? currentMission;
  bool existingMissionSelected = false;
  List<JsonMap> results = const [];
  JsonMap? currentResult;
  JsonMap? originalSemantic;
  int currentResultVersion = 0;
  List<JsonMap> approvedPlans = const [];
  int latestApprovedPlanVersion = 0;
  JsonMap? approvedPlan;
  Uint8List? previewBytes;
  JsonMap? previewMetadata;
  int previewVersion = 0;
  final Set<String> visibleLayers = semanticLayers.toSet();
  double transferProgress = 0;
  String transferArtifact = '';
  String transferStage = '대기';
  bool frameAck = false;
  bool remoteSaved = false;
  bool applicationAck = false;
  JsonMap? activeOperation;
  String webSocketState = '이벤트 연결 대기';
  int lastEventSequence = 0;
  final List<String> eventLog = [];

  double? get metersPerPixel {
    final first = scaleFirst;
    final second = scaleSecond;
    if (first == null || second == null || scaleDistanceMeters <= 0) {
      return _loadedMetersPerPixel;
    }
    final pixels = math.sqrt(
      math.pow(second.x - first.x, 2) + math.pow(second.y - first.y, 2),
    );
    if (pixels <= 0) return null;
    return scaleDistanceMeters / pixels;
  }

  bool get missionReady =>
      uploadReceipt != null &&
      robotStart != null &&
      yawSpecified &&
      metersPerPixel != null &&
      entrances.isNotEmpty &&
      missionName.trim().isNotEmpty;

  JsonMap get reviewedSemantic => _unwrapSemantic(currentResult);

  JsonMap get bridgeStatus {
    final nested = backendStatus['bridge'];
    return nested is Map ? requireJsonMap(nested) : const {};
  }

  bool get canUndo => currentResult?['can_undo'] == true;
  bool get canRedo => currentResult?['can_redo'] == true;
  int get reviewRevision =>
      _intValue(currentResult ?? const {}, const ['revision']) ?? 0;

  Future<void> initialise() async {
    await _run(() async {
      final values = await Future.wait([backend.health(), backend.status()]);
      health = values[0];
      backendStatus = values[1];
      missions = await backend.listMissions();
    });
  }

  Future<void> refreshStatus() async {
    await _run(() async {
      backendStatus = await backend.status();
      health = await backend.health();
      missions = await backend.listMissions();
    });
  }

  Future<void> reconnectBridge() async {
    await _run(() async {
      final assets = _assets;
      if (assets == null) {
        throw StateError('이 backend는 reconnect API를 제공하지 않습니다.');
      }
      final response = await assets.reconnect();
      eventLog.insert(0, 'Bridge 재연결 요청: $response');
      backendStatus = await backend.status();
    });
  }

  void clearError() {
    error = null;
    _notify();
  }

  Future<void> chooseAndUpload(MapFilePicker picker) async {
    final picked = await picker.pick();
    if (picked != null) await uploadMap(picked);
  }

  Future<void> uploadMap(PickedMap picked) async {
    await _run(() async {
      final receipt = await backend.uploadMap(picked.filename, picked.bytes);
      uploadReceipt = receipt;
      final mapId = _stringValue(receipt, const ['map_id']);
      mapBytes = mapId != null && _assets != null
          ? await _assets!.normalizedMap(mapId)
          : picked.bytes;
      mapFilename = picked.filename;
      imageWidth = _positiveInt(receipt, const [
        'width',
        'transmission_width',
        'image_width',
      ], fallback: 1);
      imageHeight = _positiveInt(receipt, const [
        'height',
        'transmission_height',
        'image_height',
      ], fallback: 1);
      robotStart = null;
      yawSpecified = false;
      scaleFirst = null;
      scaleSecond = null;
      _loadedMetersPerPixel = null;
      entrances.clear();
      currentMission = null;
      existingMissionSelected = false;
      currentResult = null;
      originalSemantic = null;
      approvedPlans = const [];
      latestApprovedPlanVersion = 0;
      approvedPlan = null;
      previewBytes = null;
      eventLog.insert(0, '구조도 정규화·업로드 완료: ${picked.filename}');
    });
  }

  void setEditMode(MapEditMode value) {
    editMode = value;
    _notify();
  }

  void applyMapTap(MapPoint value) {
    switch (editMode) {
      case MapEditMode.robotStart:
        robotStart = value;
        yawSpecified = false;
      case MapEditMode.scaleFirst:
        scaleFirst = value;
        scaleSecond = null;
        _loadedMetersPerPixel = null;
        editMode = MapEditMode.scaleSecond;
      case MapEditMode.scaleSecond:
        scaleSecond = value;
      case MapEditMode.entrance:
        entrances.add(value);
    }
    _notify();
  }

  void setYaw(double value) {
    if (value.isFinite) {
      robotYawRadians = value;
      yawSpecified = true;
    }
    _notify();
  }

  void setRobotPose(MapPoint start, MapPoint heading) {
    robotStart = start;
    robotYawRadians = math.atan2(heading.y - start.y, heading.x - start.x);
    yawSpecified = true;
    _notify();
  }

  void clearYaw() {
    yawSpecified = false;
    _notify();
  }

  void setScaleDistance(double value) {
    if (value.isFinite && value > 0) scaleDistanceMeters = value;
    _notify();
  }

  void clearEntrances() {
    entrances.clear();
    _notify();
  }

  void updateMissionFields({
    String? name,
    String? id,
    int? teams,
    int? rescuers,
    int? version,
    String? notes,
  }) {
    if (name != null) missionName = name;
    if (id != null) missionId = id;
    if (teams != null && teams >= 0) teamCount = teams;
    if (rescuers != null && rescuers >= 0) availableRescuers = rescuers;
    if (version != null && version > 0) missionVersion = version;
    if (notes != null) missionNotes = notes;
    _notify();
  }

  JsonMap missionDraft() {
    final receipt = uploadReceipt;
    final start = robotStart;
    final scale = metersPerPixel;
    if (receipt == null || start == null || scale == null) {
      throw StateError('지도, robot 시작점, 두 점 축척이 필요합니다.');
    }
    if (!yawSpecified) {
      throw StateError('초기 yaw를 명시적으로 지정해야 합니다.');
    }
    if (entrances.isEmpty) throw StateError('출입구를 하나 이상 지정해야 합니다.');
    if (teamCount == 0 && availableRescuers == 0) {
      throw StateError('구조팀 또는 구조인원이 한 명 이상 필요합니다.');
    }
    return {
      'map_id':
          receipt['map_id'] ??
          receipt['map_token'] ??
          receipt['upload_id'] ??
          receipt['id'],
      if (missionId.trim().isNotEmpty) 'mission_id': missionId.trim(),
      'mission_version': missionVersion,
      'mission_name': missionName.trim(),
      'robot_start_image': start.toJson(),
      'initial_yaw': robotYawRadians,
      'meters_per_pixel': scale,
      'entrances': [for (final entrance in entrances) entrance.toJson()],
      'available_teams': teamCount,
      'available_rescuers': availableRescuers,
      'notes': missionNotes,
    };
  }

  Future<void> selectMission(JsonMap summary) async {
    final id = _stringValue(summary, const ['mission_id']);
    final version = _intValue(summary, const ['mission_version', 'version']);
    if (id == null || version == null) return;
    await _run(() async {
      final manifest = await backend.getMission(id, version);
      await backend.activateMission(id, version);
      currentMission = manifest;
      _applyManifest(manifest);
      final assets = _assets;
      if (assets != null) {
        mapBytes = await assets.missionBaseMap(id, version);
        await _loadLatestPreview(assets);
      }
      results = await backend.listResults(id, version);
      currentResult = null;
      originalSemantic = null;
      currentResultVersion = 0;
      approvedPlans = const [];
      latestApprovedPlanVersion = 0;
      approvedPlan = null;
      existingMissionSelected = true;
      eventLog.insert(0, '기존 임무 선택: $id v$version');
    });
  }

  /// Hydrates an already-ACTIVE mission for monitoring without activating or
  /// sending it again.
  Future<void> hydrateActiveMission(JsonMap manifest) async {
    final id = _stringValue(manifest, const ['mission_id']);
    final version = _intValue(manifest, const ['mission_version', 'version']);
    if (id == null || version == null || version < 1) {
      throw const FormatException('active mission manifest lacks id/version');
    }

    final missionChanged = missionId != id || missionVersion != version;
    currentMission = manifest;
    _applyManifest(manifest);
    existingMissionSelected = true;
    if (missionChanged) {
      currentResult = null;
      originalSemantic = null;
      currentResultVersion = 0;
      approvedPlans = const [];
      latestApprovedPlanVersion = 0;
      approvedPlan = null;
      previewBytes = null;
      previewMetadata = null;
      previewVersion = 0;
    }

    final assets = _assets;
    mapBytes = null;
    _notify();
    if (assets == null) return;
    mapBytes = await assets.missionBaseMap(id, version);
    _notify();
  }

  void prepareNextVersion() {
    if (missionId.isEmpty) return;
    var latest = missionVersion;
    for (final item in missions) {
      if (_stringValue(item, const ['mission_id']) == missionId) {
        latest = math.max(
          latest,
          _intValue(item, const ['mission_version', 'version']) ?? 0,
        );
      }
    }
    missionVersion = latest + 1;
    missionFormRevision += 1;
    existingMissionSelected = false;
    currentResult = null;
    originalSemantic = null;
    currentResultVersion = 0;
    approvedPlans = const [];
    latestApprovedPlanVersion = 0;
    approvedPlan = null;
    final sourceMapId = _stringValue(currentMission ?? const {}, const [
      'source_map_id',
    ]);
    if (sourceMapId != null) {
      uploadReceipt = {
        'map_id': sourceMapId,
        'width': imageWidth,
        'height': imageHeight,
      };
    } else if (uploadReceipt == null) {
      error = '이전 버전에는 원본 upload ID가 없습니다. 구조도를 다시 업로드하세요.';
    }
    eventLog.insert(0, '다음 임무 버전 준비: $missionId v$missionVersion');
    _notify();
  }

  Future<void> resendSelectedMission() async {
    if (missionId.isEmpty || missionVersion <= 0) return;
    await _run(() async {
      _resetTransferState();
      final operation = await backend.sendMission(missionId, missionVersion);
      await _waitForOperation(operation);
      transferProgress = 1;
      eventLog.insert(0, '기존 임무 재전송 완료: $missionId v$missionVersion');
    });
  }

  Future<void> createAndSendMission() async {
    await _run(() async {
      final created = await backend.createMission(missionDraft());
      currentMission = created;
      missionId = _stringValue(created, const ['mission_id']) ?? missionId;
      missionVersion =
          _intValue(created, const ['mission_version', 'version']) ??
          missionVersion;
      missionFormRevision += 1;
      if (missionId.isEmpty || missionVersion <= 0) {
        throw const FormatException('mission create response lacks id/version');
      }
      _resetTransferState();
      final operation = await backend.sendMission(missionId, missionVersion);
      await _waitForOperation(operation);
      transferProgress = 1;
      missions = await backend.listMissions();
      existingMissionSelected = true;
      eventLog.insert(0, '임무 전송 완료: $missionId v$missionVersion');
    });
  }

  Future<void> refreshResults() async {
    if (missionId.isEmpty || missionVersion <= 0) return;
    await _run(() async {
      results = await backend.listResults(missionId, missionVersion);
      if (results.isEmpty) {
        currentResult = null;
        originalSemantic = null;
        currentResultVersion = 0;
        approvedPlans = const [];
        latestApprovedPlanVersion = 0;
        approvedPlan = null;
        return;
      }
      final latest = results.reduce((first, second) {
        final firstVersion =
            _intValue(first, const ['result_version', 'version']) ?? 0;
        final secondVersion =
            _intValue(second, const ['result_version', 'version']) ?? 0;
        return secondVersion > firstVersion ? second : first;
      });
      final version =
          _intValue(latest, const ['result_version', 'version']) ??
          results.length;
      await _loadResult(version);
      final assets = _assets;
      if (assets != null) await _loadLatestPreview(assets);
    });
  }

  Future<void> selectResultVersion(int version) async {
    await _run(() => _loadResult(version));
  }

  Future<void> _loadResult(int version) async {
    final state = await backend.getResult(missionId, missionVersion, version);
    _setReviewState(state, resetLegacyOriginal: true);
    currentResultVersion = version;
    await _loadApprovedPlans(version);
  }

  void _setReviewState(JsonMap state, {required bool resetLegacyOriginal}) {
    currentResult = state;
    final raw = state['original_semantic_result'];
    if (raw is Map) {
      originalSemantic = Map<String, dynamic>.from(requireJsonMap(raw));
    } else if (resetLegacyOriginal || originalSemantic == null) {
      originalSemantic = Map<String, dynamic>.from(_unwrapSemantic(state));
    }
  }

  Future<void> _loadApprovedPlans(int resultVersion) async {
    final catalog = await backend.listApprovedPlans(
      missionId,
      missionVersion,
      resultVersion,
    );
    approvedPlans = jsonObjectList(catalog['items'] ?? const []);
    latestApprovedPlanVersion =
        _intValue(catalog, const ['latest_plan_version']) ?? 0;
    JsonMap? latest;
    var latestForResult = 0;
    for (final plan in approvedPlans) {
      final version = _intValue(plan, const [
        'approved_plan_version',
        'plan_version',
        'artifact_version',
      ]);
      if (version != null && version > latestForResult) {
        latestForResult = version;
        latest = plan;
      }
    }
    latestApprovedPlanVersion = math.max(
      latestApprovedPlanVersion,
      latestForResult,
    );
    approvedPlan = latest;
  }

  Future<void> applyReview(JsonMap command) async {
    final result = currentResult;
    if (result == null) return;
    final resultVersion =
        _intValue(result, const ['result_version', 'version']) ??
        currentResultVersion;
    if (resultVersion <= 0) throw StateError('result version is unavailable');
    await _run(() async {
      final state = await backend.applyReviewCommand(
        missionId,
        missionVersion,
        resultVersion,
        command,
        expectedRevision: reviewRevision,
      );
      _setReviewState(state, resetLegacyOriginal: false);
      approvedPlan = null;
    });
  }

  Future<void> copyRecommendedAssignments() => applyReview({
    'action': 'set_team_assignments',
    'assignments': _jsonList(
      (originalSemantic ?? const {})['team_recommendations'],
    ),
  });

  Future<void> publishFinalMap() async {
    final result = currentResult;
    if (result == null) return;
    final resultVersion =
        _intValue(result, const ['result_version', 'version']) ??
        currentResultVersion;
    if (resultVersion <= 0) throw StateError('result version is unavailable');
    await _run(() async {
      final published = await backend.publishFinalMap();
      final planValue = published['approved_plan'];
      if (planValue is! Map) {
        throw const FormatException('publish response lacks approved_plan');
      }
      final plan = requireJsonMap(planValue);
      approvedPlan = plan;
      final actualVersion =
          _intValue(plan, const [
            'approved_plan_version',
            'plan_version',
            'version',
          ]) ??
          latestApprovedPlanVersion;
      latestApprovedPlanVersion = math.max(
        latestApprovedPlanVersion,
        actualVersion,
      );
      approvedPlans = [
        ...approvedPlans.where(
          (item) =>
              _intValue(item, const [
                'approved_plan_version',
                'plan_version',
                'artifact_version',
              ]) !=
              actualVersion,
        ),
        plan,
      ];
      eventLog.insert(0, '최종 지도 publish 완료: v$actualVersion');
    });
  }

  void setLayerVisible(String layer, bool visible) {
    visible ? visibleLayers.add(layer) : visibleLayers.remove(layer);
    _notify();
  }

  MapPoint? semanticPoint(Object? value) {
    if (value is! Map) return null;
    var point = requireJsonMap(value);
    for (final key in const [
      'map_position',
      'position',
      'map_point',
      'center',
      'current_position',
      'recommended_position',
    ]) {
      final nested = point[key];
      if (nested is Map) {
        point = requireJsonMap(nested);
        break;
      }
    }
    final x = point['x'] ?? point['map_x'];
    final y = point['y'] ?? point['map_y'];
    if (x is! num || y is! num) return null;
    final transform = currentMission?['coordinate_transform'];
    if (transform is! Map) return MapPoint(x.toDouble(), y.toDouble());
    final data = requireJsonMap(transform);
    final originValue = data['image_origin'];
    if (originValue is! Map) return MapPoint(x.toDouble(), y.toDouble());
    final origin = requireJsonMap(originValue);
    final ox = origin['x'];
    final oy = origin['y'];
    final scale = data['meters_per_pixel'];
    final rotation = data['rotation_radians'] ?? 0;
    if (ox is! num || oy is! num || scale is! num || rotation is! num) {
      return null;
    }
    final cosine = math.cos(rotation.toDouble());
    final sine = math.sin(rotation.toDouble());
    final dx = cosine * x.toDouble() + sine * y.toDouble();
    var dy = -sine * x.toDouble() + cosine * y.toDouble();
    if (data['invert_y'] != false) dy = -dy;
    return MapPoint(
      ox.toDouble() + dx / scale.toDouble(),
      oy.toDouble() + dy / scale.toDouble(),
    );
  }

  MapPoint missionPointFromImage(MapPoint imagePoint) {
    final transformValue = currentMission?['coordinate_transform'];
    if (transformValue is! Map) return imagePoint;
    final transform = requireJsonMap(transformValue);
    final originValue = transform['image_origin'];
    if (originValue is! Map) return imagePoint;
    final origin = requireJsonMap(originValue);
    final ox = origin['x'];
    final oy = origin['y'];
    final scale = transform['meters_per_pixel'];
    final rotation = transform['rotation_radians'] ?? 0;
    if (ox is! num || oy is! num || scale is! num || rotation is! num) {
      return imagePoint;
    }
    final scaledX = (imagePoint.x - ox.toDouble()) * scale.toDouble();
    var scaledY = (imagePoint.y - oy.toDouble()) * scale.toDouble();
    if (transform['invert_y'] != false) scaledY = -scaledY;
    final cosine = math.cos(rotation.toDouble());
    final sine = math.sin(rotation.toDouble());
    return MapPoint(
      cosine * scaledX - sine * scaledY,
      sine * scaledX + cosine * scaledY,
    );
  }

  String _nextHostId(String prefix, Iterable<String> existing) {
    final used = existing.toSet();
    var index = 1;
    while (used.contains('$prefix-$index')) {
      index += 1;
    }
    return '$prefix-$index';
  }

  Future<String?> addVictimAtImage(MapPoint imagePoint) async {
    if (currentResult == null) return null;
    final semantic = reviewedSemantic;
    final ids = <String>[];
    for (final layer in const ['victim_candidates', 'confirmed_victims']) {
      final values = semantic[layer];
      if (values is! List) continue;
      for (final raw in values.whereType<Map>()) {
        final item = requireJsonMap(raw);
        final id = item['victim_id'] ?? item['detection_id'] ?? item['id'];
        if (id != null) ids.add(id.toString());
      }
    }
    final id = _nextHostId('host-victim', ids);
    final point = missionPointFromImage(imagePoint);
    await applyReview({
      'action': 'add_victim',
      'victim_id': id,
      'x': point.x,
      'y': point.y,
    });
    return id;
  }

  Future<void> moveVictimToImage(String victimId, MapPoint imagePoint) async {
    final point = missionPointFromImage(imagePoint);
    await applyReview({
      'action': 'set_victim_position',
      'victim_id': victimId,
      'x': point.x,
      'y': point.y,
    });
  }

  Future<void> deleteVictim(String victimId, {required bool hostAdded}) async {
    if (hostAdded) {
      await applyReview({
        'action': 'remove_added_victim',
        'victim_id': victimId,
      });
      return;
    }
    await applyReview({
      'action': 'set_victim_status',
      'victim_id': victimId,
      'status': 'excluded',
    });
  }

  Future<String?> addTeamAtImage(MapPoint imagePoint) async {
    if (currentResult == null) return null;
    final values = reviewedSemantic['team_recommendations'];
    final ids = <String>[];
    if (values is List) {
      for (final raw in values.whereType<Map>()) {
        final item = requireJsonMap(raw);
        final id = item['team_id'] ?? item['id'];
        if (id != null) ids.add(id.toString());
      }
    }
    final id = _nextHostId('host-team', ids);
    final point = missionPointFromImage(imagePoint);
    await applyReview({
      'action': 'upsert_team_assignment',
      'assignment': {
        'team_id': id,
        'label': '구조인력',
        'position': {'x': point.x, 'y': point.y},
        'victim_id': null,
        'route_id': null,
        'source': 'host_user',
      },
    });
    return id;
  }

  Future<void> moveTeamToImage(JsonMap item, MapPoint imagePoint) async {
    final id = item['team_id'] ?? item['id'];
    if (id == null) return;
    final point = missionPointFromImage(imagePoint);
    final assignment = <String, dynamic>{...item};
    assignment['team_id'] = id.toString();
    assignment['position'] = {'x': point.x, 'y': point.y};
    await applyReview({
      'action': 'upsert_team_assignment',
      'assignment': assignment,
    });
  }

  Future<void> removeTeam(String teamId) =>
      applyReview({'action': 'remove_team_assignment', 'team_id': teamId});

  Future<String?> addSafePointAtImage(MapPoint imagePoint) async {
    if (currentResult == null) return null;
    final values = reviewedSemantic['safe_waiting_points'];
    final ids = <String>[];
    if (values is List) {
      for (final raw in values.whereType<Map>()) {
        final item = requireJsonMap(raw);
        final id = item['waiting_id'] ?? item['safe_waiting_id'] ?? item['id'];
        if (id != null) ids.add(id.toString());
      }
    }
    final id = _nextHostId('host-safe', ids);
    final point = missionPointFromImage(imagePoint);
    await applyReview({
      'action': 'add_safe_waiting_point',
      'waiting_id': id,
      'x': point.x,
      'y': point.y,
    });
    return id;
  }

  Future<void> moveSafePointToImage(
    String waitingId,
    MapPoint imagePoint,
  ) async {
    final point = missionPointFromImage(imagePoint);
    await applyReview({
      'action': 'update_safe_waiting_point',
      'waiting_id': waitingId,
      'x': point.x,
      'y': point.y,
    });
  }

  Future<void> removeSafePoint(String waitingId) => applyReview({
    'action': 'remove_safe_waiting_point',
    'waiting_id': waitingId,
  });

  List<MapPoint>? get previewCorners {
    final metadata = previewMetadata;
    if (metadata == null) return null;
    final resolution = metadata['resolution_m_per_cell'];
    final width = metadata['source_width'];
    final height = metadata['source_height'];
    final originX = metadata['origin_x_m'];
    final originY = metadata['origin_y_m'];
    if (resolution is! num ||
        width is! num ||
        height is! num ||
        originX is! num ||
        originY is! num) {
      return null;
    }
    final topY = originY.toDouble() + height.toDouble() * resolution.toDouble();
    final rightX =
        originX.toDouble() + width.toDouble() * resolution.toDouble();
    final points = [
      {'x': originX.toDouble(), 'y': topY},
      {'x': rightX, 'y': topY},
      {'x': originX.toDouble(), 'y': originY.toDouble()},
    ];
    final converted = points.map(semanticPoint).toList();
    return converted.every((value) => value != null)
        ? converted.cast<MapPoint>()
        : null;
  }

  Future<void> _loadLatestPreview(HostAssetBackend assets) async {
    final versions = await assets.listPreviews(missionId, missionVersion);
    if (versions.isEmpty) {
      previewBytes = null;
      previewMetadata = null;
      previewVersion = 0;
      return;
    }
    versions.sort();
    previewVersion = versions.last;
    final values = await Future.wait<Object>([
      assets.preview(missionId, missionVersion, previewVersion),
      assets.previewMetadata(missionId, missionVersion, previewVersion),
    ]);
    previewBytes = values[0] as Uint8List;
    previewMetadata = values[1] as JsonMap;
  }

  void _applyManifest(JsonMap manifest) {
    missionId = _stringValue(manifest, const ['mission_id']) ?? missionId;
    missionVersion =
        _intValue(manifest, const ['mission_version', 'version']) ??
        missionVersion;
    missionName =
        _stringValue(manifest, const ['mission_name', 'name']) ?? missionName;
    missionNotes = manifest['notes']?.toString() ?? '';
    teamCount = _intValue(manifest, const ['available_teams']) ?? 0;
    availableRescuers = _intValue(manifest, const ['available_rescuers']) ?? 0;
    final base = manifest['base_map'];
    final baseMap = base is Map ? requireJsonMap(base) : manifest;
    imageWidth = _positiveInt(baseMap, const [
      'width',
      'base_map_width',
    ], fallback: 1);
    imageHeight = _positiveInt(baseMap, const [
      'height',
      'base_map_height',
    ], fallback: 1);
    mapFilename =
        _stringValue(baseMap, const ['filename', 'base_map_filename']) ??
        '$missionId-v$missionVersion';
    final transformValue = manifest['coordinate_transform'];
    final transform = transformValue is Map
        ? requireJsonMap(transformValue)
        : const <String, dynamic>{};
    final originValue =
        transform['robot_start_image'] ?? transform['image_origin'];
    if (originValue is Map) {
      final origin = requireJsonMap(originValue);
      if (origin['x'] is num && origin['y'] is num) {
        robotStart = MapPoint(
          (origin['x'] as num).toDouble(),
          (origin['y'] as num).toDouble(),
        );
      }
    }
    final yaw = transform['initial_image_yaw'];
    if (yaw is num) {
      robotYawRadians = yaw.toDouble();
      yawSpecified = true;
    } else {
      yawSpecified = false;
    }
    final scale = manifest['meters_per_pixel'] ?? transform['meters_per_pixel'];
    _loadedMetersPerPixel = scale is num ? scale.toDouble() : null;
    scaleFirst = null;
    scaleSecond = null;
    entrances.clear();
    final values = manifest['entrances'];
    if (values is List) {
      for (final item in values.whereType<Map>()) {
        final entrance = requireJsonMap(item);
        final x = entrance['image_x'];
        final y = entrance['image_y'];
        if (x is num && y is num) {
          entrances.add(MapPoint(x.toDouble(), y.toDouble()));
        }
      }
    }
    final mapId = _stringValue(manifest, const ['source_map_id']);
    uploadReceipt = mapId == null
        ? null
        : {'map_id': mapId, 'width': imageWidth, 'height': imageHeight};
    missionFormRevision += 1;
  }

  void _resetTransferState() {
    transferProgress = 0;
    transferArtifact = '';
    transferStage = '전송 준비';
    frameAck = false;
    remoteSaved = false;
    applicationAck = false;
    activeOperation = null;
  }

  Future<JsonMap> _waitForOperation(JsonMap initial) async {
    var operation = initial;
    activeOperation = operation;
    final operationId = _stringValue(operation, const ['operation_id']);
    if (operationId == null) return operation;
    final deadline = DateTime.now().add(const Duration(minutes: 2));
    while (true) {
      activeOperation = operation;
      _applyOperationResult(operation);
      _notify();
      final state = _stringValue(operation, const ['state']) ?? '';
      if (state == 'succeeded') return operation;
      if (state == 'failed' || state == 'cancelled') {
        throw StateError(
          _stringValue(operation, const ['error']) ??
              'backend operation $operationId $state',
        );
      }
      if (DateTime.now().isAfter(deadline)) {
        throw TimeoutException('backend operation $operationId timed out');
      }
      await Future<void>.delayed(const Duration(milliseconds: 250));
      operation = await backend.getOperation(operationId);
    }
  }

  void _applyOperationResult(JsonMap operation) {
    final resultValue = operation['result'];
    if (resultValue is! Map) return;
    final result = requireJsonMap(resultValue);
    final artifacts = <JsonMap>[];
    for (final key in const ['base_map', 'mission_manifest']) {
      final value = result[key];
      if (value is Map) artifacts.add(requireJsonMap(value));
    }
    if (artifacts.isEmpty) artifacts.add(result);
    frameAck = artifacts.every((value) => value['frame_ack'] == true);
    remoteSaved = artifacts.every((value) => value['remote_saved'] == true);
    applicationAck = artifacts.every(
      (value) => value['application_ack'] == true,
    );
    if (operation['state'] == 'succeeded') {
      transferProgress = 1;
      transferStage = '완료';
    }
  }

  Future<void> _run(Future<void> Function() operation) async {
    if (_disposed || busy) return;
    busy = true;
    error = null;
    _notify();
    try {
      await operation();
    } on Object catch (caught) {
      error = caught.toString();
      eventLog.insert(0, '오류: $caught');
    } finally {
      busy = false;
      _notify();
    }
  }

  void _onEvent(ApiEvent event) {
    if (_disposed) return;
    webSocketState = '연결됨 · 이벤트 수신';
    lastEventSequence = event.sequence;
    eventLog.insert(
      0,
      '#${event.sequence} ${event.eventType}: ${event.payload}',
    );
    if (event.eventType == 'bridge.status') {
      backendStatus = {...backendStatus, 'bridge': event.payload};
    }
    if (event.eventType.startsWith('operation.')) {
      activeOperation = event.payload;
    }
    if (event.eventType == 'operation.progress') {
      final progress = event.payload['progress'];
      if (progress is num) transferProgress = progress.toDouble().clamp(0, 1);
      transferArtifact =
          event.payload['artifact']?.toString() ?? transferArtifact;
      transferStage = event.payload['stage']?.toString() ?? transferStage;
    }
    if (event.eventType == 'operation.completed') {
      _applyOperationResult(event.payload);
    }
    if ({
          'result.received',
          'result.duplicate_received',
        }.contains(event.eventType) &&
        missionId.isNotEmpty &&
        missionVersion > 0) {
      unawaited(refreshResults());
    }
    _notify();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  static JsonMap _unwrapSemantic(JsonMap? value) {
    if (value == null) return const {};
    for (final key in const ['reviewed_result', 'semantic_result', 'result']) {
      final nested = value[key];
      if (nested is Map) return _unwrapSemantic(requireJsonMap(nested));
    }
    return value;
  }

  static List<JsonMap> _jsonList(Object? value) => value is List
      ? value.whereType<Map>().map(requireJsonMap).toList(growable: false)
      : const [];

  static int _positiveInt(
    JsonMap value,
    List<String> keys, {
    required int fallback,
  }) {
    final result = _intValue(value, keys);
    return result != null && result > 0 ? result : fallback;
  }

  static int? _intValue(JsonMap value, List<String> keys) {
    for (final key in keys) {
      final item = value[key];
      if (item is num) return item.toInt();
      if (item is String) {
        final parsed = int.tryParse(item);
        if (parsed != null) return parsed;
      }
    }
    return null;
  }

  static String? _stringValue(JsonMap value, List<String> keys) {
    for (final key in keys) {
      final item = value[key];
      if (item is String && item.isNotEmpty) return item;
    }
    return null;
  }

  @override
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    unawaited(_eventSubscription?.cancel());
    _eventSubscription = null;
    unawaited(backend.close());
    super.dispose();
  }
}
