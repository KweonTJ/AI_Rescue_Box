part of 'jetson_app.dart';

enum _MissionEditMode { robotStart, scaleFirst, scaleSecond, entrance }

class _MissionManagementHome extends StatelessWidget {
  const _MissionManagementHome({required this.controller});

  final JetsonController controller;

  @override
  Widget build(BuildContext context) {
    final connected = controller.error == null || controller.health.isNotEmpty;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mission 관리'),
        actions: [
          IconButton(
            tooltip: '새로고침',
            onPressed: controller.busy ? null : controller.refresh,
            icon: const Icon(Icons.refresh),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 980),
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Text(
                  '현장 Mission 설정',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 8),
                Text(
                  '구조도와 위치 정보를 만들거나 수정합니다. 저장된 Mission은 ACTIVE 페이지에서 별도로 선택합니다.',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 24),
                if (!connected)
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(18),
                      child: Row(
                        children: [
                          const Icon(Icons.cloud_off_outlined, size: 34),
                          const SizedBox(width: 14),
                          Expanded(
                            child: Text(
                              'Jetson 연결을 먼저 확인하세요.\n${controller.error ?? ''}',
                            ),
                          ),
                          FilledButton.icon(
                            onPressed: controller.busy
                                ? null
                                : controller.initialise,
                            icon: const Icon(Icons.refresh),
                            label: const Text('재시도'),
                          ),
                        ],
                      ),
                    ),
                  ),
                const SizedBox(height: 8),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final cards = [
                      _MissionActionCard(
                        key: const Key('new-mission-action'),
                        icon: Icons.add_photo_alternate_outlined,
                        title: '새 Mission 만들기',
                        description:
                            '태블릿의 JPG/PNG 구조도를 선택하고 축척, 로봇 시작 위치, 출입구를 지정합니다.',
                        buttonLabel: '새로 만들기',
                        onPressed: !connected
                            ? null
                            : () async {
                                await Navigator.of(context).push(
                                  MaterialPageRoute<void>(
                                    builder: (_) => _MissionEditorPage(
                                      controller: controller,
                                    ),
                                  ),
                                );
                              },
                      ),
                      _MissionActionCard(
                        key: const Key('edit-mission-action'),
                        icon: Icons.folder_copy_outlined,
                        title: '기존 Mission 수정',
                        description:
                            'Jetson에 저장된 Mission을 불러와 수정합니다. 기존 버전은 유지되고 새 버전으로 저장됩니다.',
                        buttonLabel: 'Mission 보관함',
                        onPressed: !connected || controller.missions.isEmpty
                            ? null
                            : () async {
                                await Navigator.of(context).push(
                                  MaterialPageRoute<void>(
                                    builder: (_) => _MissionLibraryPage(
                                      controller: controller,
                                    ),
                                  ),
                                );
                              },
                      ),
                    ];
                    if (constraints.maxWidth < 700) {
                      return Column(
                        children: [
                          cards[0],
                          const SizedBox(height: 16),
                          cards[1],
                        ],
                      );
                    }
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(child: cards[0]),
                        const SizedBox(width: 16),
                        Expanded(child: cards[1]),
                      ],
                    );
                  },
                ),
                const SizedBox(height: 22),
                _SectionCard(
                  title: 'Jetson Mission 보관함',
                  subtitle: '저장된 버전 수와 현재 ACTIVE 상태를 확인합니다.',
                  child: controller.missions.isEmpty
                      ? const _EmptyState(
                          icon: Icons.folder_off_outlined,
                          title: '저장된 Mission이 없습니다.',
                          body: '새 Mission을 만들면 이 보관함에 추가됩니다.',
                        )
                      : Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            _MetricPill(
                              label: '저장 버전',
                              value: '${controller.missions.length}',
                            ),
                            _MetricPill(
                              label: 'ACTIVE',
                              value: controller.selectedMissionId == null
                                  ? '없음'
                                  : '${controller.selectedMissionId} v${controller.selectedMissionVersion}',
                            ),
                          ],
                        ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _MissionActionCard extends StatelessWidget {
  const _MissionActionCard({
    super.key,
    required this.icon,
    required this.title,
    required this.description,
    required this.buttonLabel,
    required this.onPressed,
  });

  final IconData icon;
  final String title;
  final String description;
  final String buttonLabel;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 42),
          const SizedBox(height: 18),
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          Text(description),
          const Spacer(),
          const SizedBox(height: 22),
          SizedBox(
            width: double.infinity,
            child: FilledButton(onPressed: onPressed, child: Text(buttonLabel)),
          ),
        ],
      ),
    ),
  );
}

class _MissionLibraryPage extends StatefulWidget {
  const _MissionLibraryPage({required this.controller});

  final JetsonController controller;

  @override
  State<_MissionLibraryPage> createState() => _MissionLibraryPageState();
}

class _MissionLibraryPageState extends State<_MissionLibraryPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      await widget.controller.refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    final missions = [...widget.controller.missions]
      ..sort((a, b) {
        final idCompare = (_asString(a['mission_id']) ?? '').compareTo(
          _asString(b['mission_id']) ?? '',
        );
        if (idCompare != 0) return idCompare;
        return (_asInt(b['mission_version'] ?? b['version']) ?? 0).compareTo(
          _asInt(a['mission_version'] ?? a['version']) ?? 0,
        );
      });
    return Scaffold(
      appBar: AppBar(title: const Text('기존 Mission 수정')),
      body: SafeArea(
        child: missions.isEmpty
            ? const _EmptyState(
                icon: Icons.folder_off_outlined,
                title: '수정할 Mission이 없습니다.',
                body: '먼저 새 Mission을 만들어 주세요.',
              )
            : ListView.separated(
                padding: const EdgeInsets.all(18),
                itemCount: missions.length,
                separatorBuilder: (_, _) => const SizedBox(height: 10),
                itemBuilder: (context, index) {
                  final mission = missions[index];
                  final id = _asString(mission['mission_id']) ?? 'unknown';
                  final version =
                      _asInt(
                        mission['mission_version'] ?? mission['version'],
                      ) ??
                      0;
                  final active = mission['active'] == true;
                  return Card(
                    child: ListTile(
                      key: Key('edit-$id-v$version'),
                      leading: const Icon(Icons.map_outlined),
                      title: Text('$id · v$version'),
                      subtitle: Text(
                        active
                            ? '현재 ACTIVE · 수정 시 새 버전으로 저장'
                            : '수정 시 기존 버전을 보존하고 새 버전으로 저장',
                      ),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          if (active)
                            const Padding(
                              padding: EdgeInsets.only(right: 10),
                              child: _MiniLabel(text: 'ACTIVE', good: true),
                            ),
                          const Icon(Icons.chevron_right),
                        ],
                      ),
                      onTap: () async {
                        await Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => _MissionEditorPage(
                              controller: widget.controller,
                              sourceMission: mission,
                            ),
                          ),
                        );
                        if (mounted) setState(() {});
                      },
                    ),
                  );
                },
              ),
      ),
    );
  }
}

class _MissionEditorPage extends StatefulWidget {
  const _MissionEditorPage({required this.controller, this.sourceMission});

  final JetsonController controller;
  final JsonMap? sourceMission;

  bool get editing => sourceMission != null;

  @override
  State<_MissionEditorPage> createState() => _MissionEditorPageState();
}

class _MissionEditorPageState extends State<_MissionEditorPage> {
  final _missionIdController = TextEditingController();
  final _missionNameController = TextEditingController(text: '현장 임무');
  final _metersPerPixelController = TextEditingController();
  final _scaleDistanceController = TextEditingController(text: '1.0');
  final _notesController = TextEditingController();

  Uint8List? _mapBytes;
  String? _mapFilename;
  int _imageWidth = 1;
  int _imageHeight = 1;
  bool _imageChanged = false;
  Offset? _robotStart;
  double _robotYaw = 0;
  bool _yawSpecified = false;
  Offset? _scaleFirst;
  Offset? _scaleSecond;
  final List<Offset> _entrances = [];
  _MissionEditMode _editMode = _MissionEditMode.robotStart;
  Offset? _dragStart;
  int? _sourceVersion;
  int? _nextVersion;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    if (widget.editing) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _loadExisting());
    }
  }

  @override
  void dispose() {
    for (final controller in [
      _missionIdController,
      _missionNameController,
      _metersPerPixelController,
      _scaleDistanceController,
      _notesController,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _loadExisting() async {
    final summary = widget.sourceMission!;
    final id = _asString(summary['mission_id']);
    final version = _asInt(summary['mission_version'] ?? summary['version']);
    if (id == null || version == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final detail = await widget.controller.backend.getMission(id, version);
      final manifest = _asMap(detail['manifest']) ?? detail;
      final transform = _asMap(manifest['coordinate_transform']) ?? const {};
      final robot = _asMap(manifest['robot_start']) ?? const {};
      final robotImage =
          _asMap(transform['robot_start_image']) ??
          (_asDouble(robot['image_x']) != null &&
                  _asDouble(robot['image_y']) != null
              ? {'x': robot['image_x'], 'y': robot['image_y']}
              : _asMap(transform['image_origin']));
      final rx = _asDouble(robotImage?['x']);
      final ry = _asDouble(robotImage?['y']);
      final scale = _asDouble(
        manifest['meters_per_pixel'] ?? transform['meters_per_pixel'],
      );
      final imageYaw =
          _asDouble(transform['initial_image_yaw']) ??
          _asDouble(transform['rotation_radians']) ??
          0.0;
      final mapInfo = _asMap(manifest['base_map']) ?? const {};
      final width = _asInt(manifest['base_map_width'] ?? mapInfo['width']) ?? 1;
      final height =
          _asInt(manifest['base_map_height'] ?? mapInfo['height']) ?? 1;
      final entrances = _asObjectList(manifest['entrances']);
      final imageEntrances = <Offset>[];
      for (final entrance in entrances) {
        final ex = _asDouble(entrance['image_x']);
        final ey = _asDouble(entrance['image_y']);
        if (ex != null && ey != null) {
          imageEntrances.add(Offset(ex, ey));
          continue;
        }
        final converted = _mapToImage(entrance, transform);
        if (converted != null) imageEntrances.add(converted);
      }
      final bytes = await widget.controller.backend.downloadArtifact(
        '/api/v1/missions/$id/$version/display-map.png',
      );
      var latest = version;
      for (final item in widget.controller.missions) {
        if (_asString(item['mission_id']) == id) {
          latest = math.max(
            latest,
            _asInt(item['mission_version'] ?? item['version']) ?? 0,
          );
        }
      }
      if (!mounted) return;
      setState(() {
        _missionIdController.text = id;
        _missionNameController.text = _asString(manifest['mission_name']) ?? id;
        _metersPerPixelController.text = scale?.toStringAsPrecision(8) ?? '';
        _notesController.text = _asString(manifest['notes']) ?? '';
        _mapBytes = bytes;
        _mapFilename =
            _asString(manifest['source_image_filename']) ??
            _asString(mapInfo['filename']) ??
            'base_map.png';
        _imageWidth = width;
        _imageHeight = height;
        _imageChanged = false;
        _sourceVersion = version;
        _nextVersion = latest + 1;
        if (rx != null && ry != null) _robotStart = Offset(rx, ry);
        _robotYaw = imageYaw;
        _yawSpecified = _robotStart != null;
        _entrances
          ..clear()
          ..addAll(imageEntrances);
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = _message(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Offset? _mapToImage(JsonMap point, JsonMap transform) {
    final mapX = _asDouble(point['x'] ?? point['map_x']);
    final mapY = _asDouble(point['y'] ?? point['map_y']);
    final origin = _asMap(transform['image_origin']);
    final ox = _asDouble(origin?['x']);
    final oy = _asDouble(origin?['y']);
    final scale = _asDouble(transform['meters_per_pixel']);
    final rotation = _asDouble(transform['rotation_radians']) ?? 0.0;
    if (mapX == null ||
        mapY == null ||
        ox == null ||
        oy == null ||
        scale == null ||
        scale <= 0) {
      return null;
    }
    final cosine = math.cos(rotation);
    final sine = math.sin(rotation);
    final dx = cosine * mapX + sine * mapY;
    var dy = -sine * mapX + cosine * mapY;
    if (transform['invert_y'] != false) dy = -dy;
    return Offset(ox + dx / scale, oy + dy / scale);
  }

  Future<void> _pickMap() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['jpg', 'jpeg', 'png'],
      withData: true,
    );
    final file = result?.files.single;
    final bytes = file?.bytes;
    if (file == null || bytes == null) return;
    try {
      final codec = await ui.instantiateImageCodec(bytes);
      final frame = await codec.getNextFrame();
      if (!mounted) return;
      setState(() {
        _mapBytes = bytes;
        _mapFilename = file.name;
        _imageWidth = frame.image.width;
        _imageHeight = frame.image.height;
        _imageChanged = true;
        _robotStart = null;
        _yawSpecified = false;
        _scaleFirst = null;
        _scaleSecond = null;
        _entrances.clear();
        _error = null;
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = '이미지를 열 수 없습니다: ${_message(error)}');
    }
  }

  double? get _metersPerPixel {
    final value = double.tryParse(_metersPerPixelController.text.trim());
    return value != null && value.isFinite && value > 0 ? value : null;
  }

  void _calculateScale() {
    final first = _scaleFirst;
    final second = _scaleSecond;
    final distance = double.tryParse(_scaleDistanceController.text.trim());
    if (first == null || second == null || distance == null || distance <= 0) {
      setState(() => _error = '축척점 2개와 실제 거리를 입력하세요.');
      return;
    }
    final pixels = (second - first).distance;
    if (pixels <= 0) return;
    final scale = distance / pixels;
    setState(() {
      _metersPerPixelController.text = scale.toStringAsPrecision(8);
      _error = null;
    });
  }

  Offset _imagePoint(Offset local, Size size) => Offset(
    (local.dx / size.width * _imageWidth).clamp(0, _imageWidth.toDouble()),
    (local.dy / size.height * _imageHeight).clamp(0, _imageHeight.toDouble()),
  );

  void _mapTap(Offset value) {
    setState(() {
      switch (_editMode) {
        case _MissionEditMode.robotStart:
          _robotStart = value;
          _robotYaw = 0;
          _yawSpecified = true;
        case _MissionEditMode.scaleFirst:
          _scaleFirst = value;
          _scaleSecond = null;
          _editMode = _MissionEditMode.scaleSecond;
        case _MissionEditMode.scaleSecond:
          _scaleSecond = value;
        case _MissionEditMode.entrance:
          _entrances.add(value);
      }
    });
  }

  Future<void> _save() async {
    final map = _mapBytes;
    final start = _robotStart;
    final scale = _metersPerPixel;
    if (map == null || _mapFilename == null) {
      setState(() => _error = '구조도 JPG/PNG를 선택하세요.');
      return;
    }
    if (start == null || !_yawSpecified) {
      setState(() => _error = '로봇 시작 위치와 방향을 지정하세요.');
      return;
    }
    if (scale == null) {
      setState(() => _error = '올바른 축척(m/pixel)을 입력하거나 계산하세요.');
      return;
    }
    if (_entrances.isEmpty) {
      setState(() => _error = '출입구를 하나 이상 지정하세요.');
      return;
    }
    final name = _missionNameController.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'Mission 이름을 입력하세요.');
      return;
    }

    final draft = <String, Object?>{
      if (_missionIdController.text.trim().isNotEmpty)
        'mission_id': _missionIdController.text.trim(),
      'mission_name': name,
      'meters_per_pixel': scale,
      'robot_start_image': {'x': start.dx, 'y': start.dy},
      'initial_yaw': _robotYaw,
      'entrances': [
        for (final entrance in _entrances) {'x': entrance.dx, 'y': entrance.dy},
      ],
      'notes': _notesController.text,
    };

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final stored = await widget.controller.backend.storeTabletMission(
        draft,
        filename: _imageChanged || !widget.editing ? _mapFilename : null,
        bytes: _imageChanged || !widget.editing ? map : null,
        reuseFromVersion: widget.editing && !_imageChanged
            ? _sourceVersion
            : null,
      );
      await widget.controller.refresh();
      if (!mounted) return;
      final id =
          _asString(stored['mission_id']) ??
          _asString(_asMap(stored['manifest'])?['mission_id']) ??
          _missionIdController.text;
      final version =
          _asInt(stored['mission_version']) ??
          _asInt(_asMap(stored['manifest'])?['mission_version']) ??
          _nextVersion ??
          1;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$id · v$version 저장 완료 (STORED)')));
      Navigator.of(context).pop();
    } on Object catch (error) {
      if (mounted) setState(() => _error = _message(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bytes = _mapBytes;
    final title = widget.editing ? 'Mission 수정' : '새 Mission 만들기';
    return Scaffold(
      appBar: AppBar(
        title: Text(title),
        actions: [
          if (widget.editing && _nextVersion != null)
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Center(
                child: _MiniLabel(text: '새 버전 v$_nextVersion', good: true),
              ),
            ),
        ],
      ),
      body: SafeArea(
        child: Stack(
          children: [
            Positioned.fill(
              child: ListView(
                padding: const EdgeInsets.all(18),
                children: [
                  if (_error != null) ...[
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Text(
                          _error!,
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                  ],
                  _SectionCard(
                    title: '1. Mission 정보',
                    subtitle: widget.editing
                        ? '기존 버전은 보존되고 저장 시 새 버전이 생성됩니다.'
                        : 'Mission 이름과 현장 인원을 입력합니다.',
                    child: Column(
                      children: [
                        TextField(
                          controller: _missionIdController,
                          readOnly: widget.editing,
                          decoration: InputDecoration(
                            labelText: 'Mission ID',
                            hintText: widget.editing ? null : '비워두면 자동 생성',
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _missionNameController,
                          decoration: const InputDecoration(
                            labelText: 'Mission 이름',
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _notesController,
                          maxLines: 2,
                          decoration: const InputDecoration(labelText: '메모'),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),
                  _SectionCard(
                    title: '2. 구조도',
                    subtitle: widget.editing && !_imageChanged
                        ? '현재 구조도를 그대로 사용하면 Jetson이 원본/전처리 결과를 재사용합니다.'
                        : '태블릿에 저장된 JPEG 또는 PNG를 선택합니다.',
                    trailing: FilledButton.icon(
                      key: const Key('tablet-pick-map'),
                      onPressed: _busy ? null : _pickMap,
                      icon: const Icon(Icons.photo_library_outlined),
                      label: Text(bytes == null ? '사진 선택' : '사진 변경'),
                    ),
                    child: bytes == null
                        ? const SizedBox(
                            height: 220,
                            child: _EmptyState(
                              icon: Icons.image_outlined,
                              title: '구조도 미선택',
                              body: 'JPG/PNG 구조도를 선택하세요.',
                            ),
                          )
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text(
                                '${_mapFilename ?? '-'} · $_imageWidth × $_imageHeight',
                              ),
                              const SizedBox(height: 12),
                              _MissionImageEditor(
                                bytes: bytes,
                                imageWidth: _imageWidth,
                                imageHeight: _imageHeight,
                                editMode: _editMode,
                                robotStart: _robotStart,
                                robotYaw: _robotYaw,
                                scaleFirst: _scaleFirst,
                                scaleSecond: _scaleSecond,
                                entrances: _entrances,
                                onTap: _mapTap,
                                onRobotDragStart: (value) {
                                  _dragStart = value;
                                  setState(() {
                                    _robotStart = value;
                                    _yawSpecified = true;
                                  });
                                },
                                onRobotDragUpdate: (value) {
                                  final start = _dragStart;
                                  if (start == null) return;
                                  setState(() {
                                    _robotStart = start;
                                    _robotYaw = math.atan2(
                                      value.dy - start.dy,
                                      value.dx - start.dx,
                                    );
                                    _yawSpecified = true;
                                  });
                                },
                                onRobotDragEnd: () => _dragStart = null,
                              ),
                            ],
                          ),
                  ),
                  const SizedBox(height: 14),
                  _SectionCard(
                    title: '3. 구조도 설정',
                    subtitle: '구조도 위에서 로봇 시작 위치, 축척 기준점, 출입구를 지정합니다.',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            ChoiceChip(
                              selected:
                                  _editMode == _MissionEditMode.robotStart,
                              label: const Text('로봇 시작 위치/방향'),
                              onSelected: (_) => setState(
                                () => _editMode = _MissionEditMode.robotStart,
                              ),
                            ),
                            ChoiceChip(
                              selected:
                                  _editMode == _MissionEditMode.scaleFirst ||
                                  _editMode == _MissionEditMode.scaleSecond,
                              label: const Text('축척 두 점 지정'),
                              onSelected: (_) => setState(() {
                                _scaleFirst = null;
                                _scaleSecond = null;
                                _editMode = _MissionEditMode.scaleFirst;
                              }),
                            ),
                            ChoiceChip(
                              selected: _editMode == _MissionEditMode.entrance,
                              label: const Text('출입구 추가'),
                              onSelected: (_) => setState(
                                () => _editMode = _MissionEditMode.entrance,
                              ),
                            ),
                            OutlinedButton.icon(
                              onPressed: _entrances.isEmpty
                                  ? null
                                  : () => setState(_entrances.clear),
                              icon: const Icon(Icons.delete_outline),
                              label: const Text('출입구 초기화'),
                            ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        Row(
                          children: [
                            Expanded(
                              child: TextField(
                                controller: _scaleDistanceController,
                                keyboardType:
                                    const TextInputType.numberWithOptions(
                                      decimal: true,
                                    ),
                                decoration: const InputDecoration(
                                  labelText: '두 점의 실제 거리 (m)',
                                ),
                              ),
                            ),
                            const SizedBox(width: 10),
                            FilledButton.tonal(
                              onPressed:
                                  _scaleFirst != null && _scaleSecond != null
                                  ? _calculateScale
                                  : null,
                              child: const Text('축척 계산'),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _metersPerPixelController,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: const InputDecoration(
                            labelText: '축척 (m/pixel)',
                            helperText: '직접 입력하거나 위 두 점으로 계산할 수 있습니다.',
                          ),
                        ),
                        const SizedBox(height: 12),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            _MetricPill(
                              label: 'Robot',
                              value: _robotStart == null
                                  ? '미지정'
                                  : '(${_robotStart!.dx.toStringAsFixed(0)}, ${_robotStart!.dy.toStringAsFixed(0)})',
                            ),
                            _MetricPill(
                              label: 'Yaw',
                              value: _yawSpecified
                                  ? '${(_robotYaw * 180 / math.pi).toStringAsFixed(1)}°'
                                  : '미지정',
                            ),
                            _MetricPill(
                              label: '출입구',
                              value: '${_entrances.length}개',
                            ),
                            _MetricPill(
                              label: 'Scale',
                              value: _metersPerPixel == null
                                  ? '미지정'
                                  : '${_metersPerPixel!.toStringAsPrecision(5)} m/px',
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 18),
                  SizedBox(
                    height: 52,
                    child: FilledButton.icon(
                      key: const Key('store-tablet-mission'),
                      onPressed: _busy ? null : _save,
                      icon: const Icon(Icons.cloud_upload_outlined),
                      label: Text(
                        widget.editing
                            ? '새 버전으로 Jetson에 저장'
                            : 'Jetson에 Mission 저장',
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                ],
              ),
            ),
            if (_busy)
              const Positioned.fill(
                child: ColoredBox(
                  color: Color(0x66000000),
                  child: Center(child: CircularProgressIndicator()),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _MissionImageEditor extends StatelessWidget {
  const _MissionImageEditor({
    required this.bytes,
    required this.imageWidth,
    required this.imageHeight,
    required this.editMode,
    required this.robotStart,
    required this.robotYaw,
    required this.scaleFirst,
    required this.scaleSecond,
    required this.entrances,
    required this.onTap,
    required this.onRobotDragStart,
    required this.onRobotDragUpdate,
    required this.onRobotDragEnd,
  });

  final Uint8List bytes;
  final int imageWidth;
  final int imageHeight;
  final _MissionEditMode editMode;
  final Offset? robotStart;
  final double robotYaw;
  final Offset? scaleFirst;
  final Offset? scaleSecond;
  final List<Offset> entrances;
  final ValueChanged<Offset> onTap;
  final ValueChanged<Offset> onRobotDragStart;
  final ValueChanged<Offset> onRobotDragUpdate;
  final VoidCallback onRobotDragEnd;

  Offset _point(Offset local, Size size) => Offset(
    (local.dx / size.width * imageWidth).clamp(0, imageWidth.toDouble()),
    (local.dy / size.height * imageHeight).clamp(0, imageHeight.toDouble()),
  );

  @override
  Widget build(BuildContext context) {
    final aspect = math.max(0.1, imageWidth / imageHeight);
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 620, maxWidth: 1100),
        child: AspectRatio(
          aspectRatio: aspect,
          child: InteractiveViewer(
            minScale: 0.5,
            maxScale: 8,
            child: LayoutBuilder(
              builder: (context, constraints) {
                final size = constraints.biggest;
                return GestureDetector(
                  onTapDown: (details) =>
                      onTap(_point(details.localPosition, size)),
                  onPanStart: editMode == _MissionEditMode.robotStart
                      ? (details) => onRobotDragStart(
                          _point(details.localPosition, size),
                        )
                      : null,
                  onPanUpdate: editMode == _MissionEditMode.robotStart
                      ? (details) => onRobotDragUpdate(
                          _point(details.localPosition, size),
                        )
                      : null,
                  onPanEnd: editMode == _MissionEditMode.robotStart
                      ? (_) => onRobotDragEnd()
                      : null,
                  child: CustomPaint(
                    foregroundPainter: _MissionDraftPainter(
                      imageWidth: imageWidth,
                      imageHeight: imageHeight,
                      robotStart: robotStart,
                      robotYaw: robotYaw,
                      scaleFirst: scaleFirst,
                      scaleSecond: scaleSecond,
                      entrances: entrances,
                    ),
                    child: Image.memory(
                      bytes,
                      fit: BoxFit.fill,
                      gaplessPlayback: true,
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

class _MissionDraftPainter extends CustomPainter {
  const _MissionDraftPainter({
    required this.imageWidth,
    required this.imageHeight,
    required this.robotStart,
    required this.robotYaw,
    required this.scaleFirst,
    required this.scaleSecond,
    required this.entrances,
  });

  final int imageWidth;
  final int imageHeight;
  final Offset? robotStart;
  final double robotYaw;
  final Offset? scaleFirst;
  final Offset? scaleSecond;
  final List<Offset> entrances;

  Offset _screen(Offset value, Size size) => Offset(
    value.dx / imageWidth * size.width,
    value.dy / imageHeight * size.height,
  );

  @override
  void paint(Canvas canvas, Size size) {
    final robot = robotStart;
    if (robot != null) {
      final center = _screen(robot, size);
      final paint = Paint()
        ..color = const Color(0xff06d6a0)
        ..strokeWidth = 3
        ..style = PaintingStyle.stroke;
      canvas.drawCircle(center, 10, paint);
      canvas.drawLine(
        center,
        center + Offset(math.cos(robotYaw) * 38, math.sin(robotYaw) * 38),
        paint,
      );
    }
    final scalePaint = Paint()
      ..color = const Color(0xffffd166)
      ..strokeWidth = 3;
    if (scaleFirst != null) {
      canvas.drawCircle(_screen(scaleFirst!, size), 6, scalePaint);
    }
    if (scaleSecond != null) {
      canvas.drawCircle(_screen(scaleSecond!, size), 6, scalePaint);
      if (scaleFirst != null) {
        canvas.drawLine(
          _screen(scaleFirst!, size),
          _screen(scaleSecond!, size),
          scalePaint,
        );
      }
    }
    final entrancePaint = Paint()..color = const Color(0xff118ab2);
    for (final entrance in entrances) {
      canvas.drawRect(
        Rect.fromCenter(center: _screen(entrance, size), width: 14, height: 14),
        entrancePaint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _MissionDraftPainter oldDelegate) => true;
}

String _message(Object error) {
  if (error is ApiFailure) return error.message;
  return error.toString().replaceFirst(
    RegExp(r'^[A-Za-z]+(?:Error|Exception): '),
    '',
  );
}
