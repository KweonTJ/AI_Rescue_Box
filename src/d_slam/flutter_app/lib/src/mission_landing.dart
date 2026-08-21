part of 'jetson_app.dart';

/// Bounded landing page used by the Tablet shell.
///
/// This intentionally avoids flex children with unbounded ListView height so it
/// remains stable on both Galaxy Tab landscape and portrait layouts.
class _MissionLandingPage extends StatelessWidget {
  const _MissionLandingPage({required this.controller});

  final JetsonController controller;

  @override
  Widget build(BuildContext context) {
    final connected = controller.error == null || controller.health.isNotEmpty;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mission 관리'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            onPressed: controller.busy ? null : controller.refresh,
            icon: const Icon(Icons.refresh),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 980),
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Text('현장 Mission 설정', style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: 8),
                Text(
                  '구조도와 위치 정보를 만들거나 수정합니다. 저장 후 실제 사용 버전은 ACTIVE 페이지에서 선택합니다.',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 22),
                if (!connected) ...[
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Wrap(
                        spacing: 14,
                        runSpacing: 12,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          const Icon(Icons.cloud_off_outlined, size: 32),
                          SizedBox(
                            width: 520,
                            child: Text('Jetson 연결을 먼저 확인하세요.\n${controller.error ?? ''}'),
                          ),
                          FilledButton.icon(
                            onPressed: controller.busy ? null : controller.initialise,
                            icon: const Icon(Icons.refresh),
                            label: const Text('재시도'),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                ],
                LayoutBuilder(
                  builder: (context, constraints) {
                    final items = <Widget>[
                      _LandingActionCard(
                        key: const Key('new-mission-action'),
                        icon: Icons.add_photo_alternate_outlined,
                        title: '새 Mission 만들기',
                        description: '태블릿의 JPG/PNG 구조도를 선택하고 축척, 로봇 시작 위치, 출입구를 지정합니다.',
                        buttonLabel: '새로 만들기',
                        onPressed: !connected
                            ? null
                            : () async {
                                await Navigator.of(context).push(
                                  MaterialPageRoute<void>(
                                    builder: (_) => _MissionEditorPage(controller: controller),
                                  ),
                                );
                              },
                      ),
                      _LandingActionCard(
                        key: const Key('edit-mission-action'),
                        icon: Icons.folder_copy_outlined,
                        title: '기존 Mission 수정',
                        description: 'Jetson 보관함의 기존 버전을 불러옵니다. 수정본은 v2, v3처럼 새 버전으로 저장됩니다.',
                        buttonLabel: 'Mission 보관함',
                        onPressed: !connected || controller.missions.isEmpty
                            ? null
                            : () async {
                                await Navigator.of(context).push(
                                  MaterialPageRoute<void>(
                                    builder: (_) => _MissionLibraryPage(controller: controller),
                                  ),
                                );
                              },
                      ),
                    ];
                    if (constraints.maxWidth < 700) {
                      return Column(
                        children: [items[0], const SizedBox(height: 14), items[1]],
                      );
                    }
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(child: items[0]),
                        const SizedBox(width: 16),
                        Expanded(child: items[1]),
                      ],
                    );
                  },
                ),
                const SizedBox(height: 18),
                _SectionCard(
                  title: 'Jetson Mission 보관함',
                  subtitle: 'Mission 생성/수정과 실제 ACTIVE 선택은 서로 분리됩니다.',
                  child: controller.missions.isEmpty
                      ? const _EmptyState(
                          icon: Icons.folder_off_outlined,
                          title: '저장된 Mission이 없습니다.',
                          body: '새 Mission을 만들면 여기에 추가됩니다.',
                        )
                      : Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            _MetricPill(label: '저장 버전', value: '${controller.missions.length}'),
                            _MetricPill(
                              label: 'ACTIVE',
                              value: controller.selectedMissionId == null
                                  ? '없음'
                                  : '${controller.selectedMissionId} v${controller.selectedMissionVersion}',
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

class _LandingActionCard extends StatelessWidget {
  const _LandingActionCard({
    super.key,
    required this.icon,
    required this.title,
    required this.description,
    required this.buttonLabel,
    required this.onPressed,
  });

  final IconData icon;
  final String title;
  final String description;
  final String buttonLabel;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, size: 42),
              const SizedBox(height: 16),
              Text(title, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Text(description),
              const SizedBox(height: 22),
              SizedBox(
                width: double.infinity,
                child: FilledButton(onPressed: onPressed, child: Text(buttonLabel)),
              ),
            ],
          ),
        ),
      );
}
