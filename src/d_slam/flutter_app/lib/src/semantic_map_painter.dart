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
    final initial = _asMap(value);
    if (initial == null) return null;
    var point = initial;
    for (final key in const [
      'map_position',
      'position',
      'map_point',
      'center',
    ]) {
      final nested = _asMap(point[key]);
      if (nested != null) {
        point = nested;
        break;
      }
    }
    final x = _asDouble(point['x'] ?? point['map_x']);
    final y = _asDouble(point['y'] ?? point['map_y']);
    if (x == null || y == null) return null;
    return _screenFromImage(projection.missionToImage(Offset(x, y)));
  }

  void paint(Canvas canvas, Size size) {
    final robot = _screenFromMission(
      result?['robot_pose'] ?? manifest?['robot_start'],
    );
    if (robot != null) {
      canvas.drawCircle(robot, 7, Paint()..color = const Color(0xff56cfe1));
    }

    final trajectory = result?['robot_trajectory'];
    if (trajectory is List) {
      final points = trajectory
          .map(_screenFromMission)
          .whereType<Offset>()
          .toList();
      _drawPolyline(canvas, points, const Color(0xff56cfe1), 2);
    }

    final victims = <JsonMap>[
      ..._asObjectList(result?['victim_candidates']),
      ..._asObjectList(result?['confirmed_victims']),
      ..._asObjectList(approvedPlan?['approved_victims']),
    ];
    for (final victim in victims) {
      final point = _screenFromMission(
        victim['map_position'] ?? victim['position'],
      );
      if (point == null) continue;
      canvas.drawCircle(point, 6, Paint()..color = const Color(0xffffd166));
    }

    final obstacles = result?['obstacles'];
    if (obstacles is List) {
      for (final obstacle in obstacles) {
        final object = _asMap(obstacle);
        _drawPolygon(
          canvas,
          object?['polygon'] ?? object?['points'] ?? obstacle,
          const Color(0xff555555),
        );
      }
    }

    final risks = <JsonMap>[
      ..._asObjectList(result?['risk_zones']),
      ..._asObjectList(approvedPlan?['approved_risk_zones']),
    ];
    for (final risk in risks) {
      _drawPolygon(canvas, risk['polygon'] ?? risk, const Color(0xffef476f));
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

      for (final assignment in _asObjectList(plan['final_team_assignments'])) {
        final point = _screenFromMission(assignment);
        if (point == null) continue;
        canvas.drawCircle(point, 7, Paint()..color = const Color(0xff8a2be2));
        _drawLabel(
          canvas,
          point + const Offset(9, -9),
          (assignment['team_id'] ?? assignment['id'] ?? 'TEAM').toString(),
        );
      }

      for (final waiting in _asObjectList(plan['safe_waiting_points'])) {
        final point = _screenFromMission(waiting);
        if (point == null) continue;
        canvas.drawCircle(point, 8, Paint()..color = const Color(0xff00a878));
        canvas.drawCircle(
          point,
          3,
          Paint()
            ..color = Colors.white
            ..style = PaintingStyle.fill,
        );
      }
    }
  }

  void _drawPolygon(Canvas canvas, Object? raw, Color color) {
    final values = raw is List ? raw : _asMap(raw)?['polygon'];
    if (values is! List) return;
    final points = values.map(_screenFromMission).whereType<Offset>().toList();
    if (points.isEmpty) return;
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (final point in points.skip(1)) {
      path.lineTo(point.dx, point.dy);
    }
    if (points.length >= 3) path.close();
    canvas.drawPath(
      path,
      Paint()
        ..color = color.withValues(alpha: 0.25)
        ..style = PaintingStyle.fill,
    );
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  void _drawLabel(Canvas canvas, Offset point, String value) {
    final painter = TextPainter(
      text: TextSpan(
        text: value,
        style: const TextStyle(
          color: Colors.white,
          fontSize: 10,
          fontWeight: FontWeight.w800,
          backgroundColor: Color(0xcc4b247a),
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    painter.paint(canvas, point);
  }

  void _drawPolyline(
    Canvas canvas,
    List<Offset> points,
    Color color,
    double width,
  ) {
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
