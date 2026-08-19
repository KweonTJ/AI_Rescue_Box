part of 'jetson_app.dart';

class _StatusPanel extends StatelessWidget {
  const _StatusPanel({required this.controller});
  final JetsonController controller;

  String get _apiConnectionLabel {
    if (controller.busy && controller.activeOperation == '초기 상태 확인') {
      return 'Jetson 연결 중';
    }
    if (controller.error != null && controller.health.isEmpty) {
      return 'Jetson 연결 실패';
    }
    if (controller.health['status'] == 'ok') return 'Jetson 연결됨';
    return 'Jetson 연결 대기';
  }

  @override
  Widget build(BuildContext context) {
    final uwb = controller.uwbProvider;
    return _SectionCard(
      title: 'Jetson 상태',
      subtitle: '센서/SLAM/UWB와 FastAPI runtime 상태를 확인합니다.',
      trailing: _StatusBadge(
        label: controller.health['status']?.toString() ?? 'unknown',
        good: controller.health['status'] == 'ok',
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _MetricPill(label: 'mode', value: controller.isMockMode ? 'mock' : 'real'),
              _MetricPill(label: 'mission', value: controller.selectedMissionId ?? '-'),
              _MetricPill(label: 'progress', value: '${(controller.transferProgress * 100).round()}%'),
            ],
          ),
          const SizedBox(height: 12),
          _InfoRow(label: 'API 연결', value: _apiConnectionLabel),
          if (controller.apiBaseUri != null)
            _InfoRow(label: 'Jetson API', value: controller.apiBaseUri.toString()),
          _InfoRow(label: '진행 상태', value: controller.progressStage),
          _InfoRow(
            label: 'UWB',
            value: uwb == null ? '상태 없음' : jsonEncode(uwb),
          ),
          _InfoRow(label: 'runtime', value: jsonEncode(controller.runtime)),
          if (controller.error != null) ...[
            const SizedBox(height: 8),
            Text(
              controller.error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: 12),
          _EventLog(events: controller.eventLog),
        ],
      ),
    );
  }
}
