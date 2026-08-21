import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import 'host_controller.dart';
import 'review_workspace.dart';

/// Command-center UI after Mission authoring moved to the field Tablet.
///
/// Floorplan upload, scale calibration, robot-start and entrance editing are
/// intentionally absent. Host keeps UWB monitoring, semantic review and
/// approved-plan operations.
final class RescueHostConsoleApp extends StatefulWidget {
  const RescueHostConsoleApp({super.key, required this.controller});

  final HostController controller;

  @override
  State<RescueHostConsoleApp> createState() => _RescueHostConsoleAppState();
}

class _RescueHostConsoleAppState extends State<RescueHostConsoleApp> {
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
  Widget build(BuildContext context) => MaterialApp(
        title: 'AI Rescue Box Host',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xff00695c),
            brightness: Brightness.dark,
          ),
          useMaterial3: true,
        ),
        home: _HostConsoleShell(controller: widget.controller),
      );
}

class _HostConsoleShell extends StatefulWidget {
  const _HostConsoleShell({required this.controller});
  final HostController controller;

  @override
  State<_HostConsoleShell> createState() => _HostConsoleShellState();
}

class _HostConsoleShellState extends State<_HostConsoleShell> {
  int page = 0;
  int _seenEventSequence = 0;
  bool _syncingActive = false;

  @override
  void initState() {
    super.initState();
    _seenEventSequence = widget.controller.lastEventSequence;
    widget.controller.addListener(_controllerChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) unawaited(_syncActiveMission());
    });
  }

  @override
  void dispose() {
    widget.controller.removeListener(_controllerChanged);
    super.dispose();
  }

  void _controllerChanged() {
    final sequence = widget.controller.lastEventSequence;
    if (sequence <= _seenEventSequence) return;
    _seenEventSequence = sequence;
    unawaited(_syncActiveMission());
  }

  Future<void> _syncActiveMission() async {
    if (_syncingActive) return;
    _syncingActive = true;
    try {
      final controller = widget.controller;
      final status = await controller.backend.status();
      controller.backendStatus = status;
      final rawActive = status['active_mission'];
      if (rawActive is! Map) return;
      final active = Map<String, dynamic>.from(rawActive);
      final id = _consoleString(active, const ['mission_id']);
      final version = _consoleInt(active, const ['mission_version', 'version']);
      if (id == null || version == null || version < 1) return;

      final identityChanged =
          controller.missionId != id || controller.missionVersion != version;
      if (identityChanged || controller.currentMission == null) {
        final manifest = await controller.backend.getMission(id, version);
        controller.currentMission = manifest;
        controller.updateMissionFields(
          id: id,
          version: version,
          name: _consoleString(manifest, const ['mission_name']) ?? id,
        );
      }
      // With missionId/version synchronized, the existing review flow can load
      // semantic_result and build/send approved_plan without Host map upload.
      await controller.refreshResults();
    } on Object {
      // Host stays usable when Jetson/UWB is temporarily unavailable. Existing
      // controller error/event surfaces continue to report connection failures.
    } finally {
      _syncingActive = false;
    }
  }

  Future<void> _refreshAll() async {
    await widget.controller.refreshStatus();
    await _syncActiveMission();
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Rescue Box · Host'),
        actions: [
          _ConnectionBadge(controller: controller),
          IconButton(
            tooltip: '상태 새로고침',
            onPressed: controller.busy ? null : _refreshAll,
            icon: const Icon(Icons.refresh),
          ),
          const SizedBox(width: 8),
        ],
        bottom: controller.busy
            ? const PreferredSize(
                preferredSize: Size.fromHeight(3),
                child: LinearProgressIndicator(),
              )
            : null,
      ),
      body: Column(
        children: [
          if (controller.error != null)
            MaterialBanner(
              content: Text(controller.error!),
              actions: [
                TextButton(
                  onPressed: controller.clearError,
                  child: const Text('확인'),
                ),
              ],
            ),
          Expanded(
            child: IndexedStack(
              index: page,
              children: [
                _MonitorPage(controller: controller),
                ReviewWorkspace(controller: controller),
                _EventsPage(controller: controller),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: page,
        onDestinationSelected: (value) => setState(() => page = value),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard),
            label: '관제',
          ),
          NavigationDestination(
            icon: Icon(Icons.fact_check_outlined),
            selectedIcon: Icon(Icons.fact_check),
            label: '분석·검토',
          ),
          NavigationDestination(
            icon: Icon(Icons.monitor_heart_outlined),
            selectedIcon: Icon(Icons.monitor_heart),
            label: '상태·이벤트',
          ),
        ],
      ),
    );
  }
}

class _MonitorPage extends StatelessWidget {
  const _MonitorPage({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final statusActive = controller.backendStatus['active_mission'];
    final active = statusActive is Map
        ? Map<String, dynamic>.from(statusActive)
        : const <String, dynamic>{};
    final mission = controller.currentMission ?? active;
    final missionId = _consoleString(mission, const ['mission_id']) ??
        (controller.missionId.isEmpty ? null : controller.missionId);
    final missionVersion = _consoleInt(
          mission,
          const ['mission_version', 'version'],
        ) ??
        (missionId == null ? null : controller.missionVersion);
    final bridge = controller.bridgeStatus;
    final bridgeState = _consoleString(
          bridge,
          const ['state', 'serial_state', 'connection_state'],
        ) ??
        'WAITING';

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _Card(
          title: '현재 현장 Mission',
          subtitle: 'Mission 생성·수정·ACTIVE 선택은 Galaxy Tab에서 수행합니다.',
          child: missionId == null
              ? const _Empty(
                  icon: Icons.map_outlined,
                  title: 'ACTIVE Mission 메타데이터 대기',
                  body: 'Jetson에서 ACTIVE Mission 정보가 수신되면 표시됩니다.',
                )
              : Wrap(
                  spacing: 10,
                  runSpacing: 8,
                  children: [
                    _Metric(label: 'Mission', value: missionId),
                    _Metric(
                      label: 'Version',
                      value: missionVersion == null ? '-' : 'v$missionVersion',
                    ),
                    const _Metric(label: 'Host 역할', value: '원격 관제'),
                  ],
                ),
        ),
        const SizedBox(height: 12),
        _Card(
          title: 'UWB / Jetson',
          subtitle: 'Host↔Jetson은 작은 제어·분석 결과만 주고받습니다.',
          trailing: OutlinedButton.icon(
            onPressed: controller.busy ? null : controller.reconnectBridge,
            icon: const Icon(Icons.sync),
            label: const Text('재연결'),
          ),
          child: Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              _Metric(label: 'Bridge', value: bridgeState),
              _Metric(label: '전송 단계', value: controller.transferStage),
              _Metric(
                label: 'Peer 저장',
                value: controller.remoteSaved ? 'ACK' : '대기',
              ),
              _Metric(
                label: 'Application',
                value: controller.applicationAck ? 'ACK' : '대기',
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _Card(
          title: '분석 결과 / 구조 계획',
          subtitle: '요구조자·위험지역·경로를 검토하고 approved_plan을 전송합니다.',
          child: Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              _Metric(label: '결과', value: '${controller.results.length}개'),
              _Metric(
                label: '현재 Result',
                value: controller.currentResultVersion > 0
                    ? 'v${controller.currentResultVersion}'
                    : '없음',
              ),
              _Metric(
                label: 'Approved Plan',
                value: controller.latestApprovedPlanVersion > 0
                    ? 'v${controller.latestApprovedPlanVersion}'
                    : '없음',
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        const _Card(
          title: 'Host 역할',
          subtitle: '구조도 입력은 Tablet로 이동했습니다.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('• 구조도 JPG/PNG 업로드 없음'),
              SizedBox(height: 6),
              Text('• 축척·로봇 시작 위치·출입구 편집 없음'),
              SizedBox(height: 6),
              Text('• semantic_result / map_delta / urgent_event 수신 유지'),
              SizedBox(height: 6),
              Text('• 분석 검토·수정 및 approved_plan 전송 유지'),
            ],
          ),
        ),
      ],
    );
  }
}

class _EventsPage extends StatelessWidget {
  const _EventsPage({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _Card(
            title: '통신 이벤트',
            subtitle: controller.webSocketState,
            child: controller.eventLog.isEmpty
                ? const _Empty(
                    icon: Icons.notifications_none,
                    title: '이벤트 대기',
                    body: 'Host API와 UWB 이벤트가 표시됩니다.',
                  )
                : SizedBox(
                    height: 340,
                    child: ListView.separated(
                      itemCount: controller.eventLog.length,
                      separatorBuilder: (_, _) => const Divider(height: 12),
                      itemBuilder: (_, index) =>
                          SelectableText(controller.eventLog[index]),
                    ),
                  ),
          ),
          const SizedBox(height: 12),
          _Card(
            title: 'Backend 상태',
            subtitle: '진단용 원본 상태',
            child: SelectableText(
              const JsonEncoder.withIndent(' ').convert(controller.backendStatus),
              style: const TextStyle(fontFamily: 'monospace'),
            ),
          ),
        ],
      );
}

class _ConnectionBadge extends StatelessWidget {
  const _ConnectionBadge({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final state = _consoleString(
          controller.bridgeStatus,
          const ['state', 'serial_state', 'connection_state'],
        ) ??
        'WAITING';
    final normalized = state.toLowerCase();
    final good = normalized.contains('connect') ||
        normalized == 'ready' ||
        normalized == 'running';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: DecoratedBox(
        decoration: BoxDecoration(
          border: Border.all(
            color: good ? const Color(0xff06d6a0) : const Color(0xffffd166),
          ),
          borderRadius: BorderRadius.circular(999),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          child: Text('UWB $state'),
        ),
      ),
    );
  }
}

class _Card extends StatelessWidget {
  const _Card({
    required this.title,
    required this.subtitle,
    required this.child,
    this.trailing,
  });
  final String title;
  final String subtitle;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(title, style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 4),
                        Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
                      ],
                    ),
                  ),
                  if (trailing != null) trailing!,
                ],
              ),
              const SizedBox(height: 16),
              child,
            ],
          ),
        ),
      );
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => DecoratedBox(
        decoration: BoxDecoration(
          color: const Color(0xff102326),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: const Color(0xff315254)),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(label, style: Theme.of(context).textTheme.labelSmall),
              const SizedBox(width: 8),
              Text(value, style: Theme.of(context).textTheme.labelLarge),
            ],
          ),
        ),
      );
}

class _Empty extends StatelessWidget {
  const _Empty({required this.icon, required this.title, required this.body});
  final IconData icon;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 18),
        child: Column(
          children: [
            Icon(icon, size: 38, color: Colors.white38),
            const SizedBox(height: 10),
            Text(title, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 5),
            Text(body, textAlign: TextAlign.center),
          ],
        ),
      );
}

String? _consoleString(Map<String, dynamic> value, List<String> keys) {
  for (final key in keys) {
    final item = value[key];
    if (item is String && item.trim().isNotEmpty) return item;
  }
  return null;
}

int? _consoleInt(Map<String, dynamic> value, List<String> keys) {
  for (final key in keys) {
    final item = value[key];
    if (item is num) return item.toInt();
  }
  return null;
}
