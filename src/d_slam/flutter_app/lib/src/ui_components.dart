part of 'jetson_app.dart';

class _SectionCard extends StatelessWidget {
  const _SectionCard({
    required this.title,
    required this.subtitle,
    required this.child,
    this.trailing,
  });

  final String title;
  final String subtitle;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 4),
                    Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
              if (trailing != null) ...[
                const SizedBox(width: 12),
                trailing!,
              ],
            ],
          ),
          const SizedBox(height: 16),
          child,
        ],
      ),
    ),
  );
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.label, required this.good});
  final String label;
  final bool good;
  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: (good ? const Color(0xff00a896) : const Color(0xffef476f))
          .withValues(alpha: 0.18),
      borderRadius: BorderRadius.circular(999),
      border: Border.all(
        color: good ? const Color(0xff00a896) : const Color(0xffef476f),
      ),
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      child: Text(label, style: Theme.of(context).textTheme.labelMedium),
    ),
  );
}

class _MiniLabel extends StatelessWidget {
  const _MiniLabel({required this.text, this.good});
  final String text;
  final bool? good;
  @override
  Widget build(BuildContext context) {
    final color = good == null
        ? Colors.white54
        : good!
        ? const Color(0xff06d6a0)
        : const Color(0xffffd166);
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.8)),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        child: Text(text, style: Theme.of(context).textTheme.labelSmall),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.color, required this.label});
  final Color color;
  final String label;
  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 5),
      Text(label, style: Theme.of(context).textTheme.labelSmall),
    ],
  );
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.icon, required this.title, required this.body});
  final IconData icon;
  final String title;
  final String body;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 38, color: Colors.white38),
          const SizedBox(height: 12),
          Text(title, style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 6),
          Text(
            body,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    ),
  );
}

class _MetricPill extends StatelessWidget {
  const _MetricPill({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: const Color(0xff0b1b1d),
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: const Color(0xff244044)),
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelSmall),
          const SizedBox(width: 8),
          Text(value, style: Theme.of(context).textTheme.labelLarge),
        ],
      ),
    ),
  );
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 130,
          child: Text(label, style: Theme.of(context).textTheme.bodySmall),
        ),
        Expanded(child: SelectableText(value)),
      ],
    ),
  );
}

class _EventLog extends StatelessWidget {
  const _EventLog({required this.events});
  final List<String> events;
  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: const Color(0xff071012),
      borderRadius: BorderRadius.circular(10),
    ),
    child: SizedBox(
      height: 150,
      child: events.isEmpty
          ? const _EmptyState(
              icon: Icons.notifications_none,
              title: '이벤트 대기',
              body: 'FastAPI WebSocket 이벤트가 표시됩니다.',
            )
          : ListView.separated(
              padding: const EdgeInsets.all(10),
              itemCount: math.min(events.length, 50),
              separatorBuilder: (_, _) => const Divider(height: 10),
              itemBuilder: (context, index) => Text(
                events[index],
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
    ),
  );
}

JsonMap? _asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((key, item) => MapEntry(key.toString(), item));
  return null;
}

List<JsonMap> _asObjectList(Object? value) {
  if (value is! List) return const [];
  return [for (final item in value) if (_asMap(item) case final JsonMap object) object];
}

String? _asString(Object? value) => value is String && value.isNotEmpty ? value : null;
int? _asInt(Object? value) => value is num ? value.toInt() : null;
double? _asDouble(Object? value) => value is num ? value.toDouble() : null;

String _formatNumber(Object? value, {int digits = 2}) {
  final number = _asDouble(value);
  return number == null ? '-' : number.toStringAsFixed(digits);
}

String _positionLabel(Object? value) {
  final point = _asMap(value);
  if (point == null) return '위치 없음';
  final x = _asDouble(point['x'] ?? point['map_x']);
  final y = _asDouble(point['y'] ?? point['map_y']);
  if (x == null || y == null) return '위치 없음';
  return '(${x.toStringAsFixed(2)}, ${y.toStringAsFixed(2)}) m';
}
