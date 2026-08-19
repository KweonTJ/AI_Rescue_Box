import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'src/jetson_app.dart';
import 'src/jetson_controller.dart';

const _jetsonApiBaseUrl = String.fromEnvironment(
  'JETSON_API_BASE_URL',
  defaultValue: 'http://192.168.50.1:8001',
);
const _jetsonWebSocketUrl = String.fromEnvironment('JETSON_WS_URL');

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final endpoints = ApiEndpoints(
    baseUri: Uri.parse(_jetsonApiBaseUrl),
    webSocketUri: _jetsonWebSocketUrl.isEmpty
        ? null
        : Uri.parse(_jetsonWebSocketUrl),
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
