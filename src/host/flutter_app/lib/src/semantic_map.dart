import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'host_controller.dart';

@visibleForTesting
Color candidateDisplayColor(Object? status) => switch (status?.toString()) {
  'confirmed' => const Color(0xffe60026),
  'excluded' => const Color(0xff6b7280),
  _ => const Color(0xffffb000),
};

@visibleForTesting
Path dashedOutline(Path source, {double dash = 7, double gap = 5}) {
  final output = Path();
  for (final metric in source.computeMetrics()) {
    var distance = 0.0;
    while (distance < metric.length) {
      output.addPath(
        metric.extractPath(distance, math.min(distance + dash, metric.length)),
        Offset.zero,
      );
      distance += dash + gap;
    }
  }
  return output;
}

final class SemanticMapView extends StatelessWidget {
  const SemanticMapView({super.key, required this.controller});

  final HostController controller;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            for (final layer in HostController.semanticLayers)
              FilterChip(
                key: Key('layer-$layer'),
                selected: controller.visibleLayers.contains(layer),
                onSelected: (value) => controller.setLayerVisible(layer, value),
                label: Text(_layerLabel(layer)),
              ),
          ],
        ),
        const SizedBox(height: 8),
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 650, maxWidth: 1100),
            child: SemanticMapCanvas(
              controller: controller,
              visibleLayers: controller.visibleLayers,
            ),
          ),
        ),
        const SizedBox(height: 4),
        const Text('휠/핀치로 확대하고 드래그해 이동할 수 있습니다.'),
      ],
    );
  }
}

/// The shared base-map and semantic-overlay canvas.
///
/// Both layers fill this widget's single mission-map [AspectRatio], so any
/// letterboxing happens outside the canvas and can never offset the overlay.
final class SemanticMapCanvas extends StatelessWidget {
  const SemanticMapCanvas({
    super.key,
    required this.controller,
    required this.visibleLayers,
    this.interactive = true,
    this.overlayBuilder,
  });

  final HostController controller;
  final Set<String> visibleLayers;
  final bool interactive;
  final Widget Function(BuildContext context, Size size)? overlayBuilder;

  @override
  Widget build(BuildContext context) {
    final bytes = controller.mapBytes;
    if (bytes == null || bytes.isEmpty) {
      return const SizedBox(
        width: double.infinity,
        height: 360,
        child: ColoredBox(
          key: Key('semantic-map-fallback'),
          color: Color(0xfff4f5f4),
          child: Center(child: Text('ACTIVE Mission의 base map을 불러올 수 없습니다.')),
        ),
      );
    }
    final aspect = math.max(
      0.1,
      controller.imageWidth / controller.imageHeight,
    );
    Widget canvas = LayoutBuilder(
      builder: (context, constraints) {
        final size = constraints.biggest;
        return ClipRect(
          child: Stack(
            key: const Key('semantic-map-canvas'),
            fit: StackFit.expand,
            children: [
              Image.memory(
                bytes,
                key: const Key('semantic-map-base-image'),
                fit: BoxFit.fill,
                gaplessPlayback: true,
                errorBuilder: (_, _, _) => const ColoredBox(
                  key: Key('semantic-map-decode-fallback'),
                  color: Color(0xff20252b),
                  child: Center(
                    child: Text(
                      'base map 디코딩 실패',
                      style: TextStyle(color: Colors.white),
                    ),
                  ),
                ),
              ),
              if (visibleLayers.contains('slam_preview'))
                _PreviewOverlay(controller: controller, size: size),
              CustomPaint(
                key: const Key('semantic-map-overlay'),
                painter: _SemanticPainter(controller, visibleLayers),
              ),
              if (overlayBuilder != null)
                Positioned.fill(
                  child: overlayBuilder!(context, size),
                ),
            ],
          ),
        );
      },
    );
    if (interactive) {
      canvas = InteractiveViewer(
        key: const Key('semantic-map-zoom-pan'),
        minScale: 0.35,
        maxScale: 12,
        boundaryMargin: const EdgeInsets.all(120),
        child: canvas,
      );
    }
    return Center(
      child: AspectRatio(
        key: const Key('semantic-map-aspect-ratio'),
        aspectRatio: aspect,
        child: canvas,
      ),
    );
  }
}

final class _PreviewOverlay extends StatelessWidget {
  const _PreviewOverlay({required this.controller, required this.size});
  final HostController controller;
  final Size size;

  @override
  Widget build(BuildContext context) {
    final bytes = controller.previewBytes;
    final corners = controller.previewCorners;
    final metadata = controller.previewMetadata;
    if (bytes == null || corners == null || metadata == null) {
      return const SizedBox.shrink();
    }
    final previewWidth = (metadata['preview_width'] as num?)?.toDouble() ?? 1;
    final previewHeight = (metadata['preview_height'] as num?)?.toDouble() ?? 1;
    final scaleX = size.width / controller.imageWidth;
    final scaleY = size.height / controller.imageHeight;
    final topLeft = Offset(corners[0].x * scaleX, corners[0].y * scaleY);
    final topRight = Offset(corners[1].x * scaleX, corners[1].y * scaleY);
    final bottomLeft = Offset(corners[2].x * scaleX, corners[2].y * scaleY);
    final matrix = Matrix4.identity()
      ..setEntry(0, 0, (topRight.dx - topLeft.dx) / previewWidth)
      ..setEntry(1, 0, (topRight.dy - topLeft.dy) / previewWidth)
      ..setEntry(0, 1, (bottomLeft.dx - topLeft.dx) / previewHeight)
      ..setEntry(1, 1, (bottomLeft.dy - topLeft.dy) / previewHeight)
      ..setEntry(0, 3, topLeft.dx)
      ..setEntry(1, 3, topLeft.dy);
    return Align(
      alignment: Alignment.topLeft,
      child: Transform(
        transform: matrix,
        alignment: Alignment.topLeft,
        child: Opacity(
          opacity: 0.45,
          child: SizedBox(
            key: const Key('slam-preview-image'),
            width: previewWidth,
            height: previewHeight,
            child: Image.memory(bytes, fit: BoxFit.fill),
          ),
        ),
      ),
    );
  }
}

final class _SemanticPainter extends CustomPainter {
  _SemanticPainter(this.controller, this.visibleLayers);
  final HostController controller;
  final Set<String> visibleLayers;

  JsonMap get semantic => controller.reviewedSemantic;

  Offset? _point(Object? value, Size size) {
    final point = controller.semanticPoint(value);
    if (point == null) return null;
    return Offset(
      point.x / controller.imageWidth * size.width,
      point.y / controller.imageHeight * size.height,
    );
  }

  List<Object?> _items(String key) {
    final value = semantic[key];
    return value is List ? value : const [];
  }

  List<Object?> _points(Object? item) {
    if (item is List) return item;
    if (item is! Map) return const [];
    for (final key in const ['points', 'path', 'polygon', 'coordinates']) {
      final value = item[key];
      if (value is List) return value;
    }
    return const [];
  }

  void _drawPoint(Canvas canvas, Size size, Object? item, Color color) {
    final point = _point(item, size);
    if (point == null) return;
    canvas.drawCircle(point, 7, Paint()..color = color);
    canvas.drawCircle(
      point,
      9,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  void _drawPolyline(
    Canvas canvas,
    Size size,
    List<Object?> values,
    Color color, {
    double width = 3,
  }) {
    final path = Path();
    var started = false;
    for (final item in values) {
      final point = _point(item, size);
      if (point == null) continue;
      started
          ? path.lineTo(point.dx, point.dy)
          : path.moveTo(point.dx, point.dy);
      started = true;
    }
    if (started) {
      canvas.drawPath(
        path,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = width,
      );
    }
  }

  void _drawPolygon(
    Canvas canvas,
    Size size,
    Object? item,
    Color color, {
    bool dashed = false,
  }) {
    final values = _points(item);
    final points = values
        .map((value) => _point(value, size))
        .whereType<Offset>()
        .toList();
    if (points.isEmpty) return;
    if (points.length == 1) {
      _drawPoint(canvas, size, values.first, color);
      return;
    }
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (final point in points.skip(1)) {
      path.lineTo(point.dx, point.dy);
    }
    if (points.length > 2) path.close();
    canvas.drawPath(
      dashed ? dashedOutline(path) : path,
      Paint()
        ..color = color.withValues(alpha: 0.20)
        ..style = PaintingStyle.fill,
    );
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = dashed ? 1.5 : 2.5,
    );
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (visibleLayers.contains('robot_trajectory')) {
      _drawPolyline(
        canvas,
        size,
        _items('robot_trajectory'),
        const Color(0xff00bfff),
      );
    }
    if (visibleLayers.contains('robot_pose')) {
      _drawPoint(canvas, size, semantic['robot_pose'], const Color(0xff1677a8));
    }
    if (visibleLayers.contains('victim_candidates')) {
      for (final item in _items('victim_candidates')) {
        final status = item is Map ? item['host_status'] : null;
        if (status?.toString() == 'excluded') continue;
        _drawPoint(canvas, size, item, candidateDisplayColor(status));
      }
    }
    if (visibleLayers.contains('confirmed_victims')) {
      for (final item in _items('confirmed_victims')) {
        final status = item is Map ? item['host_status'] : null;
        if (status?.toString() == 'excluded') continue;
        _drawPoint(canvas, size, item, const Color(0xffe60026));
      }
    }
    for (final definition in const [
      ('team_recommendations', Color(0xff8a2be2)),
      ('safe_waiting_points', Color(0xff00a878)),
    ]) {
      if (!visibleLayers.contains(definition.$1)) continue;
      for (final item in _items(definition.$1)) {
        _drawPoint(canvas, size, item, definition.$2);
      }
    }
    if (visibleLayers.contains('entry_routes')) {
      for (final item in _items('entry_routes')) {
        _drawPolyline(
          canvas,
          size,
          _points(item),
          const Color(0xff2878ff),
          width: 4,
        );
      }
    }
    if (visibleLayers.contains('return_routes')) {
      for (final item in _items('return_routes')) {
        _drawPolyline(
          canvas,
          size,
          _points(item),
          const Color(0xff7656a8),
          width: 4,
        );
      }
    }
    for (final definition in const [
      ('obstacles', Color(0xff555555)),
      ('explored_areas', Color(0xff2a9d8f)),
      ('unknown_areas', Color(0xff888888)),
    ]) {
      if (!visibleLayers.contains(definition.$1)) continue;
      for (final item in _items(definition.$1)) {
        _drawPolygon(canvas, size, item, definition.$2);
      }
    }
    if (visibleLayers.contains('risk_zones')) {
      for (final item in _items('risk_zones')) {
        final state = item is Map ? item['state']?.toString() : null;
        final color = switch (state) {
          'observed' => const Color(0xffef4444),
          'interpolated' => const Color(0xff8b5cf6),
          _ => const Color(0xff9ca3af),
        };
        _drawPolygon(canvas, size, item, color, dashed: state != 'observed');
      }
    }
  }

  @override
  bool shouldRepaint(covariant _SemanticPainter oldDelegate) => true;
}

String _layerLabel(String value) => switch (value) {
  'slam_preview' => 'SLAM preview',
  'robot_pose' => 'AI Rescue Box 현재 위치',
  'robot_trajectory' => '궤적',
  'victim_candidates' => '요구조자 후보',
  'confirmed_victims' => '확정 요구조자',
  'obstacles' => '장애물',
  'risk_zones' => '위험',
  'explored_areas' => '탐색 영역',
  'unknown_areas' => '미탐색 영역',
  'entry_routes' => '진입 경로',
  'return_routes' => '복귀 경로',
  'team_recommendations' => '팀 배치',
  'safe_waiting_points' => '안전 대기점',
  _ => value,
};
