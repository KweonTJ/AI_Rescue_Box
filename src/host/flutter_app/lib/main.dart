import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'src/host_backend_adapter.dart';
import 'src/host_console_app.dart';
import 'src/host_controller.dart';

String _defaultApiBaseUrl() {
  final browserBase = Uri.base;
  if ((browserBase.scheme == 'http' || browserBase.scheme == 'https') &&
      browserBase.host.isNotEmpty) {
    return browserBase.origin;
  }
  return 'http://127.0.0.1:8000';
}

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final endpoints = ApiEndpoints.fromEnvironment(
    defaultBaseUrl: _defaultApiBaseUrl(),
  );
  final transport = HttpRescueTransport(endpoints: endpoints);
  runApp(
    RescueHostConsoleApp(
      controller: HostController(HostRestBackend(transport)),
    ),
  );
}
