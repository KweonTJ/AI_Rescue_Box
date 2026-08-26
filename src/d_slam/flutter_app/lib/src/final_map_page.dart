part of 'jetson_app.dart';

class _FinalMapPage extends StatelessWidget {
  const _FinalMapPage({
    required this.controller,
    required this.onChooseAnotherMission,
  });

  final JetsonController controller;
  final VoidCallback onChooseAnotherMission;

  int _count(JsonMap? value, Iterable<String> keys) {
    if (value == null) return 0;
    for (final key in keys) {
      final items = value[key];
      if (items is List) return items.length;
    }
    return 0;
  }

  @override
  Widget build(BuildContext context) {
    final missionId = controller.selectedMissionId;
    final missionVersion = controller.selectedMissionVersion;
    final result = controller.currentResult;
    final plan = controller.approvedPlan;
    final approved = plan != null && plan.isNotEmpty;

    final victimCount = approved
        ? _count(plan, const ['approved_victims'])
        : _count(result, const ['confirmed_victims', 'victim_candidates']);
    final obstacleCount = _count(result, const ['obstacles']);
    final riskCount = approved
        ? _count(plan, const ['approved_risk_zones'])
        : _count(result, const ['risk_zones']);
    final routeCount = approved
        ? _count(
            plan,
            const [
              'approved_entry_routes',
              'approved_routes',
              'approved_return_routes',
            ],
          )
        : _count(result, const ['entry_routes', 'return_routes']);

    if (missionId == null) {
      return _FinalMapEmpty(
        title: 'ACTIVE Mission이 없습니다',
        message: 'ACTIVE 탭에서 구조도를 선택한 뒤 최종 지도를 확인하세요.',
        onAction: onChooseAnotherMission,
      );
    }

    return ColoredBox(
      color: _tabletBackground,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        approved ? '최종 승인 지도' : '최종 승인 지도 대기 중',
                        style: const TextStyle(
                          color: _tabletInk,
                          fontSize: 24,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '$missionId · v${missionVersion ?? '-'} · '
                        '${approved ? 'Host Approved Plan 반영 완료' : '현재 Rescue Map 표시 중'}',
                        style: const TextStyle(
                          color: _tabletMuted,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
                _FinalMapStateBadge(approved: approved),
                const SizedBox(width: 10),
                IconButton.filledTonal(
                  tooltip: '새로고침',
                  onPressed: controller.busy
                      ? null
                      : () => unawaited(controller.refresh()),
                  icon: const Icon(Icons.refresh),
                ),
              ],
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _FinalMapMetric(label: '요구조자', value: victimCount),
                _FinalMapMetric(label: '장애물', value: obstacleCount),
                _FinalMapMetric(label: '위험구역', value: riskCount),
                _FinalMapMetric(label: '승인 경로', value: routeCount),
              ],
            ),
            const SizedBox(height: 14),
            Expanded(
              child: controller.baseMapPng == null
                  ? const Card(
                      child: Center(
                        child: Text(
                          '구조도 불러오는 중…',
                          style: TextStyle(
                            color: _tabletMuted,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    )
                  : Card(
                      clipBehavior: Clip.antiAlias,
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: InteractiveViewer(
                          minScale: 0.7,
                          maxScale: 8,
                          boundaryMargin: const EdgeInsets.all(100),
                          child: Center(
                            child: _MissionMapCanvas(
                              controller: controller,
                              baseMapBytes: controller.baseMapPng,
                              previewBytes: controller.previewPng,
                            ),
                          ),
                        ),
                      ),
                    ),
            ),
            if (!approved) ...[
              const SizedBox(height: 10),
              const Card(
                color: _tabletYellowSoft,
                child: Padding(
                  padding: EdgeInsets.all(12),
                  child: Row(
                    children: [
                      Icon(Icons.schedule, color: _tabletYellow),
                      SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Windows Host에서 최종 계획을 승인하면 UWB로 Jetson에 도착하고 이 화면이 자동 갱신됩니다.',
                          style: TextStyle(
                            color: _tabletInk,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _FinalMapStateBadge extends StatelessWidget {
  const _FinalMapStateBadge({required this.approved});

  final bool approved;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: approved ? _tabletGreenSoft : _tabletYellowSoft,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            approved ? Icons.verified : Icons.hourglass_top,
            size: 16,
            color: approved ? _tabletGreen : _tabletYellow,
          ),
          const SizedBox(width: 6),
          Text(
            approved ? 'APPROVED' : 'WAITING',
            style: TextStyle(
              color: approved ? _tabletGreen : _tabletYellow,
              fontSize: 11,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

class _FinalMapMetric extends StatelessWidget {
  const _FinalMapMetric({required this.label, required this.value});

  final String label;
  final int value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: _tabletSurface,
        border: Border.all(color: _tabletLine),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        '$label $value',
        style: const TextStyle(
          color: _tabletInk,
          fontSize: 12,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _FinalMapEmpty extends StatelessWidget {
  const _FinalMapEmpty({
    required this.title,
    required this.message,
    required this.onAction,
  });

  final String title;
  final String message;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.map_outlined, size: 42, color: _tabletMuted),
              const SizedBox(height: 12),
              Text(
                title,
                style: const TextStyle(
                  color: _tabletInk,
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                message,
                textAlign: TextAlign.center,
                style: const TextStyle(color: _tabletMuted),
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: onAction,
                icon: const Icon(Icons.play_circle_outline),
                label: const Text('ACTIVE Mission 선택'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}