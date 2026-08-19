part of 'jetson_app.dart';

class _MissionProjection {
  const _MissionProjection({
    required this.imageWidth,
    required this.imageHeight,
    required this.scale,
    required this.rotation,
    required this.origin,
  });

  final double imageWidth;
  final double imageHeight;
  final double scale;
  final double rotation;
  final Offset origin;

  factory _MissionProjection.fromManifest(JsonMap? manifest) {
    final baseMap = _asMap(manifest?['base_map']);
    final transform = _asMap(manifest?['coordinate_transform']);
    final topScale = (manifest?['meters_per_pixel'] as num?)?.toDouble();
    final transformScale = (transform?['meters_per_pixel'] as num?)?.toDouble();
    final offset = _asMap(transform?['origin_offset_m']);
    return _MissionProjection(
      imageWidth: (baseMap?['width'] as num?)?.toDouble() ??
          (manifest?['base_map_width'] as num?)?.toDouble() ??
          1,
      imageHeight: (baseMap?['height'] as num?)?.toDouble() ??
          (manifest?['base_map_height'] as num?)?.toDouble() ??
          1,
      scale: topScale ?? transformScale ?? 1,
      rotation: (transform?['rotation_radians'] as num?)?.toDouble() ?? 0,
      origin: Offset(
        (offset?['x'] as num?)?.toDouble() ?? 0,
        (offset?['y'] as num?)?.toDouble() ?? 0,
      ),
    );
  }

  Offset imageToMission(Offset imagePoint) {
    final x = imagePoint.dx * scale;
    final y = (imageHeight - imagePoint.dy) * scale;
    final cosTheta = math.cos(rotation);
    final sinTheta = math.sin(rotation);
    return Offset(
      origin.dx + x * cosTheta - y * sinTheta,
      origin.dy + x * sinTheta + y * cosTheta,
    );
  }

  Offset missionToImage(Offset missionPoint) {
    final translated = missionPoint - origin;
    final cosTheta = math.cos(-rotation);
    final sinTheta = math.sin(-rotation);
    final x = translated.dx * cosTheta - translated.dy * sinTheta;
    final y = translated.dx * sinTheta + translated.dy * cosTheta;
    return Offset(x / scale, imageHeight - y / scale);
  }
}
