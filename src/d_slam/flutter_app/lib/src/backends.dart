import 'dart:convert';
import 'dart:typed_data';

import 'api_client.dart';
import 'models.dart';

abstract interface class HostBackend {
  Stream<ApiEvent> get events;
  Future<JsonMap> health();
  Future<JsonMap> status();
  Future<JsonMap> uploadMap(String filename, Uint8List bytes);
  Future<JsonMap> createMission(JsonMap draft);
  Future<List<JsonMap>> listMissions();
  Future<JsonMap> getMission(String missionId, int missionVersion);
  Future<JsonMap> activateMission(String missionId, int missionVersion);
  Future<JsonMap> sendMission(String missionId, int missionVersion);
  Future<JsonMap> getOperation(String operationId);
  Future<List<JsonMap>> listResults(String missionId, int missionVersion);
  Future<JsonMap> getResult(String missionId, int missionVersion, int resultVersion);
  Future<JsonMap> applyReviewCommand(String missionId, int missionVersion, int resultVersion, JsonMap command, {int? expectedRevision});
  Future<JsonMap> buildApprovedPlan(String missionId, int missionVersion, int resultVersion, int planVersion, {int? expectedRevision});
  Future<JsonMap> listApprovedPlans(String missionId, int missionVersion, int resultVersion);
  Future<JsonMap> currentApprovedPlan(String missionId, int missionVersion, int resultVersion);
  Future<JsonMap> sendApprovedPlan(String missionId, int missionVersion, int resultVersion, int planVersion);
  Future<void> close();
}

final class RestHostBackend implements HostBackend {
  RestHostBackend(this.transport);
  final RescueTransport transport;
  @override Stream<ApiEvent> get events => transport.events;
  Future<JsonMap> _getObject(String path, {Map<String, Object?> query = const {}}) async => _object(await transport.get(path, query: query));
  Future<JsonMap> _postObject(String path, [Object? body]) async => _object(await transport.post(path, body: body));
  static JsonMap _object(Object? value) { final object = requireJsonMap(value); final data = object['data']; return data is Map ? requireJsonMap(data) : object; }
  @override Future<JsonMap> health() => _getObject('api/v1/health');
  @override Future<JsonMap> status() => _getObject('api/v1/status');
  @override Future<JsonMap> uploadMap(String filename, Uint8List bytes) => transport.upload('api/v1/maps', filename: filename, bytes: bytes);
  @override Future<JsonMap> createMission(JsonMap draft) => _postObject('api/v1/missions', draft);
  @override Future<List<JsonMap>> listMissions() async { final value = await transport.get('api/v1/missions'); if (value is List) return jsonObjectList(value); final object = _object(value); return jsonObjectList(object['items'] ?? object['missions'] ?? const []); }
  @override Future<JsonMap> getMission(String missionId, int missionVersion) => _getObject('api/v1/missions/$missionId/$missionVersion');
  @override Future<JsonMap> activateMission(String missionId, int missionVersion) => _postObject('api/v1/missions/$missionId/$missionVersion/activate');
  @override Future<JsonMap> sendMission(String missionId, int missionVersion) => _postObject('api/v1/missions/$missionId/$missionVersion/send');
  @override Future<JsonMap> getOperation(String operationId) => _getObject('api/v1/operations/$operationId');
  String _resultRoot(String missionId, int missionVersion) => 'api/v1/missions/$missionId/$missionVersion/results';
  @override Future<List<JsonMap>> listResults(String missionId, int missionVersion) async { final value = await transport.get(_resultRoot(missionId, missionVersion)); if (value is List) return jsonObjectList(value); final object = _object(value); return jsonObjectList(object['items'] ?? object['results'] ?? const []); }
  @override Future<JsonMap> getResult(String missionId, int missionVersion, int resultVersion) => _postObject('${_resultRoot(missionId, missionVersion)}/$resultVersion/load');
  @override Future<JsonMap> applyReviewCommand(String missionId, int missionVersion, int resultVersion, JsonMap command, {int? expectedRevision}) => _postObject('api/v1/missions/$missionId/$missionVersion/reviews/$resultVersion/commands', {'command': command['action'] ?? command['command'], 'arguments': Map<String, dynamic>.from(command)..remove('action')..remove('command'), 'expected_revision': ?expectedRevision});
  @override Future<JsonMap> buildApprovedPlan(String missionId, int missionVersion, int resultVersion, int planVersion, {int? expectedRevision}) => _postObject('api/v1/missions/$missionId/$missionVersion/reviews/$resultVersion/plans', {'plan_version': planVersion, 'expected_revision': ?expectedRevision});
  String _planRoot(String missionId, int missionVersion, int resultVersion) => 'api/v1/missions/$missionId/$missionVersion/reviews/$resultVersion/plans';
  @override Future<JsonMap> listApprovedPlans(String missionId, int missionVersion, int resultVersion) => _getObject(_planRoot(missionId, missionVersion, resultVersion));
  @override Future<JsonMap> currentApprovedPlan(String missionId, int missionVersion, int resultVersion) => _getObject('${_planRoot(missionId, missionVersion, resultVersion)}/current');
  @override Future<JsonMap> sendApprovedPlan(String missionId, int missionVersion, int resultVersion, int planVersion) => _postObject('${_planRoot(missionId, missionVersion, resultVersion)}/$planVersion/send');
  @override Future<void> close() => transport.close();
}

abstract interface class JetsonBackend {
  Stream<ApiEvent> get events;
  Future<JsonMap> health();
  Future<JsonMap> status();
  Future<List<JsonMap>> listMissions();
  Future<JsonMap> getMission(String missionId, int missionVersion);
  Future<JsonMap?> currentMission();
  Future<JsonMap> storeTabletMission(
    JsonMap draft, {
    String? filename,
    Uint8List? bytes,
    int? reuseFromVersion,
  });
  Future<JsonMap> selectMission(String missionId, int missionVersion);
  Future<JsonMap> analyze();
  Future<JsonMap> currentResult();
  Future<JsonMap> sendCurrentResult();
  Future<JsonMap> createPreview({bool force = false});
  Future<JsonMap?> currentPreview();
  Future<JsonMap> sendPreview({bool force = false});
  Future<JsonMap> currentApprovedPlan();
  Future<Uint8List> downloadArtifact(String path);
  Future<void> close();
}

final class RestJetsonBackend implements JetsonBackend {
  RestJetsonBackend(this.transport);
  final RescueTransport transport;
  @override Stream<ApiEvent> get events => transport.events;
  Future<JsonMap> _getObject(String path) async => _object(await transport.get(path));
  Future<JsonMap> _postObject(String path, [Object? body]) async => _object(await transport.post(path, body: body));
  static JsonMap _object(Object? value) { final object = requireJsonMap(value); final data = object['data']; return data is Map ? requireJsonMap(data) : object; }
  @override Future<JsonMap> health() => _getObject('api/v1/health');
  @override Future<JsonMap> status() => _getObject('api/v1/status');
  @override Future<List<JsonMap>> listMissions() async { final value = await transport.get('api/v1/missions'); if (value is List) return jsonObjectList(value); final object = _object(value); return jsonObjectList(object['items'] ?? object['missions'] ?? const []); }
  @override Future<JsonMap> getMission(String missionId, int missionVersion) => _getObject('api/v1/missions/$missionId/$missionVersion');
  @override Future<JsonMap?> currentMission() async { try { return await _getObject('api/v1/missions/current'); } on ApiFailure catch (failure) { if (failure.statusCode == 404) return null; rethrow; } }
  @override Future<JsonMap> storeTabletMission(JsonMap draft, {String? filename, Uint8List? bytes, int? reuseFromVersion}) async {
    final response = await transport.multipart(
      'api/v1/tablet/missions',
      fields: {
        'manifest': jsonEncode(draft),
        if (reuseFromVersion != null) 'reuse_from_version': reuseFromVersion.toString(),
      },
      filename: filename,
      bytes: bytes,
    );
    return _object(response);
  }
  @override Future<JsonMap> selectMission(String missionId, int missionVersion) => _postObject('api/v1/missions/$missionId/$missionVersion/select');
  @override Future<JsonMap> analyze() => _postObject('api/v1/analysis', const {'priorities': <String, int>{}});
  @override Future<JsonMap> currentResult() => _getObject('api/v1/results/current');
  @override Future<JsonMap> sendCurrentResult() => _postObject('api/v1/results/current/send', const {'priority': 0});
  @override Future<JsonMap> createPreview({bool force = false}) => _postObject('api/v1/preview');
  @override Future<JsonMap?> currentPreview() async { try { return await _getObject('api/v1/preview/current'); } on ApiFailure catch (failure) { if (failure.statusCode == 404) return null; rethrow; } }
  @override Future<JsonMap> sendPreview({bool force = false}) => _postObject('api/v1/preview/send', const {'priority': 0});
  @override Future<JsonMap> currentApprovedPlan() => _getObject('api/v1/approved-plan/current');
  @override Future<Uint8List> downloadArtifact(String path) => transport.getBytes(path);
  @override Future<void> close() => transport.close();
}
