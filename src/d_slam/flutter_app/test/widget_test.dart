import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:rescue_api_client/main.dart';
import 'package:rescue_api_client/rescue_api_client.dart';
class FakeBackend implements JetsonBackend { @override Stream<ApiEvent> get events=>const Stream.empty(); @override Future<JsonMap> health() async=>{}; @override Future<JsonMap> status() async=>{'stage':'stage01'}; @override Future<List<JsonMap>> listMissions() async=>[]; @override Future<JsonMap?> currentMission() async=>null; @override Future<JsonMap> selectMission(String a,int b) async=>{}; @override Future<JsonMap> analyze() async=>{}; @override Future<JsonMap> currentResult() async=>{}; @override Future<JsonMap> sendCurrentResult() async=>{}; @override Future<JsonMap> createPreview({bool force=false}) async=>{}; @override Future<JsonMap?> currentPreview() async=>null; @override Future<JsonMap> sendPreview({bool force=false}) async=>{}; @override Future<JsonMap> currentApprovedPlan() async=>{}; @override Future<Uint8List> downloadArtifact(String path) async=>Uint8List(0); @override Future<void> close() async{} }
void main(){testWidgets('Jetson status UI loads',(tester) async{await tester.pumpWidget(JetsonApp(backend:FakeBackend())); await tester.pumpAndSettle(); expect(find.textContaining('stage01'),findsOneWidget);});}
