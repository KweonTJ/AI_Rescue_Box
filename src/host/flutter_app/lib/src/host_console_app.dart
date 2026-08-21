import 'dart:convert';

import 'package:flutter/material.dart';

import 'host_controller.dart';
import 'review_workspace.dart';

/// Host UI after Mission authoring moved to the field Tablet.
///
/// The Host no longer exposes floorplan upload, scale, robot-start or entrance
/// editing.  It remains the command-center console for UWB state, semantic
/// results, review/approval and operational events.
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
  int _page = 0;

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Rescue Box · Host'),
        actions: [
          _HostConnectionBadge(controller: controller),
          const SizedBox(width: 8),
          IconButton(
            tooltip: '상태 새로고침',
            onPressed: controller.busy ? null : controller.refreshStatus,
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
              index: _page,
              children: [
                _CommandCenterPage(controller: controller),
                ReviewWorkspace(controller: controller),
                _HostEventsPage(controller: controller),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _page,
        onDestinationSelected: (value) => setState(() => _page = value),
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

class _CommandCenterPage extends StatelessWidget {
  const _CommandCenterPage({required this.controller});

  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final mission = controller.currentMission;
    final missionId = _stringValue(
          mission ?? const {},
          const ['mission_id'],
        ) ??
        (controller.missionId.isEmpty ? null : controller.missionId);
    final missionVersion = _intValue(
          mission ?? const {},
          const ['mission_version', 'version'],
        ) ??
        (controller.missionId.isEmpty ? null : controller.missionVersion);
    final bridge = controller.bridgeStatus;
    final bridgeState = _firstText(
          bridge,
          const ['state', 'serial_state', 'connection_state'],
        ) ??
        '확인 중';

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _ConsoleCard(
          title: '현재 현장 Mission',
          subtitle: 'Mission 생성·수정·ACTIVE 선택은 Galaxy Tab에서 수행합니다.',
          child: missionId == null
              ? const _ConsoleEmpty(
                  icon: Icons.map_outlined,
                  title: 'ACTIVE Mission 메타데이터 대기',
                  body: 'Jetson에서 ACTIVE Mission 정보가 수신되면 이곳에 표시됩니다.',
                )
              : Wrap(
                  spacing: 10,
                  runSpacing: 8,
                  children: [
                    _ConsoleMetric(label: 'Mission', value: missionId),
                    _ConsoleMetric(
                      label: 'Version',
                      value: missionVersion == null ? '-' : 'v$missionVersion',
                    ),
                    const _ConsoleMetric(label: '역할', value: '원격 관제'),
                  ],
                ),
        ),
        const SizedBox(height: 12),
        _ConsoleCard(
          title: 'UWB / Jetson 연결',
          subtitle: 'Host↔Jetson은 구조도 대신 작은 제어·분석 데이터만 전송합니다.',
          trailing: OutlinedButton.icon(
            onPressed: controller.busy ? null : controller.reconnectBridge,
            icon: const Icon(Icons.sync),
            label: const Text('재연결'),
          ),
          child: Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              _ConsoleMetric(label: 'Bridge', value: bridgeState),
              _ConsoleMetric(
                label: '전송 단계',
                value: controller.transferStage,
              ),
              _ConsoleMetric(
                label: 'Peer 저장',
                value: controller.remoteSaved ? 'ACK' : '대기',
              ),
              _ConsoleMetric(
                label: 'Application',
                value: controller.applicationAck ? 'ACK' : '대기',
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _ConsoleCard(
          title: '분석 결과 / 구조 계획',
          subtitle: '요구조자·위험지역·경로 결과를 검토하고 approved_plan을 전송합니다.',
          child: Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              _ConsoleMetric(
                label: '결과',
                value: '${controller.results.length}개',
              ),
              _ConsoleMetric(
                label: '현재 Result',
                value: controller.currentResultVersion > 0
                    ? 'v${controller.currentResultVersion}'
                    : '없음',
              ),
              _ConsoleMetric(
                label: 'Approved Plan',
                value: controller.latestApprovedPlanVersion > 0
                    ? 'v${controller.latestApprovedPlanVersion}'
                    : '없음',
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _ConsoleCard(
          title: 'Host 역할 변경',
          subtitle: '구조도 입력 기능은 Tablet로 이동했습니다.',
          child: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('• Host 구조도 JPG/PNG 업로드 없음'),
              SizedBox(height: 6),
              Text('• Host 축척·로봇 시작 위치·출입구 편집 없음'),
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

class _HostEventsPage extends StatelessWidget {
  const _HostEventsPage({required this.controller});

  final HostController controller;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _ConsoleCard(
            title: '통신 이벤트',
            subtitle: controller.webSocketState,
            child: controller.eventLog.isEmpty
                ? const _ConsoleEmpty(
                    icon: Icons.notifications_none,
                    title: '이벤트 대기',
                    body: 'Host API와 UWB에서 발생한 이벤트가 표시됩니다.',
                  )
                : SizedBox(
                    height: 340,
                    child: ListView.separated(
                      itemCount: controller.eventLog.length,
                      separatorBuilder: (_, _) => const Divider(height: 12),
                      itemBuilder: (_, index) => SelectableText(
                        controller.eventLog[index],
                      ),
                    ),
                  ),
          ),
          const SizedBox(height: 12),
          _ConsoleCard(
            title: 'Backend 상태',
            subtitle: '진단용 원본 상태',
            child: SelectableText(
              const JsonEncoder.withIndent('  ').convert(controller.backendStatus),
              style: const TextStyle(fontFamily: 'monospace'),
            ),
          ),
        ],
      );
}

class _HostConnectionBadge extends StatelessWidget {
  const _HostConnectionBadge({required this.controller});

  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final bridge = controller.bridgeStatus;
    final state = _firstText(
          bridge,
          const ['state', 'serial_state', 'connection_state'],
        ) ??
        'WAITING';
    final good = state.toLowerCase().contains('connect') ||
        state.toLowerCase() == 'ready' ||
        state.toLowerCase() == 'running';
    return DecoratedBox(
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
    );
  }
}

class _ConsoleCard extends StatelessWidget {
  const _ConsoleCard({
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

class _ConsoleMetric extends StatelessWidget {
  const _ConsoleMetric({required this.label, required this.value});

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

class _ConsoleEmpty extends StatelessWidget {
  const _ConsoleEmpty({
    required this.icon,
    required this.title,
    required this.body,
  });

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

String? _firstText(Map<String, dynamic> value, List<String> keys) {
  for (final key in keys) {
    final item = value[key];
    if (item is String && item.trim().isNotEmpty) return item;
  }
  return null;
}
