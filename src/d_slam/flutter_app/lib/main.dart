import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'src/jetson_app.dart';
import 'src/jetson_controller.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final endpoints = ApiEndpoints.fromEnvironment(
    defaultBaseUrl: 'http://127.0.0.1:8001',
  );
  final transport = HttpRescueTransport(endpoints: endpoints);
  runApp(
    RescueJetsonApp(
      controller: JetsonController(
        RestJetsonBackend(transport),
        apiBaseUri: endpoints.baseUri,
      ),
    ),
  );
}
