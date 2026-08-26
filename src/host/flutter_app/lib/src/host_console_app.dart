import 'dart:async';

import 'package:flutter/material.dart';

import 'command_review_workspace.dart';
import 'host_controller.dart';

const _bg = Color(0xffeceff1);
const _surface = Color(0xffffffff);
const _ink = Color(0xff141719);
const _muted = Color(0xff68717a);
const _line = Color(0xffd7dce0);
const _dark = Color(0xff171a1d);
const _green = Color(0xff1b8a5a);
const _greenSoft = Color(0xffe7f4ed);
const _yellow = Color(0xffb87a00);
const _red = Color(0xffc73737);
const _redSoft = Color(0xfffbeaea);
const _orange = Color(0xffd56b1f);
const _blue = Color(0xff1677a8);

final class RescueHostConsoleApp extends StatefulWidget {
  const RescueHostConsoleApp({super.key, required this.controller});
  final HostController controller;

  @override
  State<RescueHostConsoleApp> createState() => _RescueHostConsoleAppState();
}

class _RescueHostConsoleAppState extends State<RescueHostConsoleApp> {
  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_changed);
    widget.controller.initialise();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    widget.controller.removeListener(_changed);
    widget.controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'AI Rescue Box · Host',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.light,
          scaffoldBackgroundColor: _bg,
          colorScheme: ColorScheme.fromSeed(
            seedColor: _dark,
            brightness: Brightness.light,
            primary: _dark,
            secondary: _blue,
            surface: _surface,
            error: _red,
          ),
          cardTheme: const CardThemeData(
            elevation: 0,
            color: _surface,
            margin: EdgeInsets.zero,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.all(Radius.circular(10)),
              side: BorderSide(color: _line),
            ),
          ),
          useMaterial3: true,
        ),
        home: _HostShell(controller: widget.controller),
      );
}

class _HostShell extends StatefulWidget {
  const _HostShell({required this.controller});
  final HostController controller;

  @override
  State<_HostShell> createState() => _HostShellState();
}

class _HostShellState extends State<_HostShell> {
  int _page = 0;
  int _seenSequence = 0;
  bool _syncing = false;

  @override
  void initState() {
    super.initState();
    _seenSequence = widget.controller.lastEventSequence;
    widget.controller.addListener(_eventChanged);
    WidgetsBinding.instance.addPostFrameCallback((_) => unawaited(_syncActiveMission()));
  }

  @override
  void dispose() {
    widget.controller.removeListener(_eventChanged);
    super.dispose();
  }

  void _eventChanged() {
    if (widget.controller.lastEventSequence <= _seenSequence) return;
    _seenSequence = widget.controller.lastEventSequence;
    unawaited(_syncActiveMission());
  }

  Future<void> _syncActiveMission() async {
    if (_syncing) return;
    _syncing = true;
    try {
      final status = await widget.controller.backend.status();
      widget.controller.backendStatus = status;
      final raw = status['active_mission'];
      if (raw is! Map) return;
      final active = Map<String, dynamic>.from(raw);
      final id = active['mission_id']?.toString();
      final version = (active['mission_version'] as num?)?.toInt();
      if (id == null || id.isEmpty || version == null || version < 1) return;
      if (widget.controller.missionId != id ||
          widget.controller.missionVersion != version ||
          widget.controller.currentMission == null ||
          widget.controller.mapBytes == null) {
        final manifest = await widget.controller.backend.getMission(id, version);
        await widget.controller.hydrateActiveMission(manifest);
      }
      await widget.controller.refreshResults();
    } on Object {
      // Keep the last valid console state while the field link is unavailable.
    } finally {
      _syncing = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    return Scaffold(
      body: Row(
        children: [
          SizedBox(
            width: 220,
            child: _Sidebar(
              selected: _page,
              controller: c,
              onSelect: (value) => setState(() => _page = value),
            ),
          ),
          Expanded(
            child: Column(
              children: [
                _TopBar(controller: c),
                if (c.busy) const LinearProgressIndicator(minHeight: 2),
                if (c.error != null)
                  MaterialBanner(
                    backgroundColor: _redSoft,
                    content: Text(c.error!, style: const TextStyle(color: _red)),
                    actions: [TextButton(onPressed: c.clearError, child: const Text('확인'))],
                  ),
                Expanded(
                  child: IndexedStack(
                    index: _page,
                    children: [
                      _MonitorPage(controller: c, openReview: () => setState(() => _page = 1)),
                      CommandReviewWorkspace(controller: c),
                      _EventPage(controller: c),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({required this.selected, required this.controller, required this.onSelect});
  final int selected;
  final HostController controller;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) => ColoredBox(
        color: _dark,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              height: 76,
              padding: const EdgeInsets.symmetric(horizontal: 18),
              decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xff303438)))),
              child: const Row(
                children: [
                  _BrandMark(),
                  SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'AI Rescue Box · Host',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w800),
                        ),
                        SizedBox(height: 3),
                        Text(
                          'COMMAND CENTER',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: Color(0xff8f989f), fontSize: 9, letterSpacing: 1.1),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const Padding(
              padding: EdgeInsets.fromLTRB(18, 22, 18, 9),
              child: Text('OPERATIONS', style: TextStyle(color: Color(0xff7f888f), fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: 1.4)),
            ),
            for (final item in const [
              ('관제', Icons.dashboard_outlined),
              ('분석·검토', Icons.my_location_outlined),
              ('상태·이벤트', Icons.list_alt_outlined),
            ].indexed)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                child: Material(
                  color: selected == item.$1 ? const Color(0xff2a2f33) : Colors.transparent,
                  borderRadius: BorderRadius.circular(8),
                  child: ListTile(
                    onTap: () => onSelect(item.$1),
                    leading: Icon(item.$2.$2, color: selected == item.$1 ? Colors.white : const Color(0xffaeb5bb)),
                    title: Text(item.$2.$1, style: TextStyle(color: selected == item.$1 ? Colors.white : const Color(0xffaeb5bb), fontSize: 12, fontWeight: FontWeight.w700)),
                    dense: true,
                  ),
                ),
              ),
            const Spacer(),
            Padding(
              padding: const EdgeInsets.all(14),
              child: Container(
                padding: const EdgeInsets.all(11),
                decoration: BoxDecoration(color: const Color(0xff1d2124), border: Border.all(color: const Color(0xff343b40)), borderRadius: BorderRadius.circular(8)),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      const Expanded(child: Text('UWB BRIDGE', style: TextStyle(color: Color(0xff8f989f), fontSize: 8))),
                      Container(width: 8, height: 8, decoration: BoxDecoration(color: _bridgeGood(controller.bridgeStatus) ? _green : _yellow, shape: BoxShape.circle)),
                    ]),
                    const SizedBox(height: 7),
                    Text(_bridgeLabel(controller.bridgeStatus), style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w700)),
                  ],
                ),
              ),
            ),
          ],
        ),
      );
}

class _BrandMark extends StatelessWidget {
  const _BrandMark();
  @override
  Widget build(BuildContext context) => Container(
        width: 36,
        height: 36,
        alignment: Alignment.center,
        decoration: BoxDecoration(border: Border.all(color: Colors.white, width: 2), borderRadius: BorderRadius.circular(8)),
        child: const Text('ARB', style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w900)),
      );
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final active = controller.missionId.isNotEmpty;
    return Container(
      height: 62,
      padding: const EdgeInsets.symmetric(horizontal: 22),
      decoration: const BoxDecoration(color: _surface, border: Border(bottom: BorderSide(color: _line))),
      child: Row(
        children: [
          const Text('ACTIVE MISSION', style: TextStyle(color: _muted, fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: 1.2)),
          const SizedBox(width: 12),
          Expanded(
            child: Text(active ? '${controller.missionName} · v${controller.missionVersion}' : 'Mission 대기', style: const TextStyle(color: _ink, fontSize: 12, fontWeight: FontWeight.w800)),
          ),
          if (active) const _Badge(text: 'ACTIVE', color: _green, background: _greenSoft),
          const SizedBox(width: 18),
          _TopStatus(label: 'UWB', good: _bridgeGood(controller.bridgeStatus)),
          const SizedBox(width: 14),
          _TopStatus(label: controller.webSocketState, good: controller.webSocketState.contains('연결')),
          const SizedBox(width: 10),
          IconButton(onPressed: controller.busy ? null : controller.refreshStatus, icon: const Icon(Icons.refresh, size: 19)),
        ],
      ),
    );
  }
}

class _TopStatus extends StatelessWidget {
  const _TopStatus({required this.label, required this.good});
  final String label;
  final bool good;
  @override
  Widget build(BuildContext context) => Row(children: [
        Container(width: 7, height: 7, decoration: BoxDecoration(color: good ? _green : _yellow, shape: BoxShape.circle)),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(color: _muted, fontSize: 9)),
      ]);
}

class _MonitorPage extends StatelessWidget {
  const _MonitorPage({required this.controller, required this.openReview});
  final HostController controller;
  final VoidCallback openReview;

  @override
  Widget build(BuildContext context) {
    final semantic = controller.reviewedSemantic;
    final victimCount = _list(semantic, 'victim_candidates').length + _list(semantic, 'confirmed_victims').length;
    final confirmed = _list(semantic, 'confirmed_victims').length;
    final risks = _list(semantic, 'risk_zones');
    final routes = _list(semantic, 'entry_routes');
    return ListView(
      padding: const EdgeInsets.fromLTRB(24, 22, 24, 28),
      children: [
        const Text('COMMAND OVERVIEW', style: TextStyle(color: _muted, fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: 1.2)),
        const SizedBox(height: 5),
        const Text('관제', style: TextStyle(color: _ink, fontSize: 24, fontWeight: FontWeight.w800)),
        const SizedBox(height: 4),
        const Text('현재 ACTIVE Mission과 구조 진행 상태를 한눈에 확인합니다.', style: TextStyle(color: _muted, fontSize: 11)),
        const SizedBox(height: 16),
        _ActiveBanner(controller: controller),
        const SizedBox(height: 12),
        _StatusRibbon(controller: controller),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(child: _Metric(label: '탐지 요구조자', value: '$victimCount', unit: '명')),
            Expanded(child: _Metric(label: '확인 요구조자', value: '$confirmed', unit: '명')),
            Expanded(child: _Metric(label: '위험지역', value: '${risks.length}', unit: '곳')),
            Expanded(child: _Metric(label: '생성 경로', value: '${routes.length}', unit: '개')),
          ],
        ),
        const SizedBox(height: 12),
        LayoutBuilder(builder: (context, constraints) {
          final main = Card(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('현재 구조 상황', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 4),
                  const Text('Host는 prior-map 이미지를 UWB로 받지 않고 Mission 메타데이터와 semantic/SLAM 결과를 관제합니다.', style: TextStyle(color: _muted, fontSize: 9, height: 1.4)),
                  const SizedBox(height: 14),
                  _SituationList(semantic: semantic),
                ],
              ),
            ),
          );
          final side = Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('계획 Version', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 12),
                  _VersionBox(label: 'CURRENT RESULT', value: controller.currentResultVersion > 0 ? 'Semantic v${controller.currentResultVersion}' : '대기'),
                  const SizedBox(height: 8),
                  _VersionBox(label: 'APPROVED PLAN', value: controller.latestApprovedPlanVersion > 0 ? 'Plan v${controller.latestApprovedPlanVersion}' : '없음'),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: openReview, child: const Text('분석·검토 열기')),
                ],
              ),
            ),
          );
          if (constraints.maxWidth < 900) return Column(children: [main, const SizedBox(height: 12), side]);
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [Expanded(child: main), const SizedBox(width: 12), SizedBox(width: 330, child: side)]);
        }),
      ],
    );
  }
}

class _ActiveBanner extends StatelessWidget {
  const _ActiveBanner({required this.controller});
  final HostController controller;
  @override
  Widget build(BuildContext context) {
    final active = controller.missionId.isNotEmpty;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 19, vertical: 17),
      decoration: BoxDecoration(color: _dark, borderRadius: BorderRadius.circular(10)),
      child: Row(children: [
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('CURRENT ACTIVE MISSION', style: TextStyle(color: Color(0xffa8b0b7), fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: 1.2)),
          const SizedBox(height: 6),
          Text(active ? '${controller.missionName} · Version ${controller.missionVersion}' : 'ACTIVE Mission 대기', style: const TextStyle(color: Colors.white, fontSize: 19, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          Text(active ? '${controller.missionId} · Mission 생성/변경은 Tablet에서 수행' : 'Tablet에서 ACTIVE Mission을 선택하면 동기화됩니다.', style: const TextStyle(color: Color(0xffb8c0c6), fontSize: 9)),
        ])),
        if (active) const _Badge(text: '● ACTIVE', color: Color(0xff8be0b2), background: Color(0xff1d3328)),
      ]),
    );
  }
}

class _StatusRibbon extends StatelessWidget {
  const _StatusRibbon({required this.controller});
  final HostController controller;
  @override
  Widget build(BuildContext context) {
    final items = [
      ('UWB', _bridgeLabel(controller.bridgeStatus), _bridgeGood(controller.bridgeStatus)),
      ('MISSION', controller.missionId.isEmpty ? 'Waiting' : 'v${controller.missionVersion}', controller.missionId.isNotEmpty),
      ('RESULT', controller.currentResultVersion > 0 ? 'v${controller.currentResultVersion}' : 'Waiting', controller.currentResultVersion > 0),
      ('PREVIEW', controller.previewVersion > 0 ? 'v${controller.previewVersion}' : 'Waiting', controller.previewVersion > 0),
      ('PLAN', controller.latestApprovedPlanVersion > 0 ? 'v${controller.latestApprovedPlanVersion}' : 'Waiting', controller.latestApprovedPlanVersion > 0),
      ('WEBSOCKET', controller.webSocketState, controller.webSocketState.contains('연결')),
    ];
    return Card(child: Row(children: [
      for (var index = 0; index < items.length; index++) ...[
        Expanded(child: Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [Expanded(child: Text(items[index].$1, style: const TextStyle(color: _muted, fontSize: 8))), Container(width: 7, height: 7, decoration: BoxDecoration(color: items[index].$3 ? _green : _yellow, shape: BoxShape.circle))]),
          const SizedBox(height: 5),
          Text(items[index].$2, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800)),
        ]))),
        if (index != items.length - 1) Container(width: 1, height: 48, color: _line),
      ]
    ]));
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value, required this.unit});
  final String label;
  final String value;
  final String unit;
  @override
  Widget build(BuildContext context) => Card(child: Padding(padding: const EdgeInsets.all(14), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: const TextStyle(color: _muted, fontSize: 9)),
        const SizedBox(height: 4),
        Text('$value $unit', style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800)),
      ])));
}

class _SituationList extends StatelessWidget {
  const _SituationList({required this.semantic});
  final Map<String, dynamic> semantic;
  @override
  Widget build(BuildContext context) {
    final victims = [..._list(semantic, 'confirmed_victims'), ..._list(semantic, 'victim_candidates')];
    final risks = _list(semantic, 'risk_zones');
    final routes = _list(semantic, 'entry_routes');
    if (victims.isEmpty && risks.isEmpty && routes.isEmpty) return const Padding(padding: EdgeInsets.all(18), child: Text('분석 결과 대기', style: TextStyle(color: _muted)));
    return Column(children: [
      for (var i = 0; i < victims.take(4).length; i++) _SituationRow(color: _red, label: _entityId(victims[i], i, 'Victim'), value: victims[i]['host_status']?.toString() ?? 'candidate'),
      for (var i = 0; i < risks.take(3).length; i++) _SituationRow(color: _orange, label: _entityId(risks[i], i, 'Risk'), value: risks[i]['risk_type']?.toString() ?? 'risk'),
      for (var i = 0; i < routes.take(3).length; i++) _SituationRow(color: _blue, label: _entityId(routes[i], i, 'Route'), value: routes[i]['host_status']?.toString() ?? 'generated'),
    ]);
  }
}

class _SituationRow extends StatelessWidget {
  const _SituationRow({required this.color, required this.label, required this.value});
  final Color color;
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Container(
        constraints: const BoxConstraints(minHeight: 36),
        decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xffedf0f2)))),
        child: Row(children: [
          Container(width: 8, height: 8, decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(2))),
          const SizedBox(width: 8),
          Expanded(child: Text(label, style: const TextStyle(fontSize: 9))),
          Text(value, style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w800)),
        ]),
      );
}

class _VersionBox extends StatelessWidget {
  const _VersionBox({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: const Color(0xfff5f6f7), border: Border.all(color: _line), borderRadius: BorderRadius.circular(7)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(color: _muted, fontSize: 8)),
          const SizedBox(height: 4),
          Text(value, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800)),
        ]),
      );
}

class _EventPage extends StatefulWidget {
  const _EventPage({required this.controller});
  final HostController controller;
  @override
  State<_EventPage> createState() => _EventPageState();
}

class _EventPageState extends State<_EventPage> {
  String _filter = '전체';
  @override
  Widget build(BuildContext context) {
    final events = widget.controller.eventLog.where((item) => _filter == '전체' || _eventCategory(item) == _filter).toList();
    return ListView(
      padding: const EdgeInsets.fromLTRB(24, 22, 24, 28),
      children: [
        const Text('SYSTEM HEALTH & TIMELINE', style: TextStyle(color: _muted, fontSize: 9, fontWeight: FontWeight.w900, letterSpacing: 1.2)),
        const SizedBox(height: 5),
        const Text('상태·이벤트', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
        const SizedBox(height: 4),
        const Text('통신 로그를 개발자 콘솔이 아닌 운영 사건 단위로 확인합니다.', style: TextStyle(color: _muted, fontSize: 11)),
        const SizedBox(height: 16),
        _ServiceTable(controller: widget.controller),
        const SizedBox(height: 12),
        Card(child: Column(children: [
          Padding(
            padding: const EdgeInsets.all(13),
            child: Row(children: [
              const Expanded(child: Text('최근 이벤트', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800))),
              for (final name in const ['전체', 'Mission', '탐지', '통신', '오류'])
                Padding(
                  padding: const EdgeInsets.only(left: 5),
                  child: ChoiceChip(label: Text(name, style: const TextStyle(fontSize: 8)), selected: _filter == name, onSelected: (_) => setState(() => _filter = name)),
                ),
            ]),
          ),
          const Divider(height: 1),
          if (events.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Text('표시할 이벤트가 없습니다.', style: TextStyle(color: _muted))) else
            for (final event in events.take(30)) _EventRow(event: event),
        ])),
      ],
    );
  }
}

class _ServiceTable extends StatelessWidget {
  const _ServiceTable({required this.controller});
  final HostController controller;
  @override
  Widget build(BuildContext context) {
    final rows = [
      ('Host API', controller.health['ok'] == true ? '정상' : '대기', controller.health['ok'] == true),
      ('UWB Bridge', _bridgeLabel(controller.bridgeStatus), _bridgeGood(controller.bridgeStatus)),
      ('ACTIVE Mission', controller.missionId.isEmpty ? '대기' : '${controller.missionId} v${controller.missionVersion}', controller.missionId.isNotEmpty),
      ('WebSocket', controller.webSocketState, controller.webSocketState.contains('연결')),
      ('Approved Plan', controller.latestApprovedPlanVersion > 0 ? 'v${controller.latestApprovedPlanVersion}' : '대기', controller.latestApprovedPlanVersion > 0),
    ];
    return Card(child: Column(children: [
      const Padding(padding: EdgeInsets.all(14), child: Align(alignment: Alignment.centerLeft, child: Text('서비스 상태', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800)))),
      const Divider(height: 1),
      for (final row in rows) Container(
        constraints: const BoxConstraints(minHeight: 52),
        padding: const EdgeInsets.symmetric(horizontal: 15),
        decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xffedf0f2)))),
        child: Row(children: [
          Expanded(child: Text(row.$1, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700))),
          Container(width: 7, height: 7, decoration: BoxDecoration(color: row.$3 ? _green : _yellow, shape: BoxShape.circle)),
          const SizedBox(width: 7),
          SizedBox(width: 190, child: Text(row.$2, textAlign: TextAlign.right, overflow: TextOverflow.ellipsis, style: const TextStyle(color: _muted, fontSize: 9))),
        ]),
      ),
    ]));
  }
}

class _EventRow extends StatelessWidget {
  const _EventRow({required this.event});
  final String event;
  @override
  Widget build(BuildContext context) {
    final category = _eventCategory(event);
    final color = switch (category) { '오류' => _red, '탐지' => _orange, 'Mission' => _green, _ => _blue };
    return Container(
      constraints: const BoxConstraints(minHeight: 58),
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 9),
      decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: Color(0xffedf0f2)))),
      child: Row(children: [
        Container(width: 30, height: 30, alignment: Alignment.center, decoration: BoxDecoration(color: color.withValues(alpha: .12), borderRadius: BorderRadius.circular(7)), child: Icon(Icons.circle, size: 9, color: color)),
        const SizedBox(width: 10),
        Expanded(child: Text(_humanEvent(event), style: const TextStyle(fontSize: 9, height: 1.4))),
        Text(category, style: const TextStyle(color: _muted, fontSize: 8)),
      ]),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.text, required this.color, required this.background});
  final String text;
  final Color color;
  final Color background;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
        decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(999)),
        child: Text(text, style: TextStyle(color: color, fontSize: 9, fontWeight: FontWeight.w900)),
      );
}

List<Map<String, dynamic>> _list(Map<String, dynamic> value, String key) =>
    (value[key] is List)
        ? (value[key] as List).whereType<Map>().map((item) => Map<String, dynamic>.from(item)).toList()
        : const [];

String _entityId(Map<String, dynamic> item, int index, String fallback) {
  for (final key in const ['detection_id', 'victim_id', 'risk_id', 'route_id', 'id']) {
    final value = item[key];
    if (value is String && value.isNotEmpty) return value;
  }
  return '$fallback ${index + 1}';
}

String _bridgeLabel(Map<String, dynamic> status) =>
    status['state']?.toString() ?? status['connection_state']?.toString() ?? 'WAITING';

bool _bridgeGood(Map<String, dynamic> status) {
  final value = _bridgeLabel(status).toLowerCase();
  return value.contains('ready') || value.contains('connect') || value.contains('running') || value.contains('stable');
}

String _eventCategory(String value) {
  final lower = value.toLowerCase();
  if (lower.contains('오류') || lower.contains('error') || lower.contains('reject')) return '오류';
  if (lower.contains('mission') || lower.contains('active')) return 'Mission';
  if (lower.contains('victim') || lower.contains('risk') || lower.contains('semantic') || lower.contains('요구조자') || lower.contains('위험')) return '탐지';
  return '통신';
}

String _humanEvent(String value) {
  if (value.length <= 180) return value;
  return '${value.substring(0, 177)}...';
}
