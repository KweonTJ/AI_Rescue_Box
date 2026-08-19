part of 'jetson_app.dart';

class _MissionPanel extends StatelessWidget {
  const _MissionPanel({required this.controller});

  final JetsonController controller;

  @override
  Widget build(BuildContext context) {
    final selectedId = controller.selectedMissionId;
    final selectedVersion = controller.selectedMissionVersion;
    return _SectionCard(
      title: '임무',
      subtitle: 'Host에서 수신한 구조도와 Mission manifest를 선택합니다.',
      trailing: _StatusBadge(
        label: selectedId == null ? '미선택' : '$selectedId v$selectedVersion',
        good: selectedId != null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (controller.missions.isEmpty)
            const _EmptyState(
              icon: Icons.folder_off_outlined,
              title: '저장된 임무가 없습니다.',
              body: 'Host가 Mission artifact를 전송하면 여기에 나타납니다.',
            )
          else
            for (final mission in controller.missions) ...[
              _MissionRow(controller: controller, mission: mission),
              const SizedBox(height: 8),
            ],
        ],
      ),
    );
  }
}

class _MissionRow extends StatelessWidget {
  const _MissionRow({required this.controller, required this.mission});

  final JetsonController controller;
  final JsonMap mission;

  @override
  Widget build(BuildContext context) {
    final missionId = _asString(mission['mission_id']) ?? 'unknown';
    final version = _asInt(mission['mission_version'] ?? mission['version']) ?? 0;
    final active = mission['active'] == true ||
        (controller.selectedMissionId == missionId &&
            controller.selectedMissionVersion == version);
    final verified = mission['verified'] == true || mission['status'] == 'verified';
    return DecoratedBox(
      decoration: BoxDecoration(
        color: active ? const Color(0xff173b39) : const Color(0xff0c1b1d),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: active ? const Color(0xff48c9b0) : const Color(0xff244044),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            Icon(
              active ? Icons.radio_button_checked : Icons.map_outlined,
              color: active ? const Color(0xff48c9b0) : Colors.white70,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '$missionId · v$version',
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 4),
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    children: [
                      _MiniLabel(
                        text: verified ? '검증됨' : '검증 상태 미확인',
                        good: verified,
                      ),
                      if (mission['received_at'] is String)
                        _MiniLabel(text: mission['received_at'] as String),
                    ],
                  ),
                ],
              ),
            ),
            FilledButton.tonal(
              onPressed: controller.busy || active
                  ? null
                  : () => controller.selectMission(mission),
              child: Text(active ? '선택됨' : '선택'),
            ),
          ],
        ),
      ),
    );
  }
}

class _MapPanel extends StatelessWidget {
  const _MapPanel({required this.controller});

  final JetsonController controller;

  @override
  Widget build(BuildContext context) {
    return _SectionCard(
      title: 'Mission Map',
      subtitle: '사전 구조도 위에 현재 SLAM 결과와 semantic layer를 겹쳐 표시합니다.',
      trailing: _StatusBadge(
        label: controller.preview == null ? 'Preview 없음' : 'Preview 준비',
        good: controller.preview != null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: ColoredBox(
              color: const Color(0xff071012),
              child: controller.selectedMission == null
                  ? const SizedBox(
                      height: 330,
                      child: _EmptyState(
                        icon: Icons.map_outlined,
                        title: '임무를 선택하세요.',
                        body: 'Mission 구조도와 live map이 이 영역에 표시됩니다.',
                      ),
                    )
                  : _MissionMapCanvas(
                      controller: controller,
                      baseMapBytes: controller.baseMapPng,
                      previewBytes: controller.previewPng,
                    ),
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 8,
            children: const [
              _Legend(color: Color(0xff56cfe1), label: '로봇/궤적'),
              _Legend(color: Color(0xffffd166), label: '요구조자'),
              _Legend(color: Color(0xffef476f), label: '위험'),
              _Legend(color: Color(0xff06d6a0), label: '경로/팀'),
              _Legend(color: Color(0xff9b5de5), label: '미탐색/Preview'),
            ],
          ),
        ],
      ),
    );
  }
}
