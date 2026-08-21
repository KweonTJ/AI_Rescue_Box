import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'jetson_controller.dart';

part 'dashboard.dart';
part 'mission_management.dart';
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
  final _navigatorKey = GlobalKey<NavigatorState>();
  int _selectedPage = 0;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_changed);
    widget.controller.initialise();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  Future<void> _activateMission(JsonMap mission) async {
    final missionId = _asString(mission['mission_id']) ?? 'unknown';
    final version = _asInt(mission['mission_version'] ?? mission['version']) ?? 0;
    final name = _asString(mission['mission_name']) ?? missionId;
    final navigatorContext = _navigatorKey.currentContext;
    if (navigatorContext == null) return;
    final confirmed = await showDialog<bool>(
      context: navigatorContext,
      builder: (dialogContext) => AlertDialog(
        title: const Text('이 Mission을 ACTIVE로 전환하시겠습니까?'),
        content: Text(
          '$name\n$missionId · v$version\n\nACTIVE 전환 후 로봇 runtime은 이 버전의 구조도와 설정을 사용합니다.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('취소'),
          ),
          FilledButton(
            key: const Key('mission-select-confirm'),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('ACTIVE 전환'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await widget.controller.selectMission(mission);
    if (!mounted || widget.controller.error != null) return;
    ScaffoldMessenger.of(navigatorContext).showSnackBar(
      SnackBar(content: Text('$missionId · v$version ACTIVE 전환 완료')),
    );
  }

  void _openActivePage() {
    setState(() => _selectedPage = 1);
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
      home: Scaffold(
        body: IndexedStack(
          index: _selectedPage,
          children: [
            _MissionManagementHome(controller: widget.controller),
            _MissionSelector(
              controller: widget.controller,
              onSelect: _activateMission,
            ),
            _Dashboard(
              controller: widget.controller,
              onChooseAnotherMission: _openActivePage,
            ),
          ],
        ),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _selectedPage,
          onDestinationSelected: (value) {
            setState(() => _selectedPage = value);
          },
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.folder_copy_outlined),
              selectedIcon: Icon(Icons.folder_copy),
              label: 'Mission 관리',
            ),
            NavigationDestination(
              icon: Icon(Icons.play_circle_outline),
              selectedIcon: Icon(Icons.play_circle),
              label: 'ACTIVE',
            ),
            NavigationDestination(
              icon: Icon(Icons.monitor_heart_outlined),
              selectedIcon: Icon(Icons.monitor_heart),
              label: '운영',
            ),
          ],
        ),
      ),
    );
  }
}
