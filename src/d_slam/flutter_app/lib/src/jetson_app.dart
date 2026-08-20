import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'jetson_controller.dart';

part 'dashboard.dart';
part 'mission_map_canvas.dart';
part 'mission_panel.dart';
part 'mission_projection.dart';
part 'mission_selector.dart';
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
  // Deliberately starts at the selector on every Flutter cold launch. A
  // previously ACTIVE Jetson mission may be labelled as current, but it never
  // auto-navigates the operator past this explicit choice.
  bool _showMissionSelector = true;
  final _navigatorKey = GlobalKey<NavigatorState>();

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_changed);
    widget.controller.initialise();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  Future<void> _selectMission(JsonMap mission) async {
    final missionId = _asString(mission['mission_id']) ?? 'unknown';
    final version = _asInt(mission['mission_version'] ?? mission['version']) ?? 0;
    final name = _asString(mission['mission_name']) ?? missionId;
    final navigatorContext = _navigatorKey.currentContext;
    if (navigatorContext == null) return;
    final confirmed = await showDialog<bool>(
      context: navigatorContext,
      builder: (dialogContext) => AlertDialog(
        title: const Text('이 구조도를 사용하시겠습니까?'),
        content: Text('$name\n$missionId · v$version'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('취소'),
          ),
          FilledButton(
            key: const Key('mission-select-confirm'),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('사용'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await widget.controller.selectMission(mission);
    if (!mounted || widget.controller.error != null) return;
    setState(() => _showMissionSelector = false);
  }

  void _chooseAnotherMission() {
    setState(() => _showMissionSelector = true);
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
      navigatorKey: _navigatorKey,
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
      home: _showMissionSelector
          ? _MissionSelector(
              controller: widget.controller,
              onSelect: _selectMission,
            )
          : _Dashboard(
              controller: widget.controller,
              onChooseAnotherMission: _chooseAnotherMission,
            ),
    );
  }
}
