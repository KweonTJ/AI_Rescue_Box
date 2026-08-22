import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'host_controller.dart';
import 'review_workspace.dart';

const _crInk = Color(0xff141719);
const _crMuted = Color(0xff68717a);
const _crLine = Color(0xffd7dce0);
const _crSurface = Color(0xffffffff);
const _crSurface2 = Color(0xfff5f6f7);
const _crDark = Color(0xff171a1d);
const _crGreen = Color(0xff1b8a5a);
const _crRed = Color(0xffc73737);
const _crOrange = Color(0xffd56b1f);
const _crBlue = Color(0xff1677a8);

final class CommandReviewWorkspace extends StatefulWidget {
  const CommandReviewWorkspace({super.key, required this.controller});
  final HostController controller;

  @override
  State<CommandReviewWorkspace> createState() => _CommandReviewWorkspaceState();
}

class _CommandReviewWorkspaceState extends State<CommandReviewWorkspace> {
  int _tab = 0;
  HostController get controller => widget.controller;

  @override
  Widget build(BuildContext context) {
    final semantic = controller.reviewedSemantic;
    final victims = [..._objects(semantic, 'confirmed_victims'), ..._objects(semantic, 'victim_candidates')];
    final risks = _objects(semantic, 'risk_zones');
    final routes = _objects(semantic, 'entry_routes');
    final teams = _objects(semantic, 'team_recommendations');
    final safe = _objects(semantic, 'safe_waiting_points');
    final groups = [victims, risks, routes, teams, safe];
    return ColoredBox(
      color: const Color(0xffeceff1),
      child: Column(
        children: [
          _AnalysisHeader(controller: controller, openAdvanced: _openAdvancedEditor),
          Expanded(
            child: LayoutBuilder(builder: (context, constraints) {
              if (constraints.maxWidth < 1050) {
                return ListView(
                  padding: const EdgeInsets.all(14),
                  children: [
                    _LayerPanel(controller: controller),
                    const SizedBox(height: 10),
                    SizedBox(height: 520, child: _CommandMap(controller: controller)),
                    const SizedBox(height: 10),
                    SizedBox(height: 560, child: _ReviewSide(controller: controller, tab: _tab, onTab: (v) => setState(() => _tab = v), items: groups[_tab])),
                  ],
                );
              }
              return Row(children: [
                SizedBox(width: 210, child: _LayerPanel(controller: controller)),
                Expanded(child: _CommandMap(controller: controller)),
                SizedBox(width: 350, child: _ReviewSide(controller: controller, tab: _tab, onTab: (v) => setState(() => _tab = v), items: groups[_tab])),
              ]);
            }),
          ),
          _ApprovalBar(controller: controller, openAdvanced: _openAdvancedEditor),
        ],
      ),
    );
  }

  Future<void> _openAdvancedEditor() async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => Dialog.fullscreen(
        child: Scaffold(
          appBar: AppBar(
            title: const Text('상세 편집 도구'),
            actions: [IconButton(onPressed: () => Navigator.pop(dialogContext), icon: const Icon(Icons.close))],
          ),
          body: ReviewWorkspace(controller: controller),
        ),
      ),
    );
  }
}

class _AnalysisHeader extends StatelessWidget {
  const _AnalysisHeader({required this.controller, required this.openAdvanced});
  final HostController controller;
  final VoidCallback openAdvanced;

  @override
  Widget build(BuildContext context) => Container(
    height: 58,
    color: _crSurface,
    padding: const EdgeInsets.symmetric(horizontal: 15),
    decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: _crLine))),
    child: Row(children: [
      Container(width: 8, height: 8, decoration: BoxDecoration(color: controller.missionId.isEmpty ? const Color(0xffb87a00) : _crGreen, shape: BoxShape.circle)),
      const SizedBox(width: 8),
      Expanded(child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(controller.missionId.isEmpty ? 'ACTIVE Mission 대기' : '${controller.missionName} · v${controller.missionVersion}', style: const TextStyle(color: _crInk, fontSize: 12, fontWeight: FontWeight.w800)),
        const SizedBox(height: 2),
        const Text('분석 결과 검토 및 구조 계획 승인', style: TextStyle(color: _crMuted, fontSize: 9)),
      ])),
      if (controller.results.isNotEmpty)
        SizedBox(
          width: 190,
          child: DropdownButtonFormField<int>(
            key: const Key('result-version-selector'),
            initialValue: controller.currentResultVersion > 0 ? controller.currentResultVersion : null,
            decoration: const InputDecoration(labelText: 'Semantic Result', contentPadding: EdgeInsets.symmetric(horizontal: 9, vertical: 6)),
            items: [for (final item in controller.results) if (_version(item) case final v?) DropdownMenuItem(value: v, child: Text('v$v'))],
            onChanged: controller.busy ? null : (value) { if (value != null) controller.selectResultVersion(value); },
          ),
        ),
      const SizedBox(width: 7),
      IconButton(key: const Key('review-undo'), tooltip: 'Undo', onPressed: controller.canUndo ? () => controller.applyReview({'action': 'undo'}) : null, icon: const Icon(Icons.undo)),
      IconButton(key: const Key('review-redo'), tooltip: 'Redo', onPressed: controller.canRedo ? () => controller.applyReview({'action': 'redo'}) : null, icon: const Icon(Icons.redo)),
      const SizedBox(width: 5),
      OutlinedButton.icon(onPressed: openAdvanced, icon: const Icon(Icons.tune, size: 17), label: const Text('상세 편집')),
    ]),
  );
}

class _LayerPanel extends StatelessWidget {
  const _LayerPanel({required this.controller});
  final HostController controller;
  @override
  Widget build(BuildContext context) => Container(
    color: _crSurface,
    padding: const EdgeInsets.all(12),
    child: ListView(children: [
      const Text('지도 레이어', style: TextStyle(color: _crMuted, fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: 1.1)),
      const SizedBox(height: 9),
      for (final layer in HostController.semanticLayers)
        Container(
          constraints: const BoxConstraints(minHeight: 40),
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xffedf0f2)))),
          child: Row(children: [
            Container(width: 9, height: 9, decoration: BoxDecoration(color: _layerColor(layer), borderRadius: BorderRadius.circular(2))),
            const SizedBox(width: 7),
            Expanded(child: Text(_layerLabel(layer), style: const TextStyle(fontSize: 9))),
            Switch.adaptive(value: controller.visibleLayers.contains(layer), onChanged: (value) => controller.setLayerVisible(layer, value)),
          ]),
        ),
      const SizedBox(height: 14),
      const Text('편집 도구', style: TextStyle(color: _crMuted, fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: 1.1)),
      const SizedBox(height: 8),
      OutlinedButton.icon(onPressed: () {}, icon: const Icon(Icons.ads_click, size: 16), label: const Text('선택')),
      const SizedBox(height: 6),
      OutlinedButton.icon(onPressed: () {}, icon: const Icon(Icons.edit_location_alt_outlined, size: 16), label: const Text('위치 보정')),
      const SizedBox(height: 6),
      OutlinedButton.icon(onPressed: () {}, icon: const Icon(Icons.polyline_outlined, size: 16), label: const Text('Risk Polygon')),
      const SizedBox(height: 6),
      FilledButton.tonalIcon(onPressed: () => _showAdvancedHint(context), icon: const Icon(Icons.open_in_full, size: 16), label: const Text('전체 편집 열기')),
    ]),
  );
}

void _showAdvancedHint(BuildContext context) {
  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('우측 상단의 상세 편집 버튼에서 모든 편집 기능을 사용할 수 있습니다.')));
}

class _CommandMap extends StatelessWidget {
  const _CommandMap({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) => Container(
    color: const Color(0xffe4e7e8),
    child: Column(children: [
      Container(
        height: 42,
        color: const Color(0xfff8f9f9),
        padding: const EdgeInsets.symmetric(horizontal: 11),
        child: Row(children: [
          const Icon(Icons.map_outlined, size: 17),
          const SizedBox(width: 7),
          const Expanded(child: Text('Mission Map · SLAM / Semantic Workspace', style: TextStyle(fontSize: 9, fontWeight: FontWeight.w800))),
          Text(controller.previewVersion > 0 ? 'SLAM Preview v${controller.previewVersion}' : 'Prior-map image는 UWB 미전송', style: const TextStyle(color: _crMuted, fontSize: 8)),
        ]),
      ),
      Expanded(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Container(
            decoration: BoxDecoration(color: const Color(0xfff3f4f3), border: Border.all(color: _crLine)),
            child: Stack(children: [
              Positioned.fill(child: CustomPaint(painter: _CommandMapPainter(controller))),
              Positioned(top: 10, left: 10, child: _MapTag(title: controller.currentResultVersion > 0 ? 'Semantic Result v${controller.currentResultVersion}' : '분석 결과 대기', subtitle: 'Mission metadata + live semantic/SLAM')),
              const Positioned(right: 10, bottom: 10, child: _MapLegend()),
            ]),
          ),
        ),
      ),
    ]),
  );
}

class _CommandMapPainter extends CustomPainter {
  _CommandMapPainter(this.controller);
  final HostController controller;

  @override
  void paint(Canvas canvas, Size size) {
    final grid = Paint()..color = const Color(0xffe2e5e6)..strokeWidth = 1;
    for (double x = 0; x < size.width; x += 42) canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    for (double y = 0; y < size.height; y += 42) canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    final semantic = controller.reviewedSemantic;
    final manifest = controller.currentMission ?? const <String, dynamic>{};
    final base = manifest['base_map'] is Map ? Map<String, dynamic>.from(manifest['base_map'] as Map) : manifest;
    final width = (base['width'] ?? manifest['base_map_width']) is num ? ((base['width'] ?? manifest['base_map_width']) as num).toDouble() : 1000.0;
    final height = (base['height'] ?? manifest['base_map_height']) is num ? ((base['height'] ?? manifest['base_map_height']) as num).toDouble() : 700.0;
    Offset screen(Object? raw) {
      final p = controller.semanticPoint(raw);
      if (p == null) return Offset(size.width / 2, size.height / 2);
      return Offset((p.x / math.max(1, width) * size.width).clamp(0, size.width), (p.y / math.max(1, height) * size.height).clamp(0, size.height));
    }
    if (controller.visibleLayers.contains('robot_trajectory')) {
      _polyline(canvas, size, _values(semantic['robot_trajectory']), screen, _crBlue, 3);
    }
    if (controller.visibleLayers.contains('entry_routes')) {
      for (final route in _objects(semantic, 'entry_routes')) _polyline(canvas, size, _pointList(route), screen, _crBlue, 4);
    }
    if (controller.visibleLayers.contains('risk_zones')) {
      for (final risk in _objects(semantic, 'risk_zones')) _polygon(canvas, _pointList(risk), screen, _crOrange);
    }
    if (controller.visibleLayers.contains('obstacles')) {
      for (final obstacle in _values(semantic['obstacles'])) _polygon(canvas, _pointListValue(obstacle), screen, const Color(0xff555b60));
    }
    if (controller.visibleLayers.contains('victim_candidates')) {
      for (final victim in _objects(semantic, 'victim_candidates')) _point(canvas, screen(victim), _crRed, hollow: true);
    }
    if (controller.visibleLayers.contains('confirmed_victims')) {
      for (final victim in _objects(semantic, 'confirmed_victims')) _point(canvas, screen(victim), _crRed);
    }
    if (controller.visibleLayers.contains('safe_waiting_points')) {
      for (final item in _objects(semantic, 'safe_waiting_points')) _point(canvas, screen(item), _crGreen);
    }
    final robot = semantic['robot_pose'];
    if (robot is Map) _point(canvas, screen(robot), _crBlue);
  }

  void _point(Canvas canvas, Offset p, Color color, {bool hollow = false}) {
    canvas.drawCircle(p, 8, Paint()..color = hollow ? Colors.white : color);
    canvas.drawCircle(p, 9, Paint()..color = color..style = PaintingStyle.stroke..strokeWidth = 2);
  }

  void _polyline(Canvas canvas, Size size, List<Object?> values, Offset Function(Object?) screen, Color color, double width) {
    final points = values.map(screen).toList();
    if (points.length < 2) return;
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (final p in points.skip(1)) path.lineTo(p.dx, p.dy);
    canvas.drawPath(path, Paint()..color = color..style = PaintingStyle.stroke..strokeWidth = width..strokeCap = StrokeCap.round);
  }

  void _polygon(Canvas canvas, List<Object?> values, Offset Function(Object?) screen, Color color) {
    final points = values.map(screen).toList();
    if (points.isEmpty) return;
    if (points.length == 1) { _point(canvas, points.first, color); return; }
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (final p in points.skip(1)) path.lineTo(p.dx, p.dy);
    if (points.length > 2) path.close();
    canvas.drawPath(path, Paint()..color = color.withValues(alpha: .20)..style = PaintingStyle.fill);
    canvas.drawPath(path, Paint()..color = color..style = PaintingStyle.stroke..strokeWidth = 2);
  }

  @override
  bool shouldRepaint(covariant _CommandMapPainter oldDelegate) => true;
}

class _ReviewSide extends StatelessWidget {
  const _ReviewSide({required this.controller, required this.tab, required this.onTab, required this.items});
  final HostController controller;
  final int tab;
  final ValueChanged<int> onTab;
  final List<Map<String, dynamic>> items;

  @override
  Widget build(BuildContext context) {
    const labels = ['요구조자', '위험지역', '경로', '팀 배치', 'Safe'];
    return Container(
      color: _crSurface,
      child: Column(children: [
        SizedBox(
          height: 49,
          child: Row(children: [for (var i = 0; i < labels.length; i++) Expanded(child: InkWell(onTap: () => onTab(i), child: Container(alignment: Alignment.center, decoration: BoxDecoration(border: Border(bottom: BorderSide(color: tab == i ? _crDark : _crLine, width: tab == i ? 2 : 1))), child: Text(labels[i], style: TextStyle(color: tab == i ? _crInk : _crMuted, fontSize: 8, fontWeight: FontWeight.w800)))))]),
        ),
        Padding(
          padding: const EdgeInsets.all(13),
          child: Row(children: [Expanded(child: Text('${labels[tab]} 검토', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800))), Text('${items.length} items', style: const TextStyle(color: _crMuted, fontSize: 8))]),
        ),
        const Divider(height: 1),
        Expanded(child: items.isEmpty ? const Center(child: Text('항목 없음', style: TextStyle(color: _crMuted))) : ListView.separated(itemCount: items.length, separatorBuilder: (_, _) => const Divider(height: 1), itemBuilder: (context, index) => _ReviewItem(tab: tab, item: items[index], index: index, controller: controller))),
        Padding(
          padding: const EdgeInsets.all(12),
          child: SizedBox(width: double.infinity, child: FilledButton.tonalIcon(onPressed: () => _openFullEditor(context, controller), icon: const Icon(Icons.tune, size: 16), label: const Text('전체 상세 편집'))),
        ),
      ]),
    );
  }
}

class _ReviewItem extends StatelessWidget {
  const _ReviewItem({required this.tab, required this.item, required this.index, required this.controller});
  final int tab;
  final Map<String, dynamic> item;
  final int index;
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final fallback = const ['Victim', 'Risk', 'Route', 'Team', 'Safe'][tab];
    final id = _entityId(item, index, fallback);
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Container(width: 30, height: 30, alignment: Alignment.center, decoration: BoxDecoration(color: _tabColor(tab).withValues(alpha: .12), borderRadius: BorderRadius.circular(tab == 0 ? 15 : 7)), child: Text('${index + 1}', style: TextStyle(color: _tabColor(tab), fontSize: 9, fontWeight: FontWeight.w900))),
          const SizedBox(width: 9),
          Expanded(child: Text(id, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800))),
          Text(_shortMeta(item), style: const TextStyle(color: _crMuted, fontSize: 8)),
        ]),
        if (tab == 0) ...[
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: OutlinedButton(key: Key('confirm-victim-$index'), onPressed: () => controller.applyReview({'action': 'set_victim_status', 'victim_id': id, 'status': 'confirmed'}), child: const Text('구조 대상'))),
            const SizedBox(width: 6),
            Expanded(child: OutlinedButton(onPressed: () => controller.applyReview({'action': 'set_victim_status', 'victim_id': id, 'status': 'excluded'}), child: const Text('제외'))),
          ]),
        ] else if (tab == 2) ...[
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: OutlinedButton(key: Key('approve-route-$index'), onPressed: () => controller.applyReview({'action': 'set_route_approved', 'route_id': id, 'approved': true}), child: const Text('계획 포함'))),
            const SizedBox(width: 6),
            Expanded(child: OutlinedButton(onPressed: () => controller.applyReview({'action': 'set_route_approved', 'route_id': id, 'approved': false}), child: const Text('제외'))),
          ]),
        ],
      ]),
    );
  }
}

Future<void> _openFullEditor(BuildContext context, HostController controller) async {
  await showDialog<void>(context: context, builder: (dialogContext) => Dialog.fullscreen(child: Scaffold(appBar: AppBar(title: const Text('전체 검토 편집'), actions: [IconButton(onPressed: () => Navigator.pop(dialogContext), icon: const Icon(Icons.close))]), body: ReviewWorkspace(controller: controller))));
}

class _ApprovalBar extends StatelessWidget {
  const _ApprovalBar({required this.controller, required this.openAdvanced});
  final HostController controller;
  final VoidCallback openAdvanced;
  @override
  Widget build(BuildContext context) => Container(
    height: 64,
    color: _crSurface,
    padding: const EdgeInsets.symmetric(horizontal: 15),
    decoration: const BoxDecoration(border: Border(top: BorderSide(color: _crLine))),
    child: Row(children: [
      Expanded(child: Row(children: [
        _PlanStage(label: controller.currentResultVersion > 0 ? 'Result v${controller.currentResultVersion} 검토' : 'Result 대기', done: controller.currentResultVersion > 0),
        const _StageLine(),
        _PlanStage(label: controller.latestApprovedPlanVersion > 0 ? 'Plan v${controller.latestApprovedPlanVersion}' : 'Plan Draft', done: controller.latestApprovedPlanVersion > 0),
        const _StageLine(),
        const _PlanStage(label: 'Jetson 전송', done: false),
      ])),
      OutlinedButton(onPressed: openAdvanced, child: const Text('상세 편집')),
      const SizedBox(width: 8),
      FilledButton.icon(
        key: const Key('send-approved-plan'),
        onPressed: controller.currentResult == null || controller.busy ? null : controller.buildAndSendApprovedPlan,
        style: FilledButton.styleFrom(backgroundColor: _crGreen),
        icon: const Icon(Icons.verified_outlined),
        label: const Text('최종 구조 계획 생성 · Approved Plan 전송'),
      ),
    ]),
  );
}

class _PlanStage extends StatelessWidget {
  const _PlanStage({required this.label, required this.done});
  final String label;
  final bool done;
  @override
  Widget build(BuildContext context) => Row(children: [Container(width: 19, height: 19, alignment: Alignment.center, decoration: BoxDecoration(color: done ? const Color(0xffe7f4ed) : Colors.white, shape: BoxShape.circle, border: Border.all(color: done ? _crGreen : _crLine)), child: Text(done ? '✓' : '•', style: TextStyle(color: done ? _crGreen : _crMuted, fontSize: 8))), const SizedBox(width: 5), Text(label, style: TextStyle(color: done ? _crGreen : _crMuted, fontSize: 8, fontWeight: FontWeight.w700))]);
}

class _StageLine extends StatelessWidget {
  const _StageLine();
  @override
  Widget build(BuildContext context) => Container(width: 18, height: 1, margin: const EdgeInsets.symmetric(horizontal: 6), color: _crLine);
}

class _MapTag extends StatelessWidget {
  const _MapTag({required this.title, required this.subtitle});
  final String title;
  final String subtitle;
  @override
  Widget build(BuildContext context) => Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: Colors.white.withValues(alpha: .94), border: Border.all(color: _crLine), borderRadius: BorderRadius.circular(5)), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: const TextStyle(fontSize: 8, fontWeight: FontWeight.w800)), const SizedBox(height: 2), Text(subtitle, style: const TextStyle(color: _crMuted, fontSize: 7))]));
}

class _MapLegend extends StatelessWidget {
  const _MapLegend();
  @override
  Widget build(BuildContext context) => Container(padding: const EdgeInsets.all(8), decoration: BoxDecoration(color: Colors.white.withValues(alpha: .96), border: Border.all(color: _crLine), borderRadius: BorderRadius.circular(6)), child: const Row(mainAxisSize: MainAxisSize.min, children: [
    _LegendDot(color: _crBlue, text: 'Robot/Route'), SizedBox(width: 8), _LegendDot(color: _crRed, text: 'Victim'), SizedBox(width: 8), _LegendDot(color: _crOrange, text: 'Risk'), SizedBox(width: 8), _LegendDot(color: _crGreen, text: 'Safe'),
  ]));
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.text});
  final Color color;
  final String text;
  @override
  Widget build(BuildContext context) => Row(children: [Container(width: 7, height: 7, decoration: BoxDecoration(color: color, shape: BoxShape.circle)), const SizedBox(width: 4), Text(text, style: const TextStyle(fontSize: 7))]);
}

List<Map<String, dynamic>> _objects(Map<String, dynamic> value, String key) =>
  value[key] is List ? (value[key] as List).whereType<Map>().map((v) => Map<String, dynamic>.from(v)).toList() : const [];

List<Object?> _values(Object? value) => value is List ? value : const [];

List<Object?> _pointList(Map<String, dynamic> value) {
  for (final key in const ['points', 'path', 'polygon', 'coordinates']) {
    if (value[key] is List) return value[key] as List;
  }
  return const [];
}

List<Object?> _pointListValue(Object? value) {
  if (value is List) return value;
  if (value is Map) return _pointList(Map<String, dynamic>.from(value));
  return const [];
}

int? _version(Map<String, dynamic> value) {
  final raw = value['result_version'] ?? value['version'];
  return raw is num ? raw.toInt() : null;
}

String _entityId(Map<String, dynamic> item, int index, String fallback) {
  for (final key in const ['detection_id', 'victim_id', 'risk_id', 'route_id', 'team_id', 'waiting_id', 'id']) {
    final value = item[key];
    if (value is String && value.isNotEmpty) return value;
  }
  return '$fallback ${index + 1}';
}

String _shortMeta(Map<String, dynamic> item) {
  for (final key in const ['host_status', 'risk_type', 'state', 'confidence', 'risk_cost']) {
    final value = item[key];
    if (value != null) return '$value';
  }
  return '';
}

Color _tabColor(int tab) => switch (tab) { 0 => _crRed, 1 => _crOrange, 2 => _crBlue, 3 => _crDark, _ => _crGreen };
Color _layerColor(String layer) => switch (layer) {
  'robot_trajectory' || 'entry_routes' => _crBlue,
  'victim_candidates' || 'confirmed_victims' => _crRed,
  'risk_zones' => _crOrange,
  'safe_waiting_points' => _crGreen,
  'obstacles' => const Color(0xff555b60),
  _ => const Color(0xffa0a7ac),
};
String _layerLabel(String layer) => switch (layer) {
  'slam_preview' => 'SLAM Preview',
  'robot_trajectory' => 'Robot / 궤적',
  'victim_candidates' => 'Victim 후보',
  'confirmed_victims' => 'Victim 확인',
  'obstacles' => 'Obstacle',
  'risk_zones' => 'Risk',
  'explored_areas' => 'Explored',
  'unknown_areas' => 'Unknown',
  'entry_routes' => 'Route',
  'team_recommendations' => 'Team',
  'safe_waiting_points' => 'Safe Point',
  _ => layer,
};
