part of 'jetson_app.dart';

class _MissionProjection {
  const _MissionProjection({
    required this.imageWidth,
    required this.imageHeight,
    required this.scale,
    required this.rotation,
    required this.imageOrigin,
    required this.mapOrigin,
    required this.invertY,
  });

  final double imageWidth;
  final double imageHeight;
  final double scale;
  final double rotation;
  final Offset imageOrigin;
  final Offset mapOrigin;
  final bool invertY;

  factory _MissionProjection.fromManifest(JsonMap? manifest) {
    final baseMap = _asMap(manifest?['base_map']);
    final transform = _asMap(manifest?['coordinate_transform']);
    final imageHeight =
        (baseMap?['height'] as num?)?.toDouble() ??
        (manifest?['base_map_height'] as num?)?.toDouble() ??
        1;
    final topScale = (manifest?['meters_per_pixel'] as num?)?.toDouble();
    final transformScale = (transform?['meters_per_pixel'] as num?)?.toDouble();
    final imageOrigin = _asMap(transform?['image_origin']);
    final offset = _asMap(transform?['origin_offset_m']);
    return _MissionProjection(
      imageWidth:
          (baseMap?['width'] as num?)?.toDouble() ??
          (manifest?['base_map_width'] as num?)?.toDouble() ??
          1,
      imageHeight: imageHeight,
      scale: topScale ?? transformScale ?? 1,
      rotation: (transform?['rotation_radians'] as num?)?.toDouble() ?? 0,
      imageOrigin: Offset(
        (imageOrigin?['x'] as num?)?.toDouble() ?? 0,
        (imageOrigin?['y'] as num?)?.toDouble() ?? imageHeight,
      ),
      mapOrigin: Offset(
        (offset?['x'] as num?)?.toDouble() ?? 0,
        (offset?['y'] as num?)?.toDouble() ?? 0,
      ),
      invertY: transform?['invert_y'] != false,
    );
  }

  Offset imageToMission(Offset imagePoint) {
    final x = (imagePoint.dx - imageOrigin.dx) * scale;
    final imageY = (imagePoint.dy - imageOrigin.dy) * scale;
    final y = invertY ? -imageY : imageY;
    final cosTheta = math.cos(rotation);
    final sinTheta = math.sin(rotation);
    return Offset(
      mapOrigin.dx + x * cosTheta - y * sinTheta,
      mapOrigin.dy + x * sinTheta + y * cosTheta,
    );
  }

  Offset missionToImage(Offset missionPoint) {
    final translated = missionPoint - mapOrigin;
    final cosTheta = math.cos(-rotation);
    final sinTheta = math.sin(-rotation);
    final x = translated.dx * cosTheta - translated.dy * sinTheta;
    final y = translated.dx * sinTheta + translated.dy * cosTheta;
    return Offset(
      imageOrigin.dx + x / scale,
      imageOrigin.dy + (invertY ? -y : y) / scale,
    );
  }
}
