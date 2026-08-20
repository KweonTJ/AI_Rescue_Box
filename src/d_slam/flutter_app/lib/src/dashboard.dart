part of 'jetson_app.dart';

class _Dashboard extends StatelessWidget {
  const _Dashboard({
    required this.controller,
    required this.onChooseAnotherMission,
  });

  final JetsonController controller;
  final VoidCallback onChooseAnotherMission;

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 900;
    final missionLabel = controller.selectedMissionId == null
        ? 'Mission 미선택'
        : '${controller.selectedMissionId} · v${controller.selectedMissionVersion}';
    final content = [
      _StatusPanel(controller: controller),
      _MissionPanel(controller: controller),
      _MapPanel(controller: controller),
      _OperationPanels(controller: controller),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('AI Rescue Box · Jetson'),
            Text(
              '현재 Mission · $missionLabel',
              style: Theme.of(context).textTheme.labelMedium,
            ),
          ],
        ),
        actions: [
          TextButton.icon(
            key: const Key('choose-another-mission'),
            onPressed: controller.busy ? null : onChooseAnotherMission,
            icon: const Icon(Icons.swap_horiz),
            label: const Text('다른 구조도 선택'),
          ),
          const SizedBox(width: 8),
          _StatusBadge(
            label: controller.isMockMode ? 'MOCK' : 'REAL',
            good: !controller.isMockMode,
          ),
          const SizedBox(width: 10),
          _StatusBadge(
            label: controller.webSocketConnected ? 'WS 연결' : 'WS 대기',
            good: controller.webSocketConnected,
          ),
          const SizedBox(width: 16),
          IconButton(
            tooltip: '새로고침',
            onPressed: controller.busy ? null : controller.refresh,
            icon: const Icon(Icons.refresh),
          ),
          const SizedBox(width: 12),
        ],
      ),
      body: SafeArea(
        child: Stack(
          children: [
            Positioned.fill(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: compact
                    ? Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          for (final item in content) ...[
                            item,
                            const SizedBox(height: 14),
                          ],
                        ],
                      )
                    : Column(
                        children: [
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(
                                flex: 4,
                                child: Column(
                                  children: [
                                    content[0],
                                    const SizedBox(height: 14),
                                    content[1],
                                  ],
                                ),
                              ),
                              const SizedBox(width: 14),
                              Expanded(
                                flex: 6,
                                child: Column(
                                  children: [
                                    content[2],
                                    const SizedBox(height: 14),
                                    content[3],
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
              ),
            ),
            if (controller.busy)
              Positioned.fill(
                child: IgnorePointer(
                  child: ColoredBox(
                    color: Colors.black.withValues(alpha: 0.22),
                    child: const Center(child: CircularProgressIndicator()),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
