part of 'jetson_app.dart';

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
  Timer? _refreshTimer;
  int _frameToken = 0;

  @override
  void initState() {
    super.initState();
    _refreshTimer = Timer.periodic(
      const Duration(milliseconds: 400),
      (_) {
        if (!mounted) return;
        setState(() => _frameToken++);
      },
    );
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    super.dispose();
  }

  Uri? get _visionBase {
    final api = widget.controller.apiBaseUri;
    if (api == null || api.host.isEmpty) return null;
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
        .replace(path: path, queryParameters: {'frame': '$_frameToken'})
        .toString();
  }

  @override
  Widget build(BuildContext context) {
    final missionId = widget.controller.selectedMissionId;
    final missionVersion = widget.controller.selectedMissionVersion;
    final missionLabel = missionId == null
        ? 'ACTIVE Mission 미선택'
        : '$missionId · v${missionVersion ?? '-'}';

    return ColoredBox(
      color: _tabletBackground,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '현장 비전',
                        style: TextStyle(
                          color: _tabletInk,
                          fontSize: 24,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      SizedBox(height: 4),
                      Text(
                        'Astra RGB-D · MediaPipe 요구조자 탐지 · Depth 장애물',
                        style: TextStyle(
                          color: _tabletMuted,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
                Text(
                  missionLabel,
                  style: const TextStyle(
                    color: _tabletMuted,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(width: 12),
                OutlinedButton.icon(
                  onPressed: widget.onChooseAnotherMission,
                  icon: const Icon(Icons.swap_horiz),
                  label: const Text('Mission 변경'),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final person = _LiveVisionPanel(
                    title: 'PERSON DETECTION',
                    subtitle: 'MediaPipe EfficientDet · RGB',
                    imageUrl: _imageUrl('/person.jpg'),
                  );
                  final depth = _LiveVisionPanel(
                    title: 'DEPTH OBSTACLE',
                    subtitle: 'Astra Depth · 근거리 장애물/거리',
                    imageUrl: _imageUrl('/depth.jpg'),
                  );

                  if (constraints.maxWidth < 820) {
                    return ListView(
                      children: [
                        SizedBox(height: 340, child: person),
                        const SizedBox(height: 14),
                        SizedBox(height: 340, child: depth),
                      ],
                    );
                  }

                  return Row(
                    children: [
                      Expanded(child: person),
                      const SizedBox(width: 16),
                      Expanded(child: depth),
                    ],
                  );
                },
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                const Icon(Icons.circle, size: 9, color: _tabletGreen),
                const SizedBox(width: 7),
                Text(
                  _visionBase == null
                      ? 'Vision Server 연결 대기'
                      : 'Vision Server · ${_visionBase!.host}:8091',
                  style: const TextStyle(
                    color: _tabletMuted,
                    fontSize: 11,
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

class _LiveVisionPanel extends StatelessWidget {
  const _LiveVisionPanel({
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
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: const TextStyle(
                          color: _tabletInk,
                          fontSize: 14,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        subtitle,
                        style: const TextStyle(
                          color: _tabletMuted,
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
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
                    color: _tabletGreen,
                    fontSize: 10,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: ColoredBox(
              color: const Color(0xff111719),
              child: imageUrl == null
                  ? const _VisionWaiting()
                  : Image.network(
                      imageUrl!,
                      fit: BoxFit.contain,
                      gaplessPlayback: true,
                      filterQuality: FilterQuality.low,
                      errorBuilder: (_, _, _) => const _VisionWaiting(),
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
          CircularProgressIndicator(strokeWidth: 2, color: Colors.white54),
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