import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'jetson_controller.dart';

part 'dashboard.dart';
part 'mission_landing.dart';
part 'mission_management.dart';
part 'mission_workflow_v2.dart';
part 'mission_map_canvas.dart';
part 'mission_panel.dart';
part 'mission_projection.dart';
part 'mission_selector.dart';
part 'operation_panels.dart';
part 'semantic_details.dart';
part 'semantic_map_painter.dart';
part 'status_panel.dart';
part 'ui_components.dart';

const _tabletBackground = Color(0xffeef0f2);
const _tabletSurface = Color(0xffffffff);
const _tabletSurfaceMuted = Color(0xfff6f7f8);
const _tabletInk = Color(0xff15181b);
const _tabletMuted = Color(0xff66707a);
const _tabletLine = Color(0xffd8dde2);
const _tabletLineStrong = Color(0xffb9c1c9);
const _tabletDark = Color(0xff171a1d);
const _tabletGreen = Color(0xff1b8a5a);
const _tabletGreenSoft = Color(0xffe7f4ed);
const _tabletYellow = Color(0xffb87a00);
const _tabletYellowSoft = Color(0xfffff4d9);
const _tabletRed = Color(0xffc73737);
const _tabletOrange = Color(0xffd56b1f);
const _tabletBlue = Color(0xff1677a8);
const _tabletCyan = Color(0xff00a7c4);

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
        icon: const Icon(Icons.warning_amber_rounded, color: _tabletYellow),
        title: const Text('이 Mission을 ACTIVE로 전환하시겠습니까?'),
        content: Text('$name\n$missionId · v$version\n\nACTIVE 전환 후 로봇 runtime은 이 버전의 구조도와 설정을 사용합니다.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(dialogContext).pop(false), child: const Text('취소')),
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
    if (!mounted || !navigatorContext.mounted || widget.controller.error != null) return;
    ScaffoldMessenger.of(navigatorContext).showSnackBar(SnackBar(content: Text('$missionId · v$version ACTIVE 전환 완료')));
  }

  void _openActivePage() => setState(() => _selectedPage = 1);

  @override
  void dispose() {
    widget.controller.removeListener(_changed);
    widget.controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
        navigatorKey: _navigatorKey,
        title: 'AI Rescue Box · Tablet',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.light,
          scaffoldBackgroundColor: _tabletBackground,
          colorScheme: ColorScheme.fromSeed(
            seedColor: _tabletDark,
            brightness: Brightness.light,
            primary: _tabletDark,
            secondary: _tabletBlue,
            surface: _tabletSurface,
            error: _tabletRed,
          ),
          dividerColor: _tabletLine,
          cardTheme: const CardThemeData(
            elevation: 0,
            color: _tabletSurface,
            margin: EdgeInsets.zero,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.all(Radius.circular(12)),
              side: BorderSide(color: _tabletLine),
            ),
          ),
          inputDecorationTheme: const InputDecorationTheme(
            filled: true,
            fillColor: _tabletSurface,
            border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(8)), borderSide: BorderSide(color: _tabletLineStrong)),
            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(8)), borderSide: BorderSide(color: _tabletLineStrong)),
            focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(8)), borderSide: BorderSide(color: _tabletDark, width: 1.5)),
          ),
          appBarTheme: const AppBarTheme(backgroundColor: _tabletDark, foregroundColor: Colors.white, elevation: 0, surfaceTintColor: Colors.transparent),
          filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(minimumSize: const Size(0, 48), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)))),
          outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(minimumSize: const Size(0, 48), foregroundColor: _tabletInk, side: const BorderSide(color: _tabletLineStrong), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)))),
          useMaterial3: true,
        ),
        home: Scaffold(
          backgroundColor: _tabletBackground,
          body: SafeArea(
            child: Column(
              children: [
                _TabletTopBar(controller: widget.controller),
                _TabletPrimaryNav(selectedIndex: _selectedPage, onSelected: (value) => setState(() => _selectedPage = value)),
                if (widget.controller.busy) const LinearProgressIndicator(minHeight: 2),
                Expanded(
                  child: IndexedStack(
                    index: _selectedPage,
                    children: [
                      _MissionLandingPage(controller: widget.controller),
                      _MissionSelector(controller: widget.controller, onSelect: _activateMission),
                      _Dashboard(controller: widget.controller, onChooseAnotherMission: _openActivePage),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      );
}

class _TabletTopBar extends StatelessWidget {
  const _TabletTopBar({required this.controller});
  final JetsonController controller;

  @override
  Widget build(BuildContext context) {
    final connected = controller.health['status'] == 'ok' || (controller.error == null && controller.health.isNotEmpty);
    final api = controller.apiBaseUri;
    final endpoint = api == null ? 'Jetson API' : '${api.host}:${api.port}';
    return Container(
      height: 66,
      color: _tabletDark,
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Row(children: [
        Container(
          width: 36,
          height: 36,
          alignment: Alignment.center,
          decoration: BoxDecoration(border: Border.all(color: Colors.white, width: 2), borderRadius: BorderRadius.circular(8)),
          child: const Text('ARB', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w900)),
        ),
        const SizedBox(width: 12),
        const Expanded(child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('AI Rescue Box', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800)),
          SizedBox(height: 2),
          Text('Field Tablet · Mission Control', style: TextStyle(color: Color(0xffaeb5bc), fontSize: 11)),
        ])),
        if (MediaQuery.sizeOf(context).width >= 900) ...[
          Text(endpoint, style: const TextStyle(color: Color(0xffaeb5bc), fontSize: 11)),
          const SizedBox(width: 16),
        ],
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
          decoration: BoxDecoration(
            color: connected ? const Color(0xff202823) : const Color(0xff2b2020),
            border: Border.all(color: connected ? const Color(0xff3b4540) : const Color(0xff5b3434)),
            borderRadius: BorderRadius.circular(999),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 8, height: 8, decoration: BoxDecoration(color: connected ? _tabletGreen : _tabletRed, shape: BoxShape.circle)),
            const SizedBox(width: 8),
            Text(connected ? 'Jetson 연결됨' : 'Jetson 연결 대기', style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
          ]),
        ),
        const SizedBox(width: 12),
        StreamBuilder<int>(
          stream: Stream<int>.periodic(const Duration(seconds: 30), (value) => value),
          builder: (_, _) {
            final now = TimeOfDay.now();
            return Text('${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}', style: const TextStyle(color: Color(0xffd9dde0), fontSize: 12, fontWeight: FontWeight.w700));
          },
        ),
      ]),
    );
  }
}

class _TabletPrimaryNav extends StatelessWidget {
  const _TabletPrimaryNav({required this.selectedIndex, required this.onSelected});
  final int selectedIndex;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    const items = [('Mission 관리', Icons.folder_copy_outlined), ('ACTIVE', Icons.play_circle_outline), ('운영', Icons.monitor_heart_outlined)];
    return Container(
      height: 62,
      padding: const EdgeInsets.symmetric(horizontal: 24),
      decoration: const BoxDecoration(
        color: _tabletSurface,
        border: Border(bottom: BorderSide(color: _tabletLine)),
      ),
      child: Row(children: [
        for (var index = 0; index < items.length; index++)
          _TabletNavItem(label: items[index].$1, icon: items[index].$2, selected: selectedIndex == index, showActiveDot: index == 1, onTap: () => onSelected(index)),
      ]),
    );
  }
}

class _TabletNavItem extends StatelessWidget {
  const _TabletNavItem({required this.label, required this.icon, required this.selected, required this.onTap, this.showActiveDot = false});
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;
  final bool showActiveDot;

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: Container(
          width: 170,
          height: 62,
          alignment: Alignment.center,
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: selected ? _tabletInk : Colors.transparent, width: 3))),
          child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            Icon(icon, size: 19, color: selected ? _tabletInk : _tabletMuted),
            const SizedBox(width: 8),
            Text(label, style: TextStyle(color: selected ? _tabletInk : _tabletMuted, fontWeight: FontWeight.w800, fontSize: 14)),
            if (showActiveDot) ...[
              const SizedBox(width: 7),
              Container(width: 7, height: 7, decoration: const BoxDecoration(color: _tabletGreen, shape: BoxShape.circle)),
            ],
          ]),
        ),
      );
}
