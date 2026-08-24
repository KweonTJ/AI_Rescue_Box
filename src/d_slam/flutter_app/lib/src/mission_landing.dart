part of 'jetson_app.dart';

class _MissionLandingPage extends StatelessWidget {
  const _MissionLandingPage({required this.controller});
  final JetsonController controller;

  @override
  Widget build(BuildContext context) {
    final connected =
        controller.error == null || controller.health.isNotEmpty;

    final uniqueMissions = controller.missions
        .map((item) => _asString(item['mission_id']))
        .whereType<String>()
        .toSet()
        .length;

    final activeLabel = controller.selectedMissionId == null
        ? '없음'
        : '${controller.selectedMissionId} · v${controller.selectedMissionVersion}';

    return ColoredBox(
      color: _tabletBackground,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1320),

          // ListView 대신 SingleChildScrollView + Column 사용
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(30, 28, 30, 34),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'MISSION MANAGEMENT',
                  style: TextStyle(
                    color: _tabletMuted,
                    fontSize: 10,
                    fontWeight: FontWeight.w900,
                    letterSpacing: 1.4,
                  ),
                ),
                const SizedBox(height: 7),
                const Text(
                  '현장에서 수행할 작업을 선택하세요',
                  style: TextStyle(
                    color: _tabletInk,
                    fontSize: 27,
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.8,
                  ),
                ),
                const SizedBox(height: 7),
                const Text(
                  'Mission 저장과 실제 사용 전환은 분리되어 있습니다.',
                  style: TextStyle(
                    color: _tabletMuted,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 22),

                if (!connected) ...[
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: const Color(0xfffff5f5),
                      border: Border.all(
                        color: const Color(0xffeccaca),
                      ),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.cloud_off_outlined,
                          color: _tabletRed,
                          size: 30,
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Text(
                            'Jetson 연결을 먼저 확인하세요.\n'
                            '${controller.error ?? ''}',
                            style: const TextStyle(
                              color: _tabletInk,
                            ),
                          ),
                        ),
                        FilledButton.icon(
                          onPressed:
                              controller.busy ? null : controller.initialise,
                          icon: const Icon(Icons.refresh),
                          label: const Text('재시도'),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                ],

                LayoutBuilder(
                  builder: (context, constraints) {
                    final newMission = _MissionActionTile(
                      key: const Key('new-mission-action'),
                      dark: true,
                      icon: Icons.add,
                      title: '새 Mission 만들기',
                      description:
                          '구조도를 선택하고 Mission 정보, 로봇 시작 위치, '
                          '출입구와 축척을 설정합니다.',
                      footer: '새 Mission 시작',
                      onTap: !connected
                          ? null
                          : () async {
                              await Navigator.of(context).push(
                                MaterialPageRoute<void>(
                                  builder: (_) => _MissionWorkflowPage(
                                    controller: controller,
                                  ),
                                ),
                              );
                            },
                    );

                    final editMission = _MissionActionTile(
                      key: const Key('edit-mission-action'),
                      icon: Icons.history,
                      title: '기존 Mission 수정',
                      description:
                          'Jetson에 저장된 Mission Version을 불러와 '
                          '기존 데이터는 보존한 채 새 Version으로 저장합니다.',
                      footer: '저장된 Mission 보기',
                      onTap: !connected || controller.missions.isEmpty
                          ? null
                          : () async {
                              await Navigator.of(context).push(
                                MaterialPageRoute<void>(
                                  builder: (_) => _MissionLibraryV2Page(
                                    controller: controller,
                                  ),
                                ),
                              );
                            },
                    );

                    if (constraints.maxWidth < 850) {
                      return Column(
                        key: const ValueKey(
                          'mission-actions-portrait',
                        ),
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          newMission,
                          const SizedBox(height: 14),
                          editMission,
                        ],
                      );
                    }

                    return Row(
                      key: const ValueKey(
                        'mission-actions-landscape',
                      ),
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          flex: 11,
                          child: newMission,
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          flex: 9,
                          child: editMission,
                        ),
                      ],
                    );
                  },
                ),

                const SizedBox(height: 16),

                Container(
                  decoration: BoxDecoration(
                    color: _tabletSurface,
                    border: Border.all(
                      color: _tabletLine,
                    ),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: _LandingStatusCell(
                          label: 'JETSON',
                          value:
                              connected ? 'Connected' : 'Disconnected',
                          subtitle:
                              controller.apiBaseUri?.host ?? 'API 대기',
                          good: connected,
                        ),
                      ),
                      const _LandingDivider(),
                      Expanded(
                        child: _LandingStatusCell(
                          label: 'STORED MISSIONS',
                          value:
                              '${controller.missions.length} Versions',
                          subtitle:
                              '$uniqueMissions Mission groups',
                        ),
                      ),
                      const _LandingDivider(),
                      Expanded(
                        child: _LandingStatusCell(
                          label: 'CURRENT ACTIVE',
                          value: activeLabel,
                          subtitle:
                              controller.selectedMissionId == null
                                  ? 'ACTIVE Mission 대기'
                                  : 'Jetson runtime 적용 중',
                          good:
                              controller.selectedMissionId != null,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _MissionActionTile extends StatelessWidget {
  const _MissionActionTile({
    super.key,
    required this.icon,
    required this.title,
    required this.description,
    required this.footer,
    required this.onTap,
    this.dark = false,
  });

  final IconData icon;
  final String title;
  final String description;
  final String footer;
  final VoidCallback? onTap;
  final bool dark;

  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null;
    final foreground =
        dark ? Colors.white : _tabletInk;
    final muted =
        dark ? const Color(0xffbfc5ca) : _tabletMuted;

    return Opacity(
      opacity: enabled ? 1 : 0.45,
      child: Material(
        color: dark ? _tabletDark : _tabletSurface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(
            color: dark ? _tabletDark : _tabletLine,
          ),
        ),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(12),
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: SizedBox(
              height: 225,
              child: Column(
                crossAxisAlignment:
                    CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 58,
                    height: 58,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: dark
                          ? const Color(0xff2b3034)
                          : _tabletSurfaceMuted,
                      border: Border.all(
                        color: dark
                            ? const Color(0xff41474c)
                            : _tabletLine,
                      ),
                      borderRadius:
                          BorderRadius.circular(12),
                    ),
                    child: Icon(
                      icon,
                      size: 31,
                      color: foreground,
                    ),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    title,
                    style: TextStyle(
                      color: foreground,
                      fontSize: 23,
                      fontWeight: FontWeight.w800,
                      letterSpacing: -0.6,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    description,
                    style: TextStyle(
                      color: muted,
                      fontSize: 13,
                      height: 1.45,
                    ),
                  ),
                  const Spacer(),
                  Row(
                    children: [
                      Text(
                        footer,
                        style: TextStyle(
                          color: foreground,
                          fontWeight: FontWeight.w800,
                          fontSize: 13,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Icon(
                        Icons.arrow_forward,
                        size: 18,
                        color: foreground,
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _LandingStatusCell extends StatelessWidget {
  const _LandingStatusCell({
    required this.label,
    required this.value,
    required this.subtitle,
    this.good = false,
  });

  final String label;
  final String value;
  final String subtitle;
  final bool good;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: 20,
          vertical: 17,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: const TextStyle(
                color: _tabletMuted,
                fontSize: 10,
                fontWeight: FontWeight.w800,
                letterSpacing: 0.7,
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                if (good) ...[
                  Container(
                    width: 8,
                    height: 8,
                    decoration: const BoxDecoration(
                      color: _tabletGreen,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 8),
                ],
                Flexible(
                  child: Text(
                    value,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: _tabletInk,
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              subtitle,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: _tabletMuted,
                fontSize: 11,
              ),
            ),
          ],
        ),
      );
}

class _LandingDivider extends StatelessWidget {
  const _LandingDivider();

  @override
  Widget build(BuildContext context) => Container(
        width: 1,
        height: 76,
        color: _tabletLine,
      );
}
