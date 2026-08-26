import 'dart:typed_data';

import 'package:rescue_api_client/rescue_api_client.dart';

/// Host-only artifact/status capabilities which are intentionally still served
/// by FastAPI. Flutter never receives a ROS or serial handle.
abstract interface class HostAssetBackend {
  Future<JsonMap> reconnect();
  Future<Uint8List> normalizedMap(String mapId);
  Future<Uint8List> missionBaseMap(String missionId, int missionVersion);
  Future<List<int>> listPreviews(String missionId, int missionVersion);
  Future<Uint8List> preview(
    String missionId,
    int missionVersion,
    int previewVersion,
  );
  Future<JsonMap> previewMetadata(
    String missionId,
    int missionVersion,
    int previewVersion,
  );
}

final class HostRestBackend implements HostBackend, HostAssetBackend {
  HostRestBackend(this.transport) : _delegate = RestHostBackend(transport);

  final RescueTransport transport;
  final RestHostBackend _delegate;

  @override
  Stream<ApiEvent> get events => _delegate.events;

  @override
  Future<JsonMap> health() => _delegate.health();

  @override
  Future<JsonMap> status() => _delegate.status();

  @override
  Future<JsonMap> uploadMap(String filename, Uint8List bytes) =>
      _delegate.uploadMap(filename, bytes);

  @override
  Future<JsonMap> createMission(JsonMap draft) =>
      _delegate.createMission(draft);

  @override
  Future<List<JsonMap>> listMissions() => _delegate.listMissions();

  @override
  Future<JsonMap> getMission(String missionId, int missionVersion) =>
      _delegate.getMission(missionId, missionVersion);

  @override
  Future<JsonMap> activateMission(String missionId, int missionVersion) =>
      _delegate.activateMission(missionId, missionVersion);

  @override
  Future<JsonMap> sendMission(String missionId, int missionVersion) =>
      _delegate.sendMission(missionId, missionVersion);

  @override
  Future<JsonMap> getOperation(String operationId) =>
      _delegate.getOperation(operationId);

  @override
  Future<List<JsonMap>> listResults(String missionId, int missionVersion) =>
      _delegate.listResults(missionId, missionVersion);

  @override
  Future<JsonMap> getResult(
    String missionId,
    int missionVersion,
    int resultVersion,
  ) => _delegate.getResult(missionId, missionVersion, resultVersion);

  @override
  Future<JsonMap> applyReviewCommand(
    String missionId,
    int missionVersion,
    int resultVersion,
    JsonMap command, {
    int? expectedRevision,
  }) => _delegate.applyReviewCommand(
    missionId,
    missionVersion,
    resultVersion,
    command,
    expectedRevision: expectedRevision,
  );

  @override
  Future<JsonMap> buildApprovedPlan(
    String missionId,
    int missionVersion,
    int resultVersion,
    int planVersion, {
    int? expectedRevision,
  }) => _delegate.buildApprovedPlan(
    missionId,
    missionVersion,
    resultVersion,
    planVersion,
    expectedRevision: expectedRevision,
  );

  @override
  Future<JsonMap> listApprovedPlans(
    String missionId,
    int missionVersion,
    int resultVersion,
  ) => _delegate.listApprovedPlans(missionId, missionVersion, resultVersion);

  @override
  Future<JsonMap> currentApprovedPlan(
    String missionId,
    int missionVersion,
    int resultVersion,
  ) => _delegate.currentApprovedPlan(missionId, missionVersion, resultVersion);

  @override
  Future<JsonMap> sendApprovedPlan(
    String missionId,
    int missionVersion,
    int resultVersion,
    int planVersion,
  ) => _delegate.sendApprovedPlan(
    missionId,
    missionVersion,
    resultVersion,
    planVersion,
  );

  @override
  Future<JsonMap> publishFinalMap() => _delegate.publishFinalMap();

  @override
  Future<JsonMap> reconnect() async => requireJsonMap(
    await transport.post('api/v1/status/reconnect'),
    context: 'reconnect response',
  );

  @override
  Future<Uint8List> normalizedMap(String mapId) =>
      transport.getBytes('api/v1/maps/$mapId/content');

  @override
  Future<Uint8List> missionBaseMap(String missionId, int missionVersion) =>
      transport.getBytes('api/v1/missions/$missionId/$missionVersion/base-map');

  String _previewRoot(String missionId, int missionVersion) =>
      'api/v1/missions/$missionId/$missionVersion/previews';

  @override
  Future<List<int>> listPreviews(String missionId, int missionVersion) async {
    final response = requireJsonMap(
      await transport.get(_previewRoot(missionId, missionVersion)),
      context: 'preview list',
    );
    final values = response['versions'];
    if (values is! List) throw const FormatException('versions must be a list');
    return values.whereType<num>().map((value) => value.toInt()).toList();
  }

  @override
  Future<Uint8List> preview(
    String missionId,
    int missionVersion,
    int previewVersion,
  ) => transport.getBytes(
    '${_previewRoot(missionId, missionVersion)}/$previewVersion',
  );

  @override
  Future<JsonMap> previewMetadata(
    String missionId,
    int missionVersion,
    int previewVersion,
  ) async => requireJsonMap(
    await transport.get(
      '${_previewRoot(missionId, missionVersion)}/$previewVersion/metadata',
    ),
    context: 'preview metadata',
  );

  @override
  Future<void> close() => _delegate.close();
}
