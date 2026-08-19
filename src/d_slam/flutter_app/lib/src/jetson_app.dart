import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'jetson_controller.dart';

part 'dashboard.dart';
part 'mission_map_canvas.dart';
part 'mission_panel.dart';
part 'mission_projection.dart';
part 'operation_panels.dart';
part 'semantic_details.dart';
part 'semantic_map_painter.dart';
part 'status_panel.dart';
part 'ui_components.dart';

final class RescueJetsonApp extends StatefulWidget {
  const RescueJetsonApp({super.key, required this.controller});

  final JetsonController controller;

  @override
  State<RescueJetsonApp> createState() => _RescueJetsonAppState();
}

class _RescueJetsonAppState extends State<RescueJetsonApp> {
  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_changed);
    widget.controller.initialise();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    widget.controller.removeListener(_changed);
    widget.controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI Rescue Box · Jetson',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xff00a896),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xff091315),
        cardTheme: const CardThemeData(
          elevation: 0,
          color: Color(0xff102326),
          margin: EdgeInsets.zero,
        ),
        useMaterial3: true,
      ),
      home: _Dashboard(controller: widget.controller),
    );
  }
}
