part of 'jetson_app.dart';

class _SemanticDetails extends StatelessWidget {
  const _SemanticDetails({required this.result});

  final JsonMap? result;

  @override
  Widget build(BuildContext context) {
    final victims = _asObjectList(result?['victim_candidates']);
    final risks = _asObjectList(result?['risk_zones']);
    final routes = _asObjectList(result?['entry_routes']);
    final teams = _asObjectList(result?['team_recommendations']);
    if (result == null) {
      return const _EmptyState(
        icon: Icons.analytics_outlined,
        title: '분석 결과가 없습니다.',
        body: '선택한 임무에서 분석을 실행하면 semantic result 요약이 표시됩니다.',
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _MetricPill(label: '요구조자 후보', value: '${victims.length}'),
            _MetricPill(label: '위험 구역', value: '${risks.length}'),
            _MetricPill(label: '경로', value: '${routes.length}'),
            _MetricPill(label: '팀 추천', value: '${teams.length}'),
          ],
        ),
        const SizedBox(height: 12),
        if (victims.isNotEmpty)
          _CompactJsonList(
            title: '요구조자 후보',
            icon: Icons.person_search_outlined,
            items: victims,
            label: (item) =>
                _asString(item['detection_id']) ?? _asString(item['tracking_id']) ?? 'candidate',
            detail: (item) =>
                'confidence ${_formatNumber(item['confidence'])} · ${_positionLabel(item['map_position'] ?? item['position'])}',
          ),
        if (victims.isNotEmpty) const SizedBox(height: 10),
        if (risks.isNotEmpty)
          _CompactJsonList(
            title: '위험 구역',
            icon: Icons.warning_amber_rounded,
            items: risks,
            label: (item) =>
                _asString(item['risk_type']) ?? _asString(item['risk_id']) ?? 'risk',
            detail: (item) =>
                'severity ${_formatNumber(item['severity'])} · ${_asString(item['state']) ?? 'unknown'}',
          ),
        if (risks.isNotEmpty) const SizedBox(height: 10),
        if (teams.isNotEmpty)
          _CompactJsonList(
            title: '팀 추천',
            icon: Icons.groups_2_outlined,
            items: teams,
            label: (item) => _asString(item['team_id']) ?? 'team',
            detail: (item) =>
                '${_asString(item['victim_id']) ?? '대기'} · ${_positionLabel(item['position'])}',
          ),
      ],
    );
  }
}

class _CompactJsonList extends StatelessWidget {
  const _CompactJsonList({
    required this.title,
    required this.icon,
    required this.items,
    required this.label,
    required this.detail,
  });

  final String title;
  final IconData icon;
  final List<JsonMap> items;
  final String Function(JsonMap item) label;
  final String Function(JsonMap item) detail;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: const Color(0xff0b1b1d),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xff244044)),
    ),
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18),
              const SizedBox(width: 8),
              Text(title, style: Theme.of(context).textTheme.titleSmall),
            ],
          ),
          const SizedBox(height: 8),
          for (final item in items.take(6))
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: Text(label(item))),
                  const SizedBox(width: 12),
                  Flexible(
                    child: Text(
                      detail(item),
                      textAlign: TextAlign.right,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    ),
  );
}
