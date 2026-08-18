import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'src/host_app.dart';
import 'src/host_backend_adapter.dart';
import 'src/host_controller.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final endpoints = ApiEndpoints.fromEnvironment(
    defaultBaseUrl: 'http://127.0.0.1:8000',
  );
  final transport = HttpRescueTransport(endpoints: endpoints);
  runApp(RescueHostApp(controller: HostController(HostRestBackend(transport))));
}
