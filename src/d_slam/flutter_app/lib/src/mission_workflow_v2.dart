part of 'jetson_app.dart';

class _MissionLibraryV2Page extends StatefulWidget {
  const _MissionLibraryV2Page({required this.controller});
  final JetsonController controller;

  @override
  State<_MissionLibraryV2Page> createState() => _MissionLibraryV2PageState();
}

class _MissionLibraryV2PageState extends State<_MissionLibraryV2Page> {
  String _query = '';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => widget.controller.refresh(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final groups = <String, List<JsonMap>>{};
    for (final item in widget.controller.missions) {
      final id = _asString(item['mission_id']) ?? 'unknown';
      final name = (_asString(item['mission_name']) ?? id).toLowerCase();
      if (_query.isNotEmpty &&
          !id.toLowerCase().contains(_query) &&
          !name.contains(_query)) {
        continue;
      }
      groups.putIfAbsent(id, () => <JsonMap>[]).add(item);
    }
    for (final items in groups.values) {
      items.sort(
        (a, b) => (_asInt(b['mission_version'] ?? b['version']) ?? 0).compareTo(
          _asInt(a['mission_version'] ?? a['version']) ?? 0,
        ),
      );
    }
    final ids = groups.keys.toList()..sort();
    return Scaffold(
      backgroundColor: _tabletBackground,
      appBar: AppBar(title: const Text('기존 Mission 수정')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1260),
          child: ListView(
            padding: const EdgeInsets.all(26),
            children: [
              const Text(
                'STORED MISSIONS',
                style: TextStyle(
                  color: _tabletMuted,
                  fontSize: 10,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 1.2,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                '수정할 Version을 선택하세요',
                style: TextStyle(
                  color: _tabletInk,
                  fontSize: 25,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                '원본 Version은 유지되고 수정본은 다음 Version으로 저장됩니다.',
                style: TextStyle(color: _tabletMuted, fontSize: 12),
              ),
              const SizedBox(height: 18),
              TextField(
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search),
                  hintText: 'Mission 이름 또는 ID 검색',
                ),
                onChanged: (value) =>
                    setState(() => _query = value.trim().toLowerCase()),
              ),
              const SizedBox(height: 16),
              if (ids.isEmpty)
                const _MissionSelectorMessage(
                  icon: Icons.folder_off_outlined,
                  title: '수정할 Mission이 없습니다.',
                  body: '먼저 새 Mission을 만들어 주세요.',
                )
              else
                for (final id in ids) ...[
                  _MissionFamilyV2(
                    controller: widget.controller,
                    missionId: id,
                    versions: groups[id]!,
                  ),
                  const SizedBox(height: 14),
                ],
            ],
          ),
        ),
      ),
    );
  }
}

class _MissionFamilyV2 extends StatelessWidget {
  const _MissionFamilyV2({
    required this.controller,
    required this.missionId,
    required this.versions,
  });
  final JetsonController controller;
  final String missionId;
  final List<JsonMap> versions;

  @override
  Widget build(BuildContext context) {
    final name = _asString(versions.first['mission_name']) ?? missionId;
    return Container(
      decoration: BoxDecoration(
        color: _tabletSurface,
        border: Border.all(color: _tabletLine),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        name,
                        style: const TextStyle(
                          color: _tabletInk,
                          fontSize: 15,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        missionId,
                        style: const TextStyle(
                          color: _tabletMuted,
                          fontSize: 10,
                        ),
                      ),
                    ],
                  ),
                ),
                Text(
                  '${versions.length} Versions',
                  style: const TextStyle(color: _tabletMuted, fontSize: 10),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          for (var i = 0; i < versions.length; i++) ...[
            _MissionVersionV2(controller: controller, mission: versions[i]),
            if (i != versions.length - 1) const Divider(height: 1),
          ],
        ],
      ),
    );
  }
}

class _MissionVersionV2 extends StatelessWidget {
  const _MissionVersionV2({required this.controller, required this.mission});
  final JetsonController controller;
  final JsonMap mission;

  @override
  Widget build(BuildContext context) {
    final id = _asString(mission['mission_id']) ?? 'unknown';
    final version =
        _asInt(mission['mission_version'] ?? mission['version']) ?? 0;
    final active = mission['active'] == true;
    final verified =
        mission['verified'] == true ||
        mission['verification_status'] == 'verified' ||
        mission['status'] == 'verified';
    return InkWell(
      key: Key('edit-$id-v$version'),
      onTap: () async {
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => _MissionWorkflowPage(
              controller: controller,
              sourceMission: mission,
            ),
          ),
        );
      },
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            Container(
              width: 92,
              height: 58,
              decoration: BoxDecoration(
                color: const Color(0xffeff0f0),
                border: Border.all(color: _tabletLine),
                borderRadius: BorderRadius.circular(7),
              ),
              child: const Icon(Icons.map_outlined, color: _tabletMuted),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Version $version',
                    style: const TextStyle(
                      color: _tabletInk,
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '수정 시 v${version + 1} 이상 새 Version으로 저장',
                    style: const TextStyle(color: _tabletMuted, fontSize: 10),
                  ),
                ],
              ),
            ),
            _WorkflowStatusBadge(
              text: active ? 'ACTIVE' : (verified ? 'STORED · 검증됨' : 'STORED'),
              active: active,
            ),
            const SizedBox(width: 8),
            const Icon(Icons.chevron_right, color: _tabletMuted),
          ],
        ),
      ),
    );
  }
}

class _MissionWorkflowPage extends StatefulWidget {
  const _MissionWorkflowPage({required this.controller, this.sourceMission});
  final JetsonController controller;
  final JsonMap? sourceMission;
  bool get editing => sourceMission != null;

  @override
  State<_MissionWorkflowPage> createState() => _MissionWorkflowPageState();
}

class _MissionWorkflowPageState extends State<_MissionWorkflowPage> {
  final _missionName = TextEditingController(text: '현장 임무');
  final _missionId = TextEditingController();
  final _notes = TextEditingController();
  final _scale = TextEditingController();
  final _distance = TextEditingController(text: '1.0');

  int _step = 0;
  bool _busy = false;
  String? _error;
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

  @override
  void initState() {
    super.initState();
    if (widget.editing) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _loadExisting());
    }
  }

  @override
  void dispose() {
    for (final c in [_missionName, _missionId, _notes, _scale, _distance]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _loadExisting() async {
    final summary = widget.sourceMission!;
    final id = _asString(summary['mission_id']);
    final version = _asInt(summary['mission_version'] ?? summary['version']);
    if (id == null || version == null) return;
    setState(() => _busy = true);
    try {
      final detail = await widget.controller.backend.getMission(id, version);
      final manifest = _asMap(detail['manifest']) ?? detail;
      final transform = _asMap(manifest['coordinate_transform']) ?? const {};
      final map = _asMap(manifest['base_map']) ?? const {};
      final robot = _asMap(manifest['robot_start']) ?? const {};
      final origin =
          _asMap(transform['robot_start_image']) ??
          _asMap(transform['image_origin']);
      final rx = _asDouble(origin?['x'] ?? robot['image_x']);
      final ry = _asDouble(origin?['y'] ?? robot['image_y']);
      final rawEntrances = _asObjectList(manifest['entrances']);
      final imageEntrances = <Offset>[];
      for (final entrance in rawEntrances) {
        final x = _asDouble(entrance['image_x']);
        final y = _asDouble(entrance['image_y']);
        if (x != null && y != null) imageEntrances.add(Offset(x, y));
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
        _missionId.text = id;
        _missionName.text = _asString(manifest['mission_name']) ?? id;
        _notes.text = _asString(manifest['notes']) ?? '';
        _scale.text =
            (_asDouble(
              manifest['meters_per_pixel'] ?? transform['meters_per_pixel'],
            ))?.toStringAsPrecision(7) ??
            '';
        _mapBytes = bytes;
        _mapFilename =
            _asString(manifest['source_image_filename']) ??
            _asString(map['filename']) ??
            'base_map.png';
        _imageWidth = _asInt(manifest['base_map_width'] ?? map['width']) ?? 1;
        _imageHeight =
            _asInt(manifest['base_map_height'] ?? map['height']) ?? 1;
        _robotStart = (rx != null && ry != null) ? Offset(rx, ry) : null;
        _robotYaw =
            _asDouble(
              transform['initial_image_yaw'] ?? transform['rotation_radians'],
            ) ??
            0;
        _yawSpecified = _robotStart != null;
        _entrances
          ..clear()
          ..addAll(imageEntrances);
        _sourceVersion = version;
        _nextVersion = latest + 1;
        _imageChanged = false;
      });
    } on Object catch (e) {
      if (mounted) setState(() => _error = _message(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _pickMap() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['jpg', 'jpeg', 'png'],
      withData: true,
    );
    final file = result?.files.single;
    if (file == null || file.bytes == null) return;
    try {
      final codec = await ui.instantiateImageCodec(file.bytes!);
      final frame = await codec.getNextFrame();
      if (!mounted) return;
      setState(() {
        _mapBytes = file.bytes!;
        _mapFilename = file.name;
        _imageWidth = frame.image.width;
        _imageHeight = frame.image.height;
        _imageChanged = true;
        _robotStart = null;
        _yawSpecified = false;
        _entrances.clear();
        _scaleFirst = null;
        _scaleSecond = null;
        _error = null;
      });
    } on Object catch (e) {
      if (mounted) setState(() => _error = '이미지를 열 수 없습니다: ${_message(e)}');
    }
  }

  double? get _metersPerPixel {
    final value = double.tryParse(_scale.text.trim());
    return value != null && value.isFinite && value > 0 ? value : null;
  }

  void _calculateScale() {
    final a = _scaleFirst;
    final b = _scaleSecond;
    final meters = double.tryParse(_distance.text.trim());
    if (a == null || b == null || meters == null || meters <= 0) {
      setState(() => _error = '두 점과 실제 거리(m)를 입력하세요.');
      return;
    }
    final px = (b - a).distance;
    if (px <= 0) return;
    setState(() {
      _scale.text = (meters / px).toStringAsPrecision(7);
      _error = null;
    });
  }

  void _mapTap(Offset point) {
    setState(() {
      switch (_editMode) {
        case _MissionEditMode.robotStart:
          _robotStart = point;
          _yawSpecified = true;
        case _MissionEditMode.scaleFirst:
          _scaleFirst = point;
          _scaleSecond = null;
          _editMode = _MissionEditMode.scaleSecond;
        case _MissionEditMode.scaleSecond:
          _scaleSecond = point;
        case _MissionEditMode.entrance:
          _entrances.add(point);
      }
    });
  }

  bool _validateStep() {
    setState(() => _error = null);
    if (_step == 0 && (_mapBytes == null || _mapFilename == null)) {
      setState(() => _error = 'JPG/PNG 구조도를 선택하세요.');
      return false;
    }
    if (_step == 1 && _missionName.text.trim().isEmpty) {
      setState(() => _error = 'Mission ??? ?????.');
      return false;
    }
    if (_step == 2 &&
        (_robotStart == null ||
            !_yawSpecified ||
            _metersPerPixel == null ||
            _entrances.isEmpty)) {
      setState(() => _error = 'Robot 위치/방향, 축척, 출입구를 모두 지정하세요.');
      return false;
    }
    return true;
  }

  void _next() {
    if (!_validateStep()) return;
    setState(() => _step = math.min(3, _step + 1));
  }

  Future<void> _save() async {
    if (!_validateStep()) return;
    final map = _mapBytes;
    final start = _robotStart;
    final scale = _metersPerPixel;
    if (map == null || start == null || scale == null || _mapFilename == null) {
      return;
    }
    final draft = <String, Object?>{
      if (_missionId.text.trim().isNotEmpty)
        'mission_id': _missionId.text.trim(),
      'mission_name': _missionName.text.trim(),
      'meters_per_pixel': scale,
      'robot_start_image': {'x': start.dx, 'y': start.dy},
      'initial_yaw': _robotYaw,
      'entrances': [
        for (final point in _entrances) {'x': point.dx, 'y': point.dy},
      ],
      'notes': _notes.text,
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
          _missionId.text;
      final version =
          _asInt(stored['mission_version']) ??
          _asInt(_asMap(stored['manifest'])?['mission_version']) ??
          _nextVersion ??
          1;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$id · v$version 저장 완료 (STORED)')));
      Navigator.of(context).pop();
    } on Object catch (e) {
      if (mounted) setState(() => _error = _message(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final title = widget.editing ? 'Mission 수정' : '새 Mission 만들기';
    return Scaffold(
      backgroundColor: _tabletBackground,
      appBar: AppBar(
        title: Text(title),
        actions: [
          if (widget.editing && _nextVersion != null)
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Center(
                child: _WorkflowStatusBadge(
                  text: '저장 시 v$_nextVersion 생성',
                  active: false,
                ),
              ),
            ),
        ],
      ),
      body: Stack(
        children: [
          Positioned.fill(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1320),
                child: ListView(
                  padding: const EdgeInsets.all(22),
                  children: [
                    _WorkflowStepper(step: _step, editing: widget.editing),
                    const SizedBox(height: 16),
                    if (_error != null) ...[
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: const Color(0xffffeeee),
                          border: Border.all(color: const Color(0xffe9bbbb)),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          _error!,
                          style: const TextStyle(color: _tabletRed),
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    if (_step == 0) _mapStep(),
                    if (_step == 1) _infoStep(),
                    if (_step == 2) _configStep(),
                    if (_step == 3) _reviewStep(),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        if (_step > 0)
                          OutlinedButton(
                            onPressed: _busy
                                ? null
                                : () => setState(() => _step--),
                            child: const Text('← 이전'),
                          ),
                        const Spacer(),
                        if (_step < 3)
                          FilledButton(
                            onPressed: _busy ? null : _next,
                            child: const Text('다음 →'),
                          )
                        else
                          FilledButton.icon(
                            key: const Key('store-tablet-mission'),
                            onPressed: _busy ? null : _save,
                            icon: const Icon(Icons.cloud_upload_outlined),
                            label: Text(
                              widget.editing
                                  ? '새 버전으로 저장'
                                  : 'Jetson에 Mission 저장',
                            ),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
          if (_busy)
            const Positioned.fill(
              child: ColoredBox(
                color: Color(0x55000000),
                child: Center(child: CircularProgressIndicator()),
              ),
            ),
        ],
      ),
    );
  }

  Widget _mapStep() => _WorkflowPanel(
    title: '1. 구조도 선택',
    subtitle: widget.editing && !_imageChanged
        ? '현재 구조도를 유지하면 기존 원본과 OpenCV 전처리 결과를 재사용합니다.'
        : 'JPG/JPEG/PNG 원본은 Jetson에 그대로 보존됩니다.',
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 330,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                height: 210,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: _tabletSurfaceMuted,
                  border: Border.all(color: _tabletLine),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const Icon(
                      Icons.image_outlined,
                      size: 46,
                      color: _tabletMuted,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      _mapFilename ?? '구조도 미선택',
                      textAlign: TextAlign.center,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      _mapBytes == null
                          ? 'JPG / JPEG / PNG'
                          : '$_imageWidth × $_imageHeight',
                      style: const TextStyle(color: _tabletMuted, fontSize: 11),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 10),
              FilledButton.icon(
                key: const Key('tablet-pick-map'),
                onPressed: _busy ? null : _pickMap,
                icon: const Icon(Icons.photo_library_outlined),
                label: Text(_mapBytes == null ? '파일 선택' : '사진 변경'),
              ),
            ],
          ),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Container(
            height: 330,
            decoration: BoxDecoration(
              color: const Color(0xffe3e5e7),
              border: Border.all(color: _tabletLine),
              borderRadius: BorderRadius.circular(10),
            ),
            clipBehavior: Clip.antiAlias,
            child: _mapBytes == null
                ? const Center(
                    child: Text(
                      'ORIGINAL PREVIEW',
                      style: TextStyle(
                        color: _tabletMuted,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  )
                : Image.memory(_mapBytes!, fit: BoxFit.contain),
          ),
        ),
      ],
    ),
  );

  Widget _infoStep() => _WorkflowPanel(
    title: '2. Mission 기본 정보',
    subtitle: widget.editing
        ? 'Mission ID는 유지하고 나머지 정보를 수정할 수 있습니다.'
        : '현장과 구조 인력이 식별하기 쉬운 정보를 입력합니다.',
    child: Column(
      children: [
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _missionName,
                decoration: const InputDecoration(labelText: 'Mission 이름'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                controller: _missionId,
                readOnly: widget.editing,
                decoration: InputDecoration(
                  labelText: 'Mission ID',
                  hintText: widget.editing ? null : '비워두면 자동 생성',
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _notes,
          maxLines: 3,
          decoration: const InputDecoration(labelText: '현장 메모'),
        ),
      ],
    ),
  );

  Widget _configStep() => _WorkflowPanel(
    title: '3. 지도 설정',
    subtitle: 'Robot 시작 위치/방향, 출입구, 축척을 구조도 위에서 지정합니다.',
    child: LayoutBuilder(
      builder: (context, constraints) {
        final map = _mapBytes == null
            ? const Center(child: Text('구조도를 먼저 선택하세요.'))
            : _MissionImageEditor(
                bytes: _mapBytes!,
                imageWidth: _imageWidth,
                imageHeight: _imageHeight,
                editMode: _editMode,
                robotStart: _robotStart,
                robotYaw: _robotYaw,
                scaleFirst: _scaleFirst,
                scaleSecond: _scaleSecond,
                entrances: _entrances,
                onTap: _mapTap,
                onRobotDragStart: (point) {
                  _dragStart = point;
                  setState(() {
                    _robotStart = point;
                    _yawSpecified = true;
                  });
                },
                onRobotDragUpdate: (point) {
                  final start = _dragStart;
                  if (start == null) return;
                  setState(() {
                    _robotStart = start;
                    _robotYaw = math.atan2(
                      point.dy - start.dy,
                      point.dx - start.dx,
                    );
                    _yawSpecified = true;
                  });
                },
                onRobotDragEnd: () => _dragStart = null,
              );
        final settings = Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                _WorkflowTool(
                  label: 'Robot 위치/방향',
                  selected: _editMode == _MissionEditMode.robotStart,
                  onTap: () =>
                      setState(() => _editMode = _MissionEditMode.robotStart),
                ),
                _WorkflowTool(
                  label: '출입구 추가',
                  selected: _editMode == _MissionEditMode.entrance,
                  onTap: () =>
                      setState(() => _editMode = _MissionEditMode.entrance),
                ),
                _WorkflowTool(
                  label: '두 점 측정',
                  selected:
                      _editMode == _MissionEditMode.scaleFirst ||
                      _editMode == _MissionEditMode.scaleSecond,
                  onTap: () => setState(() {
                    _scaleFirst = null;
                    _scaleSecond = null;
                    _editMode = _MissionEditMode.scaleFirst;
                  }),
                ),
              ],
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _scale,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
              decoration: const InputDecoration(
                labelText: '축척 (m/pixel)',
                helperText: '직접 입력하거나 아래 두 점 거리로 계산',
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _distance,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: const InputDecoration(
                      labelText: '두 점 실제 거리 (m)',
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton.tonal(
                  onPressed: _scaleFirst != null && _scaleSecond != null
                      ? _calculateScale
                      : null,
                  child: const Text('계산'),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              'Yaw ${(_robotYaw * 180 / math.pi).toStringAsFixed(1)}°',
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            Slider(
              min: -math.pi,
              max: math.pi,
              value: _robotYaw.clamp(-math.pi, math.pi),
              onChanged: (value) => setState(() {
                _robotYaw = value;
                _yawSpecified = true;
              }),
            ),
            const Divider(),
            _WorkflowSummary(
              label: 'Robot',
              value: _robotStart == null
                  ? '미지정'
                  : '(${_robotStart!.dx.toStringAsFixed(0)}, ${_robotStart!.dy.toStringAsFixed(0)})',
            ),
            _WorkflowSummary(label: '출입구', value: '${_entrances.length}개'),
            _WorkflowSummary(
              label: 'Scale',
              value: _metersPerPixel == null
                  ? '미지정'
                  : '${_metersPerPixel!.toStringAsPrecision(5)} m/px',
            ),
            const SizedBox(height: 6),
            OutlinedButton.icon(
              onPressed: _entrances.isEmpty
                  ? null
                  : () => setState(_entrances.clear),
              icon: const Icon(Icons.delete_outline),
              label: const Text('출입구 초기화'),
            ),
          ],
        );
        if (constraints.maxWidth < 900) {
          return Column(
            children: [
              SizedBox(height: 420, child: map),
              const SizedBox(height: 12),
              settings,
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: SizedBox(height: 500, child: map)),
            const SizedBox(width: 16),
            SizedBox(width: 330, child: settings),
          ],
        );
      },
    ),
  );

  Widget _reviewStep() => _WorkflowPanel(
    title: '4. 확인 및 저장',
    subtitle: '저장 후 상태는 STORED이며 ACTIVE Mission은 자동으로 바뀌지 않습니다.',
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _WorkflowSummary(
          label: 'Mission',
          value: _missionName.text.trim().isEmpty
              ? '-'
              : _missionName.text.trim(),
        ),
        _WorkflowSummary(
          label: 'Mission ID',
          value: _missionId.text.trim().isEmpty
              ? '자동 생성 예정'
              : _missionId.text.trim(),
        ),
        _WorkflowSummary(
          label: '저장 Version',
          value: widget.editing
              ? 'v${_nextVersion ?? '-'} (기존 v$_sourceVersion 보존)'
              : 'v1',
        ),
        _WorkflowSummary(
          label: '구조도',
          value: '${_mapFilename ?? '-'} · $_imageWidth × $_imageHeight',
        ),
        _WorkflowSummary(
          label: 'Robot',
          value: _robotStart == null
              ? '미지정'
              : 'x ${_robotStart!.dx.toStringAsFixed(0)} · y ${_robotStart!.dy.toStringAsFixed(0)} · ${(_robotYaw * 180 / math.pi).toStringAsFixed(1)}°',
        ),
        _WorkflowSummary(
          label: '출입구 / 축척',
          value:
              '${_entrances.length}개 · ${_metersPerPixel?.toStringAsPrecision(5) ?? '-'} m/px',
        ),
        const SizedBox(height: 14),
        Container(
          padding: const EdgeInsets.all(13),
          decoration: BoxDecoration(
            color: _tabletYellowSoft,
            border: Border.all(color: const Color(0xffe1c884)),
            borderRadius: BorderRadius.circular(8),
          ),
          child: const Text(
            '저장과 ACTIVE 전환은 별도입니다. Jetson은 원본 구조도를 보존하고 base_map_display.png / wall_mask.png / processing.json을 생성합니다.',
            style: TextStyle(
              color: Color(0xff6a4b00),
              fontSize: 11,
              height: 1.5,
            ),
          ),
        ),
      ],
    ),
  );
}

class _WorkflowStepper extends StatelessWidget {
  const _WorkflowStepper({required this.step, required this.editing});
  final int step;
  final bool editing;
  @override
  Widget build(BuildContext context) {
    const labels = ['구조도', '기본 정보', '지도 설정', '확인·저장'];
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _tabletSurface,
        border: Border.all(color: _tabletLine),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              editing ? 'Mission 수정 · 새 Version 생성' : '새 Mission 만들기',
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
          ),
          for (var i = 0; i < labels.length; i++) ...[
            _StepBadge(
              number: i + 1,
              label: labels[i],
              active: i == step,
              done: i < step,
            ),
            if (i != labels.length - 1)
              Container(width: 22, height: 1, color: _tabletLine),
          ],
        ],
      ),
    );
  }
}

class _StepBadge extends StatelessWidget {
  const _StepBadge({
    required this.number,
    required this.label,
    required this.active,
    required this.done,
  });
  final int number;
  final String label;
  final bool active;
  final bool done;
  @override
  Widget build(BuildContext context) => Row(
    children: [
      Container(
        width: 27,
        height: 27,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: active
              ? _tabletDark
              : (done ? _tabletGreenSoft : _tabletSurface),
          shape: BoxShape.circle,
          border: Border.all(
            color: active
                ? _tabletDark
                : (done ? _tabletGreen : _tabletLineStrong),
          ),
        ),
        child: Text(
          done ? '✓' : '$number',
          style: TextStyle(
            color: active ? Colors.white : (done ? _tabletGreen : _tabletMuted),
            fontSize: 10,
            fontWeight: FontWeight.w900,
          ),
        ),
      ),
      const SizedBox(width: 6),
      Text(
        label,
        style: TextStyle(
          color: active ? _tabletInk : (done ? _tabletGreen : _tabletMuted),
          fontSize: 10,
          fontWeight: FontWeight.w800,
        ),
      ),
    ],
  );
}

class _WorkflowPanel extends StatelessWidget {
  const _WorkflowPanel({
    required this.title,
    required this.subtitle,
    required this.child,
  });
  final String title;
  final String subtitle;
  final Widget child;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: _tabletSurface,
      border: Border.all(color: _tabletLine),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          title,
          style: const TextStyle(
            color: _tabletInk,
            fontSize: 16,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          subtitle,
          style: const TextStyle(color: _tabletMuted, fontSize: 11),
        ),
        const SizedBox(height: 18),
        child,
      ],
    ),
  );
}

class _WorkflowTool extends StatelessWidget {
  const _WorkflowTool({
    required this.label,
    required this.selected,
    required this.onTap,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => ChoiceChip(
    label: Text(label, style: const TextStyle(fontSize: 10)),
    selected: selected,
    onSelected: (_) => onTap(),
  );
}

class _WorkflowSummary extends StatelessWidget {
  const _WorkflowSummary({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Container(
    constraints: const BoxConstraints(minHeight: 40),
    decoration: const BoxDecoration(
      border: Border(bottom: BorderSide(color: Color(0xffedf0f2))),
    ),
    child: Row(
      children: [
        SizedBox(
          width: 150,
          child: Text(
            label,
            style: const TextStyle(color: _tabletMuted, fontSize: 10),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(
              color: _tabletInk,
              fontSize: 10,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
      ],
    ),
  );
}

class _WorkflowStatusBadge extends StatelessWidget {
  const _WorkflowStatusBadge({required this.text, required this.active});
  final String text;
  final bool active;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
    decoration: BoxDecoration(
      color: active ? _tabletGreenSoft : _tabletSurfaceMuted,
      border: Border.all(color: active ? const Color(0xffb8ddca) : _tabletLine),
      borderRadius: BorderRadius.circular(999),
    ),
    child: Text(
      text,
      style: TextStyle(
        color: active ? _tabletGreen : _tabletMuted,
        fontSize: 9,
        fontWeight: FontWeight.w900,
      ),
    ),
  );
}
