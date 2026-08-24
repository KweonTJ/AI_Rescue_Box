import 'package:flutter/material.dart';

import 'host_controller.dart';
import 'review_workspace.dart';

const _ink = Color(0xff141719);
const _muted = Color(0xff68717a);
const _line = Color(0xffd7dce0);
const _surface = Color(0xffffffff);
const _green = Color(0xff1b8a5a);
const _red = Color(0xffc73737);
const _orange = Color(0xffd56b1f);
const _blue = Color(0xff1677a8);
const _purple = Color(0xff7656a8);
const _gray = Color(0xff5b636a);

const _layerOrder = <String>[
  'robot_pose',
  'victim_candidates',
  'confirmed_victims',
  'obstacles',
  'risk_zones',
  'explored_areas',
  'unknown_areas',
  'entry_routes',
  'return_routes',
  'safe_waiting_points',
  'team_recommendations',
];

final class CommandReviewWorkspace extends StatefulWidget {
  const CommandReviewWorkspace({super.key, required this.controller});
  final HostController controller;

  @override
  State<CommandReviewWorkspace> createState() => _CommandReviewWorkspaceState();
}

class _CommandReviewWorkspaceState extends State<CommandReviewWorkspace> {
  final Set<String> _visible = _layerOrder.toSet();

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final semantic = c.reviewedSemantic;
    final updated = semantic['created_at']?.toString() ?? '분석 결과 대기';
    final bridge = c.bridgeStatus;
    final uwbGood = bridge['connected'] == true || bridge['state'] == 'connected';
    return ColoredBox(
      color: const Color(0xffeceff1),
      child: Column(
        children: [
          Container(
            constraints: const BoxConstraints(minHeight: 58),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: const BoxDecoration(
              color: _surface,
              border: Border(bottom: BorderSide(color: _line)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        c.missionId.isEmpty
                            ? 'ACTIVE Mission 대기'
                            : '${c.missionName} · v${c.missionVersion}',
                        style: const TextStyle(
                          color: _ink,
                          fontSize: 12,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        '마지막 지도 갱신: $updated',
                        style: const TextStyle(color: _muted, fontSize: 9),
                      ),
                    ],
                  ),
                ),
                _Chip(text: 'UWB ${uwbGood ? '연결됨' : '대기'}', good: uwbGood),
                const SizedBox(width: 8),
                IconButton(
                  onPressed: c.canUndo
                      ? () => c.applyReview({'action': 'undo'})
                      : null,
                  icon: const Icon(Icons.undo),
                ),
                IconButton(
                  onPressed: c.canRedo
                      ? () => c.applyReview({'action': 'redo'})
                      : null,
                  icon: const Icon(Icons.redo),
                ),
                OutlinedButton.icon(
                  onPressed: () => _advanced(context, c),
                  icon: const Icon(Icons.tune, size: 16),
                  label: const Text('상세 편집'),
                ),
              ],
            ),
          ),
          Expanded(
            child: LayoutBuilder(
              builder: (context, box) {
                final layers = _LayerPanel(
                  visible: _visible,
                  onChanged: (key, value) => setState(() {
                    value ? _visible.add(key) : _visible.remove(key);
                  }),
                );
                final map = _Map(controller: c, visible: _visible);
                final review = _RouteReview(controller: c, semantic: semantic);
                if (box.maxWidth < 1000) {
                  return ListView(
                    padding: const EdgeInsets.all(12),
                    children: [
                      SizedBox(height: 310, child: layers),
                      const SizedBox(height: 10),
                      SizedBox(height: 520, child: map),
                      const SizedBox(height: 10),
                      SizedBox(height: 520, child: review),
                    ],
                  );
                }
                return Row(
                  children: [
                    SizedBox(width: 220, child: layers),
                    Expanded(child: map),
                    SizedBox(width: 360, child: review),
                  ],
                );
              },
            ),
          ),
          Container(
            constraints: const BoxConstraints(minHeight: 62),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: const BoxDecoration(
              color: _surface,
              border: Border(top: BorderSide(color: _line)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    c.currentResultVersion > 0
                        ? 'Semantic v${c.currentResultVersion} · Human-in-the-Loop 검토'
                        : 'Semantic Result 대기',
                    style: const TextStyle(color: _muted, fontSize: 9),
                  ),
                ),
                FilledButton.icon(
                  onPressed: c.currentResult == null || c.busy
                      ? null
                      : c.buildAndSendApprovedPlan,
                  style: FilledButton.styleFrom(backgroundColor: _green),
                  icon: const Icon(Icons.verified_outlined),
                  label: const Text('Approved Plan 생성 · Jetson 전송'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.text, required this.good});
  final String text;
  final bool good;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
        decoration: BoxDecoration(
          color: good ? const Color(0xffe7f4ed) : const Color(0xfffff4d9),
          borderRadius: BorderRadius.circular(99),
        ),
        child: Text(
          text,
          style: TextStyle(
            color: good ? _green : const Color(0xff9a6800),
            fontSize: 9,
            fontWeight: FontWeight.w800,
          ),
        ),
      );
}

class _LayerPanel extends StatelessWidget {
  const _LayerPanel({required this.visible, required this.onChanged});
  final Set<String> visible;
  final void Function(String, bool) onChanged;

  @override
  Widget build(BuildContext context) => Container(
        color: _surface,
        padding: const EdgeInsets.all(12),
        child: ListView(
          children: [
            const Text(
              'RESCUE MAP LAYERS',
              style: TextStyle(
                color: _muted,
                fontSize: 9,
                fontWeight: FontWeight.w900,
                letterSpacing: 1.1,
              ),
            ),
            const SizedBox(height: 8),
            for (final layer in _layerOrder)
              SizedBox(
                height: 40,
                child: Row(
                  children: [
                    Container(
                      width: 9,
                      height: 9,
                      decoration: BoxDecoration(
                        color: _color(layer),
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                    const SizedBox(width: 7),
                    Expanded(
                      child: Text(
                        _label(layer),
                        style: const TextStyle(fontSize: 9),
                      ),
                    ),
                    Switch.adaptive(
                      value: visible.contains(layer),
                      onChanged: (value) => onChanged(layer, value),
                    ),
                  ],
                ),
              ),
          ],
        ),
      );
}

class _Map extends StatelessWidget {
  const _Map({required this.controller, required this.visible});
  final HostController controller;
  final Set<String> visible;

  @override
  Widget build(BuildContext context) => Container(
        color: const Color(0xffe4e7e8),
        padding: const EdgeInsets.all(12),
        child: Container(
          decoration: BoxDecoration(
            color: const Color(0xfff4f5f4),
            border: Border.all(color: _line),
          ),
          child: Stack(
            children: [
              Positioned.fill(
                child: CustomPaint(painter: _Painter(controller, visible)),
              ),
              const Positioned(right: 10, bottom: 10, child: _Legend()),
            ],
          ),
        ),
      );
}

class _Painter extends CustomPainter {
  _Painter(this.controller, this.visible);
  final HostController controller;
  final Set<String> visible;

  @override
  void paint(Canvas canvas, Size size) {
    final semantic = controller.reviewedSemantic;
    final width =
        (controller.imageWidth <= 1 ? 1000 : controller.imageWidth).toDouble();
    final height =
        (controller.imageHeight <= 1 ? 700 : controller.imageHeight).toDouble();

    Offset screen(Object? value) {
      final point = controller.semanticPoint(value);
      if (point == null) return Offset.zero;
      return Offset(
        (point.x / width) * size.width,
        (point.y / height) * size.height,
      );
    }

    void marker(Object? value, Color color) {
      canvas.drawCircle(screen(value), 7, Paint()..color = color);
    }

    void line(List<Object?> values, Color color, [double stroke = 3]) {
      final points = values.map(screen).toList();
      if (points.length < 2) return;
      final path = Path()..moveTo(points.first.dx, points.first.dy);
      for (final point in points.skip(1)) {
        path.lineTo(point.dx, point.dy);
      }
      final paint = Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke;
      canvas.drawPath(path, paint);
    }

    void polygon(List<Object?> values, Color color) {
      final points = values.map(screen).toList();
      if (points.length < 2) return;
      final path = Path()..moveTo(points.first.dx, points.first.dy);
      for (final point in points.skip(1)) {
        path.lineTo(point.dx, point.dy);
      }
      if (points.length > 2) path.close();
      canvas.drawPath(
        path,
        Paint()..color = color.withValues(alpha: .18),
      );
    }

    if (visible.contains('explored_areas')) {
      for (final area in _values(semantic['explored_areas'])) {
        polygon(_pointValues(area), const Color(0xff7ca087));
      }
    }
    if (visible.contains('unknown_areas')) {
      for (final area in _values(semantic['unknown_areas'])) {
        polygon(_pointValues(area), const Color(0xff9aa1a7));
      }
    }
    if (visible.contains('risk_zones')) {
      for (final risk in _objects(semantic, 'risk_zones')) {
        polygon(_pointValues(risk['polygon']), _orange);
      }
    }
    if (visible.contains('obstacles')) {
      for (final obstacle in _values(semantic['obstacles'])) {
        polygon(_pointValues(obstacle), _gray);
      }
    }
    if (visible.contains('entry_routes')) {
      for (final route in _objects(semantic, 'entry_routes')) {
        line(_pointValues(route['points']), _blue, 4);
      }
    }
    if (visible.contains('return_routes')) {
      for (final route in _objects(semantic, 'return_routes')) {
        line(_pointValues(route['points']), _purple, 4);
      }
    }
    if (visible.contains('victim_candidates')) {
      for (final item in _objects(semantic, 'victim_candidates')) {
        marker(item['map_position'] ?? item['position'], _red);
      }
    }
    if (visible.contains('confirmed_victims')) {
      for (final item in _objects(semantic, 'confirmed_victims')) {
        marker(item['map_position'] ?? item['position'], _red);
      }
    }
    if (visible.contains('safe_waiting_points')) {
      for (final item in _values(semantic['safe_waiting_points'])) {
        marker(item, _green);
      }
    }
    if (visible.contains('team_recommendations')) {
      for (final item in _objects(semantic, 'team_recommendations')) {
        marker(item['position'] ?? item, _gray);
      }
    }
    if (visible.contains('robot_pose') && semantic['robot_pose'] is Map) {
      marker(semantic['robot_pose'], _blue);
    }
  }

  @override
  bool shouldRepaint(covariant _Painter oldDelegate) =>
      oldDelegate.controller.reviewRevision != controller.reviewRevision ||
      oldDelegate.visible != visible;
}

class _RouteReview extends StatelessWidget {
  const _RouteReview({required this.controller, required this.semantic});
  final HostController controller;
  final Map<String, dynamic> semantic;

  @override
  Widget build(BuildContext context) {
    final entries = _objects(semantic, 'entry_routes');
    final returns = _objects(semantic, 'return_routes');
    return Container(
      color: _surface,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          const Text(
            '경로 검토',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 4),
          const Text(
            '진입 경로와 복귀 경로를 별도 레이어로 승인·제외·수정합니다.',
            style: TextStyle(color: _muted, fontSize: 9),
          ),
          const SizedBox(height: 12),
          _RouteGroup(
            title: '진입 경로',
            color: _blue,
            routes: entries,
            controller: controller,
          ),
          const SizedBox(height: 14),
          _RouteGroup(
            title: '복귀 경로',
            color: _purple,
            routes: returns,
            controller: controller,
          ),
        ],
      ),
    );
  }
}

class _RouteGroup extends StatelessWidget {
  const _RouteGroup({
    required this.title,
    required this.color,
    required this.routes,
    required this.controller,
  });
  final String title;
  final Color color;
  final List<Map<String, dynamic>> routes;
  final HostController controller;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              ),
              const SizedBox(width: 6),
              Text(
                '$title · ${routes.length}',
                style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800),
              ),
            ],
          ),
          const SizedBox(height: 6),
          if (routes.isEmpty)
            const Text(
              '경로 없음',
              style: TextStyle(color: _muted, fontSize: 9),
            ),
          for (final route in routes)
            _RouteCard(route: route, color: color, controller: controller),
        ],
      );
}

class _RouteCard extends StatelessWidget {
  const _RouteCard({
    required this.route,
    required this.color,
    required this.controller,
  });
  final Map<String, dynamic> route;
  final Color color;
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final id = route['route_id']?.toString() ?? 'route';
    return Container(
      margin: const EdgeInsets.only(top: 7),
      padding: const EdgeInsets.all(9),
      decoration: BoxDecoration(
        border: Border.all(color: color.withValues(alpha: .35)),
        borderRadius: BorderRadius.circular(7),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            id,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 3),
          Text(
            'goal=${route['goal_type'] ?? '-'} · risk=${route['risk_cost'] ?? '-'} · rank=${route['rank'] ?? '-'}',
            style: const TextStyle(color: _muted, fontSize: 8),
          ),
          const SizedBox(height: 7),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => controller.applyReview({
                    'action': 'set_route_approved',
                    'route_id': id,
                    'approved': true,
                  }),
                  child: const Text('승인'),
                ),
              ),
              const SizedBox(width: 5),
              Expanded(
                child: OutlinedButton(
                  onPressed: () => controller.applyReview({
                    'action': 'set_route_approved',
                    'route_id': id,
                    'approved': false,
                  }),
                  child: const Text('제외'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 5),
          OutlinedButton.icon(
            onPressed: () => _editRoute(context, controller, id, route),
            icon: const Icon(Icons.polyline_outlined, size: 15),
            label: const Text('경유점 수정'),
          ),
        ],
      ),
    );
  }
}

Future<void> _editRoute(
  BuildContext context,
  HostController controller,
  String id,
  Map<String, dynamic> route,
) async {
  final points = _pointValues(route['points'])
      .whereType<Map>()
      .map((item) => Map<String, dynamic>.from(item))
      .toList();
  if (points.length < 2) return;
  final first = points.first;
  final last = points.last;
  final x0 = (((first['x'] as num?)?.toDouble() ?? 0) +
          ((last['x'] as num?)?.toDouble() ?? 0)) /
      2;
  final y0 = (((first['y'] as num?)?.toDouble() ?? 0) +
          ((last['y'] as num?)?.toDouble() ?? 0)) /
      2;
  final x = TextEditingController(text: x0.toStringAsFixed(2));
  final y = TextEditingController(text: y0.toStringAsFixed(2));
  final ok = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('경유점 수정'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: x,
            decoration: const InputDecoration(labelText: 'X (m)'),
          ),
          TextField(
            controller: y,
            decoration: const InputDecoration(labelText: 'Y (m)'),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext, false),
          child: const Text('취소'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(dialogContext, true),
          child: const Text('적용'),
        ),
      ],
    ),
  );
  if (ok != true) return;
  final px = double.tryParse(x.text);
  final py = double.tryParse(y.text);
  if (px == null || py == null) return;
  await controller.applyReview({
    'action': 'modify_route',
    'route_id': id,
    'route': {
      'points': [
        first,
        {'x': px, 'y': py},
        last,
      ],
      if (route['start'] != null) 'start': route['start'],
      if (route['goal'] != null) 'goal': route['goal'],
      if (route['goal_type'] != null) 'goal_type': route['goal_type'],
    },
  });
}

Future<void> _advanced(
  BuildContext context,
  HostController controller,
) async {
  await showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog.fullscreen(
      child: Scaffold(
        appBar: AppBar(
          title: const Text('상세 편집 도구'),
          actions: [
            IconButton(
              onPressed: () => Navigator.pop(dialogContext),
              icon: const Icon(Icons.close),
            ),
          ],
        ),
        body: ReviewWorkspace(controller: controller),
      ),
    ),
  );
}

class _Legend extends StatelessWidget {
  const _Legend();

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: .95),
          border: Border.all(color: _line),
          borderRadius: BorderRadius.circular(6),
        ),
        child: const Wrap(
          spacing: 8,
          runSpacing: 5,
          children: [
            _LegendItem(color: _blue, text: 'AI Rescue Box / 진입'),
            _LegendItem(color: _purple, text: '복귀'),
            _LegendItem(color: _red, text: '요구조자'),
            _LegendItem(color: _orange, text: '위험'),
            _LegendItem(color: _green, text: 'Safe Zone'),
            _LegendItem(color: _gray, text: '구조팀'),
          ],
        ),
      );
}

class _LegendItem extends StatelessWidget {
  const _LegendItem({required this.color, required this.text});
  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 4),
          Text(text, style: const TextStyle(fontSize: 7)),
        ],
      );
}

List<Map<String, dynamic>> _objects(
  Map<String, dynamic> value,
  String key,
) =>
    value[key] is List
        ? (value[key] as List)
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList()
        : const [];

List<Object?> _values(Object? value) => value is List ? value : const [];

List<Object?> _pointValues(Object? value) {
  if (value is List) return value;
  if (value is Map) {
    final map = Map<String, dynamic>.from(value);
    for (final key in const ['points', 'polygon', 'path', 'coordinates']) {
      if (map[key] is List) return map[key] as List;
    }
  }
  return const [];
}

Color _color(String layer) => switch (layer) {
      'robot_pose' || 'entry_routes' => _blue,
      'return_routes' => _purple,
      'victim_candidates' || 'confirmed_victims' => _red,
      'risk_zones' => _orange,
      'safe_waiting_points' => _green,
      'team_recommendations' || 'obstacles' => _gray,
      'explored_areas' => const Color(0xff7ca087),
      _ => const Color(0xff9aa1a7),
    };

String _label(String layer) => switch (layer) {
      'robot_pose' => 'AI Rescue Box 현재 위치',
      'victim_candidates' => '요구조자 후보',
      'confirmed_victims' => '확인 요구조자',
      'obstacles' => '장애물',
      'risk_zones' => '위험구역',
      'explored_areas' => '탐색 영역',
      'unknown_areas' => '미탐색 영역',
      'entry_routes' => '진입 경로',
      'return_routes' => '복귀 경로',
      'safe_waiting_points' => 'Safe Zone',
      'team_recommendations' => '구조팀 배치',
      _ => layer,
    };
