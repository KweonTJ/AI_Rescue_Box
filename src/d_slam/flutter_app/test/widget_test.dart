import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rescue_api_client/rescue_api_client.dart';
import 'package:rescue_api_client/src/backends.dart';
import 'package:rescue_api_client/src/jetson_app.dart';
import 'package:rescue_api_client/src/jetson_controller.dart';

class _FakeBackend implements JetsonBackend {
  @override Stream<ApiEvent> get events => const Stream<ApiEvent>.empty();
  @override Future<JsonMap> health() async => {'status':'ok','mode':'mock'};
  @override Future<JsonMap> status() async => {'mode':'mock','providers':<String,Object?>{}};
  @override Future<List<JsonMap>> listMissions() async => <JsonMap>[];
  @override Future<JsonMap?> currentMission() async => null;
  @override Future<JsonMap> selectMission(String missionId,int missionVersion) async => <String,Object?>{};
  @override Future<JsonMap> analyze() async => {'analysis_mode':'mock','result':<String,Object?>{}};
  @override Future<JsonMap> currentResult() async => <String,Object?>{};
  @override Future<JsonMap> sendCurrentResult() async => {'state':'not_wired'};
  @override Future<JsonMap> createPreview({bool force=false}) async => <String,Object?>{};
  @override Future<JsonMap?> currentPreview() async => null;
  @override Future<JsonMap> sendPreview({bool force=false}) async => {'state':'not_wired'};
  @override Future<JsonMap> currentApprovedPlan() async => <String,Object?>{};
  @override Future<Uint8List> downloadArtifact(String path) async => Uint8List(0);
  @override Future<void> close() async {}
}

void main(){
  testWidgets('Jetson dashboard boots with API-only backend',(tester) async {
    final controller=JetsonController(_FakeBackend(),autoRefreshInterval:const Duration(days:1));
    await tester.pumpWidget(RescueJetsonApp(controller:controller));
    await tester.pump();
    expect(find.byType(RescueJetsonApp),findsOneWidget);
  });
}
