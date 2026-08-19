part of 'jetson_app.dart';

class _SemanticMapPainter {
  const _SemanticMapPainter({
    required this.projection,
    required this.manifest,
    required this.result,
    required this.approvedPlan,
    required this.previewMetadata,
    required this.sourceRect,
    required this.destinationRect,
  });

  final _MissionProjection projection;
  final JsonMap? manifest;
  final JsonMap? result;
  final JsonMap? approvedPlan;
  final JsonMap? previewMetadata;
  final Rect sourceRect;
  final Rect destinationRect;

  Offset _screenFromImage(Offset image) => Offset(
    destinationRect.left + image.dx / sourceRect.width * destinationRect.width,
    destinationRect.top + image.dy / sourceRect.height * destinationRect.height,
  );

  Offset? _screenFromMission(Object? value) {
    final point = _asMap(value);
    if (point == null) return null;
    final x = _asDouble(point['x'] ?? point['map_x']);
    final y = _asDouble(point['y'] ?? point['map_y']);
    if (x == null || y == null) return null;
    return _screenFromImage(projection.missionToImage(Offset(x, y)));
  }

  void paint(Canvas canvas, Size size) {
    final robot = _screenFromMission(result?['robot_pose'] ?? manifest?['robot_start']);
    if (robot != null) {
      canvas.drawCircle(robot, 7, Paint()..color = const Color(0xff56cfe1));
    }

    final trajectory = result?['robot_trajectory'];
    if (trajectory is List) {
      final points = trajectory.map(_screenFromMission).whereType<Offset>().toList();
      _drawPolyline(canvas, points, const Color(0xff56cfe1), 2);
    }

    for (final victim in _asObjectList(result?['victim_candidates'])) {
      final point = _screenFromMission(victim['map_position'] ?? victim['position']);
      if (point == null) continue;
      canvas.drawCircle(point, 6, Paint()..color = const Color(0xffffd166));
    }

    for (final risk in _asObjectList(result?['risk_zones'])) {
      final polygon = risk['polygon'];
      if (polygon is! List) continue;
      final points = polygon.map(_screenFromMission).whereType<Offset>().toList();
      if (points.isEmpty) continue;
      final path = Path()..moveTo(points.first.dx, points.first.dy);
      for (final point in points.skip(1)) {
        path.lineTo(point.dx, point.dy);
      }
      if (points.length >= 3) path.close();
      canvas.drawPath(
        path,
        Paint()
          ..color = const Color(0xffef476f).withValues(alpha: 0.25)
          ..style = PaintingStyle.fill,
      );
      canvas.drawPath(
        path,
        Paint()
          ..color = const Color(0xffef476f)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2,
      );
    }

    for (final route in _asObjectList(result?['entry_routes'])) {
      final raw = route['points'];
      if (raw is! List) continue;
      _drawPolyline(
        canvas,
        raw.map(_screenFromMission).whereType<Offset>().toList(),
        const Color(0xff06d6a0),
        3,
      );
    }

    final plan = approvedPlan;
    if (plan != null) {
      final planRoutes = plan['approved_routes'];
      if (planRoutes is List) {
        for (final item in planRoutes) {
          final route = _asMap(item);
          final raw = route?['points'];
          if (raw is! List) continue;
          _drawPolyline(
            canvas,
            raw.map(_screenFromMission).whereType<Offset>().toList(),
            const Color(0xff06d6a0),
            4,
          );
        }
      }
    }
  }

  void _drawPolyline(Canvas canvas, List<Offset> points, Color color, double width) {
    if (points.length < 2) return;
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (final point in points.skip(1)) {
      path.lineTo(point.dx, point.dy);
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = width
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
  }
}
