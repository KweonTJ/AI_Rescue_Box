part of 'jetson_app.dart';

const _hostApiBaseUrl = String.fromEnvironment(
  'HOST_API_BASE_URL',
  defaultValue: 'http://192.168.0.10:8000',
);

class _Dashboard extends StatefulWidget {
  const _Dashboard({
    required this.controller,
    required this.onChooseAnotherMission,
  });

  final JetsonController controller;
  final VoidCallback onChooseAnotherMission;

  @override
  State<_Dashboard> createState() => _DashboardState();
}

class _DashboardState extends State<_Dashboard> {
  Timer? _timer;
  int _frame = 0;
  JsonMap? _finalMapState;
  String? _finalMapError;
  bool _finalMapLoading = false;
  DateTime _nextFinalMapRefresh = DateTime.fromMillisecondsSinceEpoch(0);

  Uri get _hostApiBase => Uri.parse(_hostApiBaseUrl);

  @override
  void initState() {
    super.initState();

    final refreshInterval =
        widget.controller.autoRefreshInterval > const Duration(minutes: 1)
        ? widget.controller.autoRefreshInterval
        : const Duration(milliseconds: 350);
    _timer = Timer.periodic(refreshInterval, (_) {
      if (!mounted) return;

      final now = DateTime.now();
      setState(() {
        _frame++;
      });
      if (!now.isBefore(_nextFinalMapRefresh)) {
        _nextFinalMapRefresh = now.add(const Duration(seconds: 2));
        unawaited(_refreshFinalMap());
      }
    });
    unawaited(_refreshFinalMap());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Uri? get _visionBase {
    final api = widget.controller.apiBaseUri;

    if (api == null) return null;

    return Uri(
      scheme: api.scheme.isEmpty ? 'http' : api.scheme,
      host: api.host,
      port: 8091,
    );
  }

  String? _imageUrl(String path) {
    final base = _visionBase;

    if (base == null) return null;

    return base
        .replace(path: path, queryParameters: {'t': '$_frame'})
        .toString();
  }

  Future<void> _refreshFinalMap() async {
    if (_finalMapLoading) return;
    _finalMapLoading = true;
    try {
      final uri = _hostApiBase.replace(
        path: '/api/v1/final-map/current',
        queryParameters: {'t': '${DateTime.now().millisecondsSinceEpoch}'},
      );
      final response = await http.get(uri).timeout(const Duration(seconds: 4));
      if (response.statusCode != 200) {
        throw StateError('Host final-map HTTP ${response.statusCode}');
      }
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded is! Map) {
        throw const FormatException(
          'Host final-map response must be an object',
        );
      }
      if (!mounted) return;
      setState(() {
        _finalMapState = Map<String, dynamic>.from(decoded);
        _finalMapError = null;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _finalMapError = error.toString();
      });
    } finally {
      _finalMapLoading = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final personUrl = _imageUrl('/person.jpg');
    final depthUrl = _imageUrl('/depth.jpg');

    final visionHost = _visionBase?.host ?? '-';
    final missionLabel = widget.controller.selectedMissionId == null
        ? 'Mission 미선택'
        : '${widget.controller.selectedMissionId} · v${widget.controller.selectedMissionVersion}';

    return ColoredBox(
      color: _tabletBackground,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '현장 비전',
                        style: TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.w900,
                          color: _tabletInk,
                        ),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        'RGB-D Camera · MediaPipe Person Detection',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: _tabletMuted,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '현재 Mission · $missionLabel',
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: _tabletMuted,
                        ),
                      ),
                    ],
                  ),
                ),
                TextButton.icon(
                  key: const Key('choose-another-mission'),
                  onPressed: widget.controller.busy
                      ? null
                      : widget.onChooseAnotherMission,
                  icon: const Icon(Icons.swap_horiz),
                  label: const Text('다른 구조도 선택'),
                ),
                const SizedBox(width: 10),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 8,
                  ),
                  decoration: BoxDecoration(
                    color: _tabletGreenSoft,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.circle, size: 9, color: _tabletGreen),
                      SizedBox(width: 7),
                      Text(
                        'LIVE',
                        style: TextStyle(
                          fontWeight: FontWeight.w900,
                          color: _tabletGreen,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            LayoutBuilder(
              builder: (context, constraints) {
                if (constraints.maxWidth < 800) {
                  return Column(
                    children: [
                      SizedBox(
                        height: 340,
                        child: _VisionFeed(
                          title: 'PERSON DETECTION',
                          subtitle: 'MediaPipe EfficientDet Lite0',
                          imageUrl: personUrl,
                        ),
                      ),
                      const SizedBox(height: 14),
                      SizedBox(
                        height: 340,
                        child: _VisionFeed(
                          title: 'DEPTH CAMERA',
                          subtitle: 'Astra RGB-D Depth',
                          imageUrl: depthUrl,
                        ),
                      ),
                    ],
                  );
                }

                return SizedBox(
                  height: 400,
                  child: Row(
                    children: [
                      Expanded(
                        child: _VisionFeed(
                          title: 'PERSON DETECTION',
                          subtitle: 'MediaPipe EfficientDet Lite0',
                          imageUrl: personUrl,
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: _VisionFeed(
                          title: 'DEPTH CAMERA',
                          subtitle: 'Astra RGB-D Depth',
                          imageUrl: depthUrl,
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
            const SizedBox(height: 18),
            _FinalMapPanel(
              state: _finalMapState,
              error: _finalMapError,
              hostApiBase: _hostApiBase,
              cacheKey: _frame,
              refreshing: _finalMapLoading,
              onRefresh: _refreshFinalMap,
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 14,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.wifi, size: 15, color: _tabletGreen),
                    const SizedBox(width: 6),
                    Text(
                      'Vision Server · $visionHost:8091',
                      style: const TextStyle(
                        fontSize: 11,
                        color: _tabletMuted,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.dns_outlined,
                      size: 15,
                      color: _tabletBlue,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      'Final Map Server · ${_hostApiBase.host}:${_hostApiBase.hasPort ? _hostApiBase.port : 80}',
                      style: const TextStyle(
                        fontSize: 11,
                        color: _tabletMuted,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                const Text(
                  'AI Rescue Box · Field Operation',
                  style: TextStyle(
                    fontSize: 11,
                    color: _tabletMuted,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _VisionFeed extends StatelessWidget {
  const _VisionFeed({
    required this.title,
    required this.subtitle,
    required this.imageUrl,
  });

  final String title;
  final String subtitle;
  final String? imageUrl;

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      color: _tabletSurface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 12),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w900,
                          color: _tabletInk,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        subtitle,
                        style: const TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          color: _tabletMuted,
                        ),
                      ),
                    ],
                  ),
                ),
                const Icon(Icons.circle, size: 8, color: _tabletGreen),
                const SizedBox(width: 5),
                const Text(
                  'LIVE',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w900,
                    color: _tabletGreen,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: ColoredBox(
              color: const Color(0xff151719),
              child: imageUrl == null
                  ? const _VisionWaiting()
                  : Image.network(
                      imageUrl!,
                      fit: BoxFit.contain,
                      gaplessPlayback: true,
                      filterQuality: FilterQuality.low,
                      errorBuilder: (context, error, stackTrace) {
                        return const _VisionWaiting();
                      },
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _VisionWaiting extends StatelessWidget {
  const _VisionWaiting();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.hourglass_empty, size: 24, color: Colors.white54),
          SizedBox(height: 12),
          Text(
            '비전 서버 연결 대기',
            style: TextStyle(
              color: Colors.white70,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class _FinalMapPanel extends StatelessWidget {
  const _FinalMapPanel({
    required this.state,
    required this.error,
    required this.hostApiBase,
    required this.cacheKey,
    required this.refreshing,
    required this.onRefresh,
  });

  final JsonMap? state;
  final String? error;
  final Uri hostApiBase;
  final int cacheKey;
  final bool refreshing;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final manifest = _asMap(state?['manifest']);
    final plan = _asMap(state?['approved_plan'] ?? state?['plan']);
    final semantic = _asMap(state?['semantic_result']);
    final ready = state?['state'] == 'ready' && plan != null;
    final projection = _MissionProjection.fromManifest(manifest);
    final aspect = projection.imageWidth > 0 && projection.imageHeight > 0
        ? projection.imageWidth / projection.imageHeight
        : 16 / 9;
    final baseMapPath = _asString(state?['base_map_url']);
    final publishedCacheKey = _asString(state?['published_at']) ?? '$cacheKey';
    final baseMapUri = baseMapPath == null
        ? null
        : hostApiBase.resolve(baseMapPath);
    final baseMapUrl = baseMapUri
        ?.replace(
          queryParameters: {
            ...baseMapUri.queryParameters,
            't': publishedCacheKey,
          },
        )
        .toString();

    return Card(
      clipBehavior: Clip.antiAlias,
      color: _tabletSurface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 12),
            child: Row(
              children: [
                const Icon(Icons.map_outlined, size: 19, color: _tabletBlue),
                const SizedBox(width: 8),
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '최종 구조 지도',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w900,
                          color: _tabletInk,
                        ),
                      ),
                      SizedBox(height: 2),
                      Text(
                        'Host 승인 결과 · Wi-Fi HTTP 동기화',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          color: _tabletMuted,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 9,
                    vertical: 5,
                  ),
                  decoration: BoxDecoration(
                    color: ready ? _tabletGreenSoft : _tabletYellowSoft,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    ready
                        ? 'APPROVED v${_asInt(state?['approved_plan_version']) ?? '-'}'
                        : '승인 대기',
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w900,
                      color: ready ? _tabletGreen : _tabletYellow,
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                IconButton(
                  tooltip: '최종 지도 새로고침',
                  onPressed: refreshing ? null : onRefresh,
                  icon: refreshing
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.refresh),
                ),
              ],
            ),
          ),
          if (error != null)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              color: const Color(0xffffeeee),
              child: Text(
                'Host 연결 대기 · $error',
                style: const TextStyle(
                  color: _tabletRed,
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: ColoredBox(
                color: const Color(0xffe8ebed),
                child: AspectRatio(
                  aspectRatio: aspect.clamp(0.25, 5.0),
                  child: baseMapUrl == null
                      ? const _FinalMapWaiting(
                          text: 'Host ACTIVE Mission을 기다리는 중입니다.',
                        )
                      : Stack(
                          fit: StackFit.expand,
                          children: [
                            Image.network(
                              baseMapUrl,
                              fit: BoxFit.fill,
                              gaplessPlayback: true,
                              errorBuilder: (_, _, _) => const _FinalMapWaiting(
                                text: 'Host에서 구조도를 불러오지 못했습니다.',
                              ),
                            ),
                            CustomPaint(
                              painter: _FinalPlanPainter(
                                manifest: manifest,
                                plan: plan,
                                semantic: semantic,
                              ),
                            ),
                            if (!ready)
                              Align(
                                alignment: Alignment.topCenter,
                                child: Container(
                                  margin: const EdgeInsets.all(10),
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 10,
                                    vertical: 6,
                                  ),
                                  decoration: BoxDecoration(
                                    color: Colors.white.withValues(alpha: .92),
                                    borderRadius: BorderRadius.circular(7),
                                  ),
                                  child: const Text(
                                    '구조도 연결됨 · Host Approved Plan 생성 대기',
                                    style: TextStyle(
                                      fontSize: 10,
                                      fontWeight: FontWeight.w800,
                                      color: _tabletMuted,
                                    ),
                                  ),
                                ),
                              ),
                            const Positioned(
                              right: 10,
                              bottom: 10,
                              child: _FinalMapLegend(),
                            ),
                          ],
                        ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _FinalMapWaiting extends StatelessWidget {
  const _FinalMapWaiting({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.map_outlined, size: 30, color: _tabletMuted),
        const SizedBox(height: 10),
        Text(
          text,
          textAlign: TextAlign.center,
          style: const TextStyle(
            color: _tabletMuted,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    ),
  );
}

class _FinalPlanPainter extends CustomPainter {
  _FinalPlanPainter({
    required this.manifest,
    required this.plan,
    required this.semantic,
  });

  final JsonMap? manifest;
  final JsonMap? plan;
  final JsonMap? semantic;

  Offset? _missionPoint(Object? raw) {
    if (raw is! Map) return null;
    var value = Map<String, dynamic>.from(raw);
    for (final key in const [
      'map_position',
      'position',
      'map_point',
      'center',
      'current_position',
      'recommended_position',
    ]) {
      final nested = value[key];
      if (nested is Map) {
        value = Map<String, dynamic>.from(nested);
        break;
      }
    }
    final x = value['x'] ?? value['map_x'];
    final y = value['y'] ?? value['map_y'];
    if (x is! num || y is! num) return null;
    return Offset(x.toDouble(), y.toDouble());
  }

  Offset? _screen(Object? raw, Size size, _MissionProjection projection) {
    final mission = _missionPoint(raw);
    if (mission == null ||
        projection.imageWidth <= 0 ||
        projection.imageHeight <= 0) {
      return null;
    }
    final image = projection.missionToImage(mission);
    return Offset(
      image.dx / projection.imageWidth * size.width,
      image.dy / projection.imageHeight * size.height,
    );
  }

  List<Object?> _list(Object? raw) => raw is List ? raw : const [];

  List<Object?> _points(Object? raw) {
    if (raw is List) return raw;
    if (raw is! Map) return const [];
    final value = Map<String, dynamic>.from(raw);
    for (final key in const ['points', 'path', 'polygon', 'coordinates']) {
      final nested = value[key];
      if (nested is List) return nested;
    }
    return const [];
  }

  void _point(Canvas canvas, Offset point, Color color, {double radius = 7}) {
    canvas.drawCircle(point, radius, Paint()..color = color);
    canvas.drawCircle(
      point,
      radius + 2,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  void _polyline(
    Canvas canvas,
    List<Object?> values,
    Size size,
    _MissionProjection projection,
    Color color, {
    double width = 4,
  }) {
    final points = values
        .map((item) => _screen(item, size, projection))
        .whereType<Offset>()
        .toList();
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

  void _polygon(
    Canvas canvas,
    Object? raw,
    Size size,
    _MissionProjection projection,
    Color color,
  ) {
    final points = _points(raw)
        .map((item) => _screen(item, size, projection))
        .whereType<Offset>()
        .toList();
    if (points.isEmpty) return;
    if (points.length == 1) {
      _point(canvas, points.first, color);
      return;
    }
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (final point in points.skip(1)) {
      path.lineTo(point.dx, point.dy);
    }
    if (points.length >= 3) path.close();
    canvas.drawPath(
      path,
      Paint()
        ..color = color.withValues(alpha: .20)
        ..style = PaintingStyle.fill,
    );
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5,
    );
  }

  @override
  void paint(Canvas canvas, Size size) {
    final projection = _MissionProjection.fromManifest(manifest);
    final semanticValue = semantic ?? const <String, dynamic>{};
    final planValue = plan ?? const <String, dynamic>{};

    for (final obstacle in _list(semanticValue['obstacles'])) {
      _polygon(canvas, obstacle, size, projection, const Color(0xff555555));
    }
    _polyline(
      canvas,
      _list(semanticValue['robot_trajectory']),
      size,
      projection,
      const Color(0xff00a7c4),
      width: 3,
    );
    final robot = _screen(semanticValue['robot_pose'], size, projection);
    if (robot != null) {
      _point(canvas, robot, _tabletBlue, radius: 6);
    }

    for (final risk in _list(planValue['approved_risk_zones'])) {
      _polygon(canvas, risk, size, projection, const Color(0xffef476f));
    }
    for (final route in _list(planValue['approved_routes'])) {
      _polyline(
        canvas,
        _points(route),
        size,
        projection,
        const Color(0xff2878ff),
      );
    }
    for (final victim in _list(planValue['approved_victims'])) {
      final point = _screen(victim, size, projection);
      if (point != null) {
        _point(canvas, point, const Color(0xffe60026), radius: 8);
      }
    }
    for (final assignment in _list(planValue['final_team_assignments'])) {
      final point = _screen(assignment, size, projection);
      if (point != null) {
        _point(canvas, point, const Color(0xff8a2be2), radius: 7);
      }
    }
    for (final waiting in _list(planValue['safe_waiting_points'])) {
      final point = _screen(waiting, size, projection);
      if (point != null) {
        _point(canvas, point, const Color(0xff00a878), radius: 7);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _FinalPlanPainter oldDelegate) => true;
}

class _FinalMapLegend extends StatelessWidget {
  const _FinalMapLegend();

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .94),
      border: Border.all(color: _tabletLine),
      borderRadius: BorderRadius.circular(7),
    ),
    child: const Wrap(
      spacing: 8,
      runSpacing: 5,
      children: [
        _FinalLegendDot(color: Color(0xffe60026), label: '요구조자'),
        _FinalLegendDot(color: Color(0xffef476f), label: '위험'),
        _FinalLegendDot(color: Color(0xff2878ff), label: '경로'),
        _FinalLegendDot(color: Color(0xff8a2be2), label: '구조팀'),
        _FinalLegendDot(color: Color(0xff00a878), label: 'Safe'),
        _FinalLegendDot(color: Color(0xff00a7c4), label: '로봇'),
      ],
    ),
  );
}

class _FinalLegendDot extends StatelessWidget {
  const _FinalLegendDot({required this.color, required this.label});

  final Color color;
  final String label;

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
      Text(
        label,
        style: const TextStyle(fontSize: 8, fontWeight: FontWeight.w700),
      ),
    ],
  );
}
