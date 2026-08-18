import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'host_controller.dart';

final class MissionMapEditor extends StatefulWidget {
  const MissionMapEditor({super.key, required this.controller});

  final HostController controller;

  @override
  State<MissionMapEditor> createState() => _MissionMapEditorState();
}

final class _MissionMapEditorState extends State<MissionMapEditor> {
  MapPoint? _dragStart;

  HostController get controller => widget.controller;

  MapPoint _mapPoint(Offset point, Size size) => MapPoint(
    (point.dx / size.width * controller.imageWidth).clamp(
      0,
      controller.imageWidth.toDouble(),
    ),
    (point.dy / size.height * controller.imageHeight).clamp(
      0,
      controller.imageHeight.toDouble(),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final bytes = controller.mapBytes;
    if (bytes == null) {
      return const SizedBox(
        height: 360,
        child: Center(child: Text('JPEG 또는 PNG 구조도를 먼저 업로드하세요.')),
      );
    }
    final aspect = math.max(
      0.1,
      controller.imageWidth / controller.imageHeight,
    );
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 560, maxWidth: 1000),
        child: AspectRatio(
          aspectRatio: aspect,
          child: InteractiveViewer(
            minScale: 0.5,
            maxScale: 8,
            child: LayoutBuilder(
              builder: (context, constraints) {
                final size = constraints.biggest;
                return GestureDetector(
                  key: const Key('mission-map-editor'),
                  onTapDown: (details) {
                    if (controller.editMode != MapEditMode.robotStart) {
                      controller.applyMapTap(
                        _mapPoint(details.localPosition, size),
                      );
                    }
                  },
                  onPanStart: controller.editMode == MapEditMode.robotStart
                      ? (details) {
                          _dragStart = _mapPoint(details.localPosition, size);
                        }
                      : null,
                  onPanUpdate: controller.editMode == MapEditMode.robotStart
                      ? (details) {
                          final start = _dragStart;
                          if (start != null) {
                            controller.setRobotPose(
                              start,
                              _mapPoint(details.localPosition, size),
                            );
                          }
                        }
                      : null,
                  onPanEnd: controller.editMode == MapEditMode.robotStart
                      ? (_) => _dragStart = null
                      : null,
                  child: CustomPaint(
                    foregroundPainter: _MarkerPainter(controller),
                    child: Image.memory(
                      bytes,
                      fit: BoxFit.fill,
                      gaplessPlayback: true,
                      errorBuilder: (_, _, _) => const ColoredBox(
                        color: Color(0xff20252b),
                        child: Center(child: Text('구조도 미리보기 디코딩 실패')),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}

final class _MarkerPainter extends CustomPainter {
  _MarkerPainter(this.controller);
  final HostController controller;

  Offset _point(MapPoint value, Size size) => Offset(
    value.x / controller.imageWidth * size.width,
    value.y / controller.imageHeight * size.height,
  );

  @override
  void paint(Canvas canvas, Size size) {
    final start = controller.robotStart;
    if (start != null) {
      final origin = _point(start, size);
      final paint = Paint()
        ..color = const Color(0xff00c853)
        ..strokeWidth = 3
        ..style = PaintingStyle.stroke;
      canvas.drawCircle(origin, 9, paint);
      final direction = Offset(
        math.cos(controller.robotYawRadians) * 34,
        math.sin(controller.robotYawRadians) * 34,
      );
      canvas.drawLine(origin, origin + direction, paint);
    }
    final scalePaint = Paint()
      ..color = const Color(0xffffc400)
      ..strokeWidth = 3;
    if (controller.scaleFirst case final first?) {
      canvas.drawCircle(_point(first, size), 6, scalePaint);
    }
    if (controller.scaleSecond case final second?) {
      canvas.drawCircle(_point(second, size), 6, scalePaint);
      if (controller.scaleFirst case final first?) {
        canvas.drawLine(_point(first, size), _point(second, size), scalePaint);
      }
    }
    final entrancePaint = Paint()..color = const Color(0xff00b0ff);
    for (final entrance in controller.entrances) {
      final center = _point(entrance, size);
      canvas.drawRect(
        Rect.fromCenter(center: center, width: 12, height: 12),
        entrancePaint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _MarkerPainter oldDelegate) => true;
}
