part of 'jetson_app.dart';

class _MissionSelector extends StatelessWidget {
  const _MissionSelector({required this.controller, required this.onSelect});

  final JetsonController controller;
  final Future<void> Function(JsonMap mission) onSelect;

  bool get _connectionFailed => controller.error != null && controller.health.isEmpty;

  @override
  Widget build(BuildContext context) {
    final apiAddress = controller.apiBaseUri?.toString() ?? '기본 Jetson API 주소';
    final activeName = _asString(_asMap(controller.selectedMission?['manifest'])?['mission_name']) ??
        controller.selectedMissionId ??
        'ACTIVE Mission 없음';
    final activeVersion = controller.selectedMissionVersion;
    return ColoredBox(
      color: _tabletBackground,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1320),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(30, 28, 30, 34),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'ROBOT MISSION SELECTION',
                            style: TextStyle(
                              color: _tabletMuted,
                              fontSize: 10,
                              fontWeight: FontWeight.w900,
                              letterSpacing: 1.4,
                            ),
                          ),
                          SizedBox(height: 7),
                          Text(
                            'ACTIVE Mission',
                            style: TextStyle(
                              color: _tabletInk,
                              fontSize: 27,
                              fontWeight: FontWeight.w800,
                              letterSpacing: -0.8,
                            ),
                          ),
                          SizedBox(height: 6),
                          Text(
                            '실제 사용할 Mission 선택 · Mission 관리에서 STORED된 Version 중 하나를 명시적으로 ACTIVE로 전환합니다.',
                            style: TextStyle(color: _tabletMuted, fontSize: 13),
                          ),
                        ],
                      ),
                    ),
                    OutlinedButton.icon(
                      onPressed: controller.busy ? null : controller.refresh,
                      icon: const Icon(Icons.refresh),
                      label: const Text('새로고침'),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 21),
                  decoration: BoxDecoration(
                    color: _tabletDark,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'CURRENT ACTIVE',
                              style: TextStyle(
                                color: Color(0xffaeb6bd),
                                fontSize: 10,
                                fontWeight: FontWeight.w900,
                                letterSpacing: 1.4,
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              activeVersion == null
                                  ? activeName
                                  : '$activeName · v$activeVersion',
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 24,
                                fontWeight: FontWeight.w800,
                                letterSpacing: -0.5,
                              ),
                            ),
                            const SizedBox(height: 5),
                            Text(
                              controller.selectedMissionId == null
                                  ? 'ACTIVE로 지정된 Mission이 없습니다.'
                                  : '${controller.selectedMissionId} · Jetson runtime 적용 중',
                              style: const TextStyle(color: Color(0xffbfc5ca), fontSize: 11),
                            ),
                          ],
                        ),
                      ),
                      Container(
                        constraints: const BoxConstraints(minWidth: 210),
                        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
                        decoration: BoxDecoration(
                          color: controller.selectedMissionId == null
                              ? const Color(0xff332d1d)
                              : const Color(0xff1d3328),
                          border: Border.all(
                            color: controller.selectedMissionId == null
                                ? const Color(0xff6f5d2d)
                                : const Color(0xff366b52),
                          ),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              controller.selectedMissionId == null ? '● NOT SET' : '● ACTIVE',
                              style: TextStyle(
                                color: controller.selectedMissionId == null
                                    ? const Color(0xffffd166)
                                    : const Color(0xff8be0b2),
                                fontSize: 15,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              controller.selectedMissionId == null
                                  ? 'Mission 선택 필요'
                                  : 'SLAM / AI 분석 기준으로 사용 중',
                              style: const TextStyle(color: Color(0xffa9c8b6), fontSize: 10),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                if (_connectionFailed)
                  Expanded(
                    child: _MissionSelectorMessage(
                      icon: Icons.cloud_off_outlined,
                      title: 'Jetson 연결 실패',
                      body: 'Jetson API 주소: $apiAddress\n${controller.error}',
                      action: FilledButton.icon(
                        key: const Key('mission-selector-retry'),
                        onPressed: controller.busy ? null : controller.initialise,
                        icon: const Icon(Icons.refresh),
                        label: const Text('재시도'),
                      ),
                    ),
                  )
                else if (controller.busy && controller.missions.isEmpty)
                  const Expanded(child: Center(child: CircularProgressIndicator()))
                else if (controller.missions.isEmpty)
                  const Expanded(
                    child: _MissionSelectorMessage(
                      icon: Icons.folder_off_outlined,
                      title: '저장된 Mission이 없습니다.',
                      body: 'Mission 관리에서 새 구조도를 등록하면 여기에 표시됩니다.',
                    ),
                  )
                else
                  Expanded(
                    child: Container(
                      decoration: BoxDecoration(
                        color: _tabletSurface,
                        border: Border.all(color: _tabletLine),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          const Padding(
                            padding: EdgeInsets.fromLTRB(18, 16, 18, 13),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Jetson 저장 Version',
                                  style: TextStyle(
                                    color: _tabletInk,
                                    fontSize: 15,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                                SizedBox(height: 4),
                                Text(
                                  'ACTIVE 전환은 SLAM과 분석 기준을 변경하므로 명시적으로 실행합니다.',
                                  style: TextStyle(color: _tabletMuted, fontSize: 10),
                                ),
                              ],
                            ),
                          ),
                          const Divider(height: 1),
                          Expanded(
                            child: ListView.separated(
                              key: const Key('mission-selector-list'),
                              itemCount: controller.missions.length,
                              separatorBuilder: (_, _) => const Divider(height: 1),
                              itemBuilder: (context, index) {
                                final mission = controller.missions[index];
                                return _MissionSelectorCard(
                                  controller: controller,
                                  mission: mission,
                                  onTap: () => onSelect(mission),
                                );
                              },
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                if (controller.error != null && !_connectionFailed) ...[
                  const SizedBox(height: 10),
                  Text(
                    controller.error!,
                    key: const Key('mission-selector-error'),
                    style: const TextStyle(color: _tabletRed, fontWeight: FontWeight.w700),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _MissionSelectorMessage extends StatelessWidget {
  const _MissionSelectorMessage({
    required this.icon,
    required this.title,
    required this.body,
    this.action,
  });

  final IconData icon;
  final String title;
  final String body;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 52, color: _tabletMuted),
            const SizedBox(height: 15),
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: _tabletInk,
                fontSize: 18,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 7),
            Text(
              body,
              textAlign: TextAlign.center,
              style: const TextStyle(color: _tabletMuted, fontSize: 12, height: 1.5),
            ),
            if (action != null) ...[
              const SizedBox(height: 18),
              action!,
            ],
          ],
        ),
      );
}

class _MissionSelectorCard extends StatelessWidget {
  const _MissionSelectorCard({
    required this.controller,
    required this.mission,
    required this.onTap,
  });

  final JetsonController controller;
  final JsonMap mission;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final missionId = _asString(mission['mission_id']) ?? 'unknown';
    final version = _asInt(mission['mission_version'] ?? mission['version']) ?? 0;
    final name = _asString(mission['mission_name']) ?? missionId;
    final verified = mission['verified'] == true ||
        mission['verification_status'] == 'verified' ||
        mission['status'] == 'verified';
    final active = mission['active'] == true;
    final received = _asString(mission['received_at'] ?? mission['verified_at']);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
      child: Row(
        children: [
          Container(
            width: 21,
            height: 21,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(
                color: active ? _tabletDark : _tabletLineStrong,
                width: 2,
              ),
            ),
            child: active
                ? Center(
                    child: Container(
                      width: 9,
                      height: 9,
                      decoration: const BoxDecoration(
                        color: _tabletDark,
                        shape: BoxShape.circle,
                      ),
                    ),
                  )
                : null,
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '$name · v$version',
                  style: const TextStyle(
                    color: _tabletInk,
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  '$missionId${received == null ? '' : ' · $received'}',
                  style: const TextStyle(color: _tabletMuted, fontSize: 10),
                ),
              ],
            ),
          ),
          _VersionStateBadge(
            text: active ? '현재 ACTIVE' : (verified ? '검증 완료 · STORED' : 'STORED'),
            active: active,
            verified: verified,
          ),
          const SizedBox(width: 12),
          FilledButton(
            key: Key('select-$missionId-v$version'),
            onPressed: controller.busy || active ? null : onTap,
            style: FilledButton.styleFrom(minimumSize: const Size(126, 42)),
            child: Text(active ? '현재 ACTIVE' : 'ACTIVE 전환'),
          ),
        ],
      ),
    );
  }
}
