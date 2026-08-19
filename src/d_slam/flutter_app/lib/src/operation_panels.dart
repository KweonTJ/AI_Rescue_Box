part of 'jetson_app.dart';

class _OperationPanels extends StatelessWidget {
  const _OperationPanels({required this.controller});
  final JetsonController controller;

  @override
  Widget build(BuildContext context) {
    final hasMission = controller.selectedMissionId != null;
    return _SectionCard(
      title: '분석 · 전송 · 승인 계획',
      subtitle: 'Jetson 분석 결과와 Preview를 생성하고 Host 승인 계획을 확인합니다.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              FilledButton.icon(
                onPressed: controller.busy || !hasMission ? null : controller.runAnalysis,
                icon: const Icon(Icons.analytics_outlined),
                label: Text(controller.isMockMode ? 'Mock 분석' : '센서 분석'),
              ),
              FilledButton.tonalIcon(
                onPressed: controller.busy || controller.currentResult == null
                    ? null
                    : controller.sendResult,
                icon: const Icon(Icons.send_outlined),
                label: const Text('결과 전송'),
              ),
              OutlinedButton.icon(
                onPressed: controller.busy || !hasMission ? null : controller.createPreview,
                icon: const Icon(Icons.map_outlined),
                label: const Text('Preview 생성'),
              ),
              OutlinedButton.icon(
                onPressed: controller.busy || controller.preview == null
                    ? null
                    : controller.sendCurrentPreview,
                icon: const Icon(Icons.upload_outlined),
                label: const Text('Preview 전송'),
              ),
              OutlinedButton.icon(
                onPressed: controller.busy || !hasMission
                    ? null
                    : controller.refreshApprovedPlan,
                icon: const Icon(Icons.verified_outlined),
                label: const Text('Approved Plan 확인'),
              ),
            ],
          ),
          const SizedBox(height: 14),
          LinearProgressIndicator(value: controller.transferProgress.clamp(0, 1)),
          const SizedBox(height: 14),
          _SemanticDetails(result: controller.currentResult),
          if (controller.approvedPlan != null) ...[
            const SizedBox(height: 14),
            DecoratedBox(
              decoration: BoxDecoration(
                color: const Color(0xff0b1b1d),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xff244044)),
              ),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: SelectableText(
                  const JsonEncoder.withIndent('  ').convert(controller.approvedPlan),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
