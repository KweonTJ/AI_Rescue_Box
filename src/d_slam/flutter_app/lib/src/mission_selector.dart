part of 'jetson_app.dart';

class _MissionSelector extends StatelessWidget {
  const _MissionSelector({required this.controller, required this.onSelect});

  final JetsonController controller;
  final Future<void> Function(JsonMap mission) onSelect;

  bool get _connectionFailed => controller.error != null && controller.health.isEmpty;

  @override
  Widget build(BuildContext context) {
    final apiAddress = controller.apiBaseUri?.toString() ?? '기본 Jetson API 주소';
    return Scaffold(
      appBar: AppBar(
        title: const Text('ACTIVE Mission'),
        actions: [
          IconButton(
            tooltip: 'Mission 목록 새로고침',
            onPressed: controller.busy ? null : controller.refresh,
            icon: const Icon(Icons.refresh),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 860),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    '실제 사용할 Mission 선택',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Mission 관리에서 STORED된 버전 중 하나를 명시적으로 ACTIVE로 전환합니다.',
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                  const SizedBox(height: 18),
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
                      child: ListView.separated(
                        key: const Key('mission-selector-list'),
                        itemCount: controller.missions.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 12),
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
                  if (controller.error != null && !_connectionFailed) ...[
                    const SizedBox(height: 12),
                    Text(
                      controller.error!,
                      key: const Key('mission-selector-error'),
                      style: TextStyle(color: Theme.of(context).colorScheme.error),
                    ),
                  ],
                ],
              ),
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
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 56, color: Colors.white54),
          const SizedBox(height: 16),
          Text(title, textAlign: TextAlign.center, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          Text(body, textAlign: TextAlign.center),
          if (action != null) ...[
            const SizedBox(height: 18),
            action!,
          ],
        ],
      ),
    );
  }
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
    return Card(
      key: Key('mission-card-$missionId-v$version'),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: controller.busy || active ? null : onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Container(
                width: 128,
                height: 88,
                decoration: BoxDecoration(
                  color: const Color(0xff071012),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xff244044)),
                ),
                child: const Icon(Icons.map_outlined, size: 38, color: Colors.white54),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name, style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 4),
                    Text('$missionId · v$version'),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      children: [
                        _MiniLabel(text: verified ? '검증됨' : '저장됨', good: verified),
                        if (active) const _MiniLabel(text: '현재 ACTIVE', good: true),
                        if (received != null) _MiniLabel(text: received),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              FilledButton(
                key: Key('select-$missionId-v$version'),
                onPressed: controller.busy || active ? null : onTap,
                child: Text(active ? '현재 ACTIVE' : 'ACTIVE 전환'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
