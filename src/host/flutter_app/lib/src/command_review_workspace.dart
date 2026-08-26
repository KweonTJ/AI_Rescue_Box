import 'package:flutter/material.dart';

import 'host_controller.dart';
import 'review_workspace.dart';
import 'semantic_map.dart';

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
  'robot_trajectory',
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

enum _MapTool { select, addVictim, addTeam, addSafe, pan }

enum _MarkerKind { victim, team, safe }

@immutable
class _MarkerSelection {
  const _MarkerSelection({
    required this.kind,
    required this.id,
    required this.label,
    this.hostAdded = false,
  });
  final _MarkerKind kind;
  final String id;
  final String label;
  final bool hostAdded;
}

@immutable
class _MarkerSpec {
  const _MarkerSpec({
    required this.kind,
    required this.id,
    required this.label,
    required this.item,
    required this.color,
    this.hostAdded = false,
  });
  final _MarkerKind kind;
  final String id;
  final String label;
  final Map<String, dynamic> item;
  final Color color;
  final bool hostAdded;
  String get key => '${kind.name}:$id';
}

final class CommandReviewWorkspace extends StatefulWidget {
  const CommandReviewWorkspace({super.key, required this.controller});
  final HostController controller;

  @override
  State<CommandReviewWorkspace> createState() => _CommandReviewWorkspaceState();
}

class _CommandReviewWorkspaceState extends State<CommandReviewWorkspace> {
  final Set<String> _visible = _layerOrder.toSet();
  _MapTool _tool = _MapTool.select;
  _MarkerSelection? _selection;

  Future<void> _deleteSelection() async {
    final selected = _selection;
    if (selected == null || widget.controller.busy) return;
    switch (selected.kind) {
      case _MarkerKind.victim:
        await widget.controller.deleteVictim(
          selected.id,
          hostAdded: selected.hostAdded,
        );
      case _MarkerKind.team:
        await widget.controller.removeTeam(selected.id);
      case _MarkerKind.safe:
        await widget.controller.removeSafePoint(selected.id);
    }
    if (mounted) setState(() => _selection = null);
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final semantic = c.reviewedSemantic;
    final updated = semantic['created_at']?.toString() ?? '분석 결과 대기';
    final bridge = c.bridgeStatus;
    final uwbGood =
        bridge['connected'] == true || bridge['state'] == 'connected';
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
                  tooltip: '실행 취소',
                  onPressed: c.canUndo
                      ? () => c.applyReview({'action': 'undo'})
                      : null,
                  icon: const Icon(Icons.undo),
                ),
                IconButton(
                  tooltip: '다시 실행',
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
                final map = _Map(
                  controller: c,
                  visible: _visible,
                  tool: _tool,
                  selection: _selection,
                  onToolChanged: (value) => setState(() => _tool = value),
                  onSelectionChanged: (value) =>
                      setState(() => _selection = value),
                  onDelete: _deleteSelection,
                );
                final review = _RouteReview(controller: c, semantic: semantic);
                if (box.maxWidth < 1000) {
                  return ListView(
                    padding: const EdgeInsets.all(12),
                    children: [
                      SizedBox(height: 310, child: layers),
                      const SizedBox(height: 10),
                      SizedBox(height: 560, child: map),
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
                      : c.publishFinalMap,
                  style: FilledButton.styleFrom(backgroundColor: _green),
                  icon: const Icon(Icons.verified_outlined),
                  label: const Text('최종 지도 전송'),
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
  const _Map({
    required this.controller,
    required this.visible,
    required this.tool,
    required this.selection,
    required this.onToolChanged,
    required this.onSelectionChanged,
    required this.onDelete,
  });
  final HostController controller;
  final Set<String> visible;
  final _MapTool tool;
  final _MarkerSelection? selection;
  final ValueChanged<_MapTool> onToolChanged;
  final ValueChanged<_MarkerSelection?> onSelectionChanged;
  final Future<void> Function() onDelete;

  @override
  Widget build(BuildContext context) => Container(
    color: const Color(0xffe4e7e8),
    padding: const EdgeInsets.all(12),
    child: Column(
      children: [
        _MapEditToolbar(
          tool: tool,
          selection: selection,
          enabled: controller.currentResult != null && !controller.busy,
          onToolChanged: onToolChanged,
          onDelete: onDelete,
        ),
        const SizedBox(height: 8),
        Expanded(
          child: Container(
            decoration: BoxDecoration(
              color: const Color(0xfff4f5f4),
              border: Border.all(color: _line),
            ),
            child: Stack(
              children: [
                Positioned.fill(
                  child: SemanticMapCanvas(
                    controller: controller,
                    visibleLayers: visible,
                    interactive: tool == _MapTool.pan,
                    overlayBuilder: (context, size) => _MapEditorOverlay(
                      controller: controller,
                      size: size,
                      visible: visible,
                      tool: tool,
                      selection: selection,
                      onSelectionChanged: onSelectionChanged,
                      onToolChanged: onToolChanged,
                    ),
                  ),
                ),
                const Positioned(right: 10, bottom: 10, child: _Legend()),
              ],
            ),
          ),
        ),
      ],
    ),
  );
}

class _MapEditToolbar extends StatelessWidget {
  const _MapEditToolbar({
    required this.tool,
    required this.selection,
    required this.enabled,
    required this.onToolChanged,
    required this.onDelete,
  });
  final _MapTool tool;
  final _MarkerSelection? selection;
  final bool enabled;
  final ValueChanged<_MapTool> onToolChanged;
  final Future<void> Function() onDelete;

  @override
  Widget build(BuildContext context) {
    Widget button(_MapTool value, IconData icon, String label) => ChoiceChip(
      key: Key('map-tool-${value.name}'),
      selected: tool == value,
      avatar: Icon(icon, size: 15),
      label: Text(label),
      onSelected: enabled ? (_) => onToolChanged(value) : null,
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: _surface,
        border: Border.all(color: _line),
      ),
      child: Wrap(
        spacing: 7,
        runSpacing: 7,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          button(_MapTool.select, Icons.ads_click, '선택 / 드래그'),
          button(_MapTool.addVictim, Icons.person_add_alt_1, '+ 요구조자'),
          button(_MapTool.addTeam, Icons.group_add_outlined, '+ 구조인력'),
          button(_MapTool.addSafe, Icons.add_location_alt_outlined, '+ Safe'),
          button(_MapTool.pan, Icons.pan_tool_alt_outlined, '이동 / 확대'),
          if (selection != null) ...[
            const SizedBox(width: 4),
            Chip(
              avatar: const Icon(Icons.my_location, size: 15),
              label: Text('${selection!.label} · ${selection!.id}'),
            ),
            OutlinedButton.icon(
              key: const Key('delete-selected-marker'),
              onPressed: enabled ? onDelete : null,
              icon: const Icon(Icons.delete_outline, size: 16),
              label: Text(
                selection!.kind == _MarkerKind.victim && !selection!.hostAdded
                    ? '제외'
                    : '삭제',
              ),
            ),
          ],
          if (tool == _MapTool.addVictim ||
              tool == _MapTool.addTeam ||
              tool == _MapTool.addSafe)
            const Text(
              '구조도에서 추가할 위치를 클릭하세요.',
              style: TextStyle(color: _muted, fontSize: 9),
            )
          else if (tool == _MapTool.select)
            const Text(
              '마커를 클릭해 선택하고 드래그해서 위치를 수정합니다.',
              style: TextStyle(color: _muted, fontSize: 9),
            ),
        ],
      ),
    );
  }
}

class _MapEditorOverlay extends StatefulWidget {
  const _MapEditorOverlay({
    required this.controller,
    required this.size,
    required this.visible,
    required this.tool,
    required this.selection,
    required this.onSelectionChanged,
    required this.onToolChanged,
  });
  final HostController controller;
  final Size size;
  final Set<String> visible;
  final _MapTool tool;
  final _MarkerSelection? selection;
  final ValueChanged<_MarkerSelection?> onSelectionChanged;
  final ValueChanged<_MapTool> onToolChanged;

  @override
  State<_MapEditorOverlay> createState() => _MapEditorOverlayState();
}

class _MapEditorOverlayState extends State<_MapEditorOverlay> {
  String? _draggingKey;
  Offset? _dragScreen;

  MapPoint _imagePoint(Offset screen) {
    final width = widget.size.width <= 0 ? 1.0 : widget.size.width;
    final height = widget.size.height <= 0 ? 1.0 : widget.size.height;
    return MapPoint(
      (screen.dx / width * widget.controller.imageWidth)
          .clamp(0.0, widget.controller.imageWidth.toDouble())
          .toDouble(),
      (screen.dy / height * widget.controller.imageHeight)
          .clamp(0.0, widget.controller.imageHeight.toDouble())
          .toDouble(),
    );
  }

  Offset? _screenPoint(_MarkerSpec marker) {
    final point = widget.controller.semanticPoint(marker.item);
    if (point == null ||
        widget.controller.imageWidth <= 0 ||
        widget.controller.imageHeight <= 0) {
      return null;
    }
    return Offset(
      point.x / widget.controller.imageWidth * widget.size.width,
      point.y / widget.controller.imageHeight * widget.size.height,
    );
  }

  List<_MarkerSpec> _markers() {
    final semantic = widget.controller.reviewedSemantic;
    final result = <_MarkerSpec>[];
    if (widget.visible.contains('victim_candidates')) {
      for (final item in _objects(semantic, 'victim_candidates')) {
        if (item['host_status']?.toString() == 'excluded') continue;
        final id = _firstId(item, const ['victim_id', 'detection_id', 'id']);
        if (id == null) continue;
        result.add(
          _MarkerSpec(
            kind: _MarkerKind.victim,
            id: id,
            label: '요구조자',
            item: item,
            color: _orange,
            hostAdded: item['source'] == 'host_user',
          ),
        );
      }
    }
    if (widget.visible.contains('confirmed_victims')) {
      for (final item in _objects(semantic, 'confirmed_victims')) {
        if (item['host_status']?.toString() == 'excluded') continue;
        final id = _firstId(item, const ['victim_id', 'detection_id', 'id']);
        if (id == null) continue;
        result.add(
          _MarkerSpec(
            kind: _MarkerKind.victim,
            id: id,
            label: '요구조자',
            item: item,
            color: _red,
            hostAdded: item['source'] == 'host_user',
          ),
        );
      }
    }
    if (widget.visible.contains('team_recommendations')) {
      for (final item in _objects(semantic, 'team_recommendations')) {
        final id = _firstId(item, const ['team_id', 'id']);
        if (id == null) continue;
        result.add(
          _MarkerSpec(
            kind: _MarkerKind.team,
            id: id,
            label: '구조인력',
            item: item,
            color: _purple,
            hostAdded: item['source'] == 'host_user',
          ),
        );
      }
    }
    if (widget.visible.contains('safe_waiting_points')) {
      for (final item in _objects(semantic, 'safe_waiting_points')) {
        final id = _firstId(item, const [
          'waiting_id',
          'safe_waiting_id',
          'id',
        ]);
        if (id == null) continue;
        result.add(
          _MarkerSpec(
            kind: _MarkerKind.safe,
            id: id,
            label: 'Safe',
            item: item,
            color: _green,
            hostAdded: item['source'] == 'host_user',
          ),
        );
      }
    }
    return result;
  }

  Future<void> _moveMarker(_MarkerSpec marker, Offset screen) async {
    final image = _imagePoint(screen);
    switch (marker.kind) {
      case _MarkerKind.victim:
        await widget.controller.moveVictimToImage(marker.id, image);
      case _MarkerKind.team:
        await widget.controller.moveTeamToImage(marker.item, image);
      case _MarkerKind.safe:
        await widget.controller.moveSafePointToImage(marker.id, image);
    }
  }

  Future<void> _addAt(Offset screen) async {
    if (widget.controller.currentResult == null || widget.controller.busy)
      return;
    final image = _imagePoint(screen);
    String? id;
    _MarkerKind? kind;
    String? label;
    switch (widget.tool) {
      case _MapTool.addVictim:
        id = await widget.controller.addVictimAtImage(image);
        kind = _MarkerKind.victim;
        label = '요구조자';
      case _MapTool.addTeam:
        id = await widget.controller.addTeamAtImage(image);
        kind = _MarkerKind.team;
        label = '구조인력';
      case _MapTool.addSafe:
        id = await widget.controller.addSafePointAtImage(image);
        kind = _MarkerKind.safe;
        label = 'Safe';
      case _MapTool.select || _MapTool.pan:
        return;
    }
    if (!mounted || id == null) return;
    widget.onSelectionChanged(
      _MarkerSelection(kind: kind, id: id, label: label, hostAdded: true),
    );
    widget.onToolChanged(_MapTool.select);
  }

  @override
  Widget build(BuildContext context) {
    if (widget.tool == _MapTool.pan) {
      return const IgnorePointer(child: SizedBox.expand());
    }
    final markers = _markers();
    return GestureDetector(
      key: const Key('semantic-map-marker-editor'),
      behavior: HitTestBehavior.opaque,
      onTapDown: (details) async {
        if (widget.tool == _MapTool.select) {
          widget.onSelectionChanged(null);
          return;
        }
        await _addAt(details.localPosition);
      },
      child: Stack(
        fit: StackFit.expand,
        children: [
          for (final marker in markers)
            if (_screenPoint(marker) case final natural?)
              _markerWidget(
                marker,
                marker.key == _draggingKey && _dragScreen != null
                    ? _dragScreen!
                    : natural,
              ),
        ],
      ),
    );
  }

  Widget _markerWidget(_MarkerSpec marker, Offset screen) {
    final selected =
        widget.selection?.kind == marker.kind &&
        widget.selection?.id == marker.id;
    final clamped = Offset(
      screen.dx.clamp(0.0, widget.size.width).toDouble(),
      screen.dy.clamp(0.0, widget.size.height).toDouble(),
    );
    return Positioned(
      left: clamped.dx - 15,
      top: clamped.dy - 15,
      width: 30,
      height: 30,
      child: IgnorePointer(
        ignoring: widget.tool != _MapTool.select || widget.controller.busy,
        child: Tooltip(
          message: '${marker.label} · ${marker.id}',
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => widget.onSelectionChanged(
              _MarkerSelection(
                kind: marker.kind,
                id: marker.id,
                label: marker.label,
                hostAdded: marker.hostAdded,
              ),
            ),
            onPanStart: (_) {
              widget.onSelectionChanged(
                _MarkerSelection(
                  kind: marker.kind,
                  id: marker.id,
                  label: marker.label,
                  hostAdded: marker.hostAdded,
                ),
              );
              setState(() {
                _draggingKey = marker.key;
                _dragScreen = clamped;
              });
            },
            onPanUpdate: (details) {
              final current = _dragScreen ?? clamped;
              setState(() {
                _dragScreen = Offset(
                  (current.dx + details.delta.dx)
                      .clamp(0.0, widget.size.width)
                      .toDouble(),
                  (current.dy + details.delta.dy)
                      .clamp(0.0, widget.size.height)
                      .toDouble(),
                );
              });
            },
            onPanEnd: (_) async {
              final target = _dragScreen;
              setState(() {
                _draggingKey = null;
                _dragScreen = null;
              });
              if (target != null) await _moveMarker(marker, target);
            },
            child: Center(
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 100),
                width: selected ? 26 : 22,
                height: selected ? 26 : 22,
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: .78),
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: selected ? _ink : marker.color,
                    width: selected ? 3 : 2,
                  ),
                ),
                child: Icon(
                  switch (marker.kind) {
                    _MarkerKind.victim => Icons.person_pin_circle,
                    _MarkerKind.team => Icons.groups_2_outlined,
                    _MarkerKind.safe => Icons.place_outlined,
                  },
                  size: 15,
                  color: marker.color,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

String? _firstId(Map<String, dynamic> item, List<String> keys) {
  for (final key in keys) {
    final value = item[key];
    if (value != null && value.toString().isNotEmpty) return value.toString();
  }
  return null;
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
        const Text('경로 없음', style: TextStyle(color: _muted, fontSize: 9)),
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
    final id = (route['route_id'] ?? route['id'])?.toString();
    final canReview = id != null && id.isNotEmpty;
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
            id ?? 'route',
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
                  onPressed: canReview
                      ? () => controller.applyReview({
                          'action': 'set_route_approved',
                          'route_id': id,
                          'approved': true,
                        })
                      : null,
                  child: const Text('승인'),
                ),
              ),
              const SizedBox(width: 5),
              Expanded(
                child: OutlinedButton(
                  onPressed: canReview
                      ? () => controller.applyReview({
                          'action': 'set_route_approved',
                          'route_id': id,
                          'approved': false,
                        })
                      : null,
                  child: const Text('제외'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 5),
          OutlinedButton.icon(
            onPressed: () => _editRoute(
              context,
              controller,
              id ?? 'route',
              route,
            ),
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
  final points = _pointValues(
    route['points'],
  ).whereType<Map>().map((item) => Map<String, dynamic>.from(item)).toList();
  if (points.length < 2) return;
  final first = points.first;
  final last = points.last;
  final x0 =
      (((first['x'] as num?)?.toDouble() ?? 0) +
          ((last['x'] as num?)?.toDouble() ?? 0)) /
      2;
  final y0 =
      (((first['y'] as num?)?.toDouble() ?? 0) +
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

Future<void> _advanced(BuildContext context, HostController controller) async {
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

List<Map<String, dynamic>> _objects(Map<String, dynamic> value, String key) =>
    value[key] is List
    ? (value[key] as List)
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList()
    : const [];

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
  'robot_pose' || 'robot_trajectory' || 'entry_routes' => _blue,
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
  'robot_trajectory' => 'AI Rescue Box 이동 궤적',
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
