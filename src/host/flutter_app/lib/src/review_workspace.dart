import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'host_app.dart' show TransferStatusCard;
import 'host_controller.dart';
import 'semantic_map.dart';

final class ReviewWorkspace extends StatelessWidget {
  const ReviewWorkspace({super.key, required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final semantic = controller.reviewedSemantic;
    final victims = [
      ..._items(semantic, 'victim_candidates'),
      ..._items(semantic, 'confirmed_victims'),
    ];
    final risks = _items(semantic, 'risk_zones');
    final routes = _items(semantic, 'entry_routes');
    final teams = _items(semantic, 'team_recommendations');
    final waiting = _items(semantic, 'safe_waiting_points');
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Wrap(
          spacing: 10,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            FilledButton.tonalIcon(
              key: const Key('refresh-results'),
              onPressed: controller.busy ? null : controller.refreshResults,
              icon: const Icon(Icons.refresh),
              label: const Text('분석 결과 새로고침'),
            ),
            if (controller.results.isNotEmpty)
              SizedBox(
                width: 220,
                child: DropdownButtonFormField<int>(
                  key: const Key('result-version-selector'),
                  isExpanded: true,
                  initialValue: controller.currentResultVersion > 0
                      ? controller.currentResultVersion
                      : null,
                  decoration: const InputDecoration(labelText: '결과 버전'),
                  items: [
                    for (final item in controller.results)
                      if (_version(item) case final version?)
                        DropdownMenuItem(
                          value: version,
                          child: Text('semantic_result v$version'),
                        ),
                  ],
                  onChanged: controller.busy
                      ? null
                      : (value) {
                          if (value != null) {
                            controller.selectResultVersion(value);
                          }
                        },
                ),
              ),
            FilledButton.icon(
              key: const Key('publish-final-map'),
              onPressed: controller.currentResult == null || controller.busy
                  ? null
                  : controller.publishFinalMap,
              icon: const Icon(Icons.verified_outlined),
              label: const Text('최종 지도 전송'),
            ),
          ],
        ),
        const SizedBox(height: 10),
        if (controller.currentResult == null)
          const Card(
            child: Padding(
              padding: EdgeInsets.all(32),
              child: Text('수신한 semantic_result가 없습니다.'),
            ),
          )
        else ...[
          _ResultMetadata(controller: controller, semantic: semantic),
          const SizedBox(height: 10),
          SemanticMapView(controller: controller),
          const SizedBox(height: 10),
          _HistoryAndNotes(controller: controller),
          const SizedBox(height: 10),
          _Section(
            title: '요구조자 (${victims.length})',
            icon: Icons.person_pin_circle_outlined,
            children: [
              for (var index = 0; index < victims.length; index++)
                _VictimEditor(
                  controller: controller,
                  item: victims[index],
                  index: index,
                ),
            ],
          ),
          _Section(
            title: '위험 구역 (${risks.length})',
            icon: Icons.warning_amber,
            actions: [
              FilledButton.tonalIcon(
                key: const Key('add-risk'),
                onPressed: () => _addRisk(context, controller),
                icon: const Icon(Icons.add),
                label: const Text('위험 polygon 추가'),
              ),
            ],
            children: [
              for (var index = 0; index < risks.length; index++)
                _RiskEditor(
                  controller: controller,
                  item: risks[index],
                  index: index,
                ),
            ],
          ),
          _Section(
            title: '진입 경로 (${routes.length})',
            icon: Icons.route_outlined,
            children: [
              for (var index = 0; index < routes.length; index++)
                _RouteEditor(
                  controller: controller,
                  item: routes[index],
                  index: index,
                ),
            ],
          ),
          _Section(
            title: '팀 배치 (${teams.length})',
            icon: Icons.groups_outlined,
            actions: [
              OutlinedButton(
                key: const Key('copy-team-recommendations'),
                onPressed: controller.copyRecommendedAssignments,
                child: const Text('Jetson 추천 배치 복사'),
              ),
              OutlinedButton(
                key: const Key('clear-team-assignments'),
                onPressed: () => controller.applyReview({
                  'action': 'set_team_assignments',
                  'assignments': <JsonMap>[],
                }),
                child: const Text('전체 비우기'),
              ),
              FilledButton.tonalIcon(
                key: const Key('add-team-assignment'),
                onPressed: () => _upsertAssignment(context, controller, null),
                icon: const Icon(Icons.add),
                label: const Text('팀 배치 추가'),
              ),
            ],
            children: [
              for (var index = 0; index < teams.length; index++)
                _TeamEditor(
                  controller: controller,
                  item: teams[index],
                  index: index,
                ),
            ],
          ),
          _Section(
            title: '안전 대기점 (${waiting.length})',
            icon: Icons.place_outlined,
            actions: [
              OutlinedButton(
                key: const Key('clear-waiting-points'),
                onPressed: () => controller.applyReview({
                  'action': 'set_safe_waiting_points',
                  'points': <JsonMap>[],
                }),
                child: const Text('전체 비우기'),
              ),
              FilledButton.tonalIcon(
                key: const Key('add-waiting-point'),
                onPressed: () => _upsertWaiting(context, controller, null),
                icon: const Icon(Icons.add_location_alt_outlined),
                label: const Text('대기점 추가'),
              ),
            ],
            children: [
              for (var index = 0; index < waiting.length; index++)
                _WaitingEditor(
                  controller: controller,
                  item: waiting[index],
                  index: index,
                ),
            ],
          ),
          const SizedBox(height: 10),
          TransferStatusCard(controller: controller),
          ExpansionTile(
            title: const Text('원본/검토 JSON'),
            children: [
              SelectableText(
                const JsonEncoder.withIndent(
                  '  ',
                ).convert(controller.currentResult),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

class _ResultMetadata extends StatelessWidget {
  const _ResultMetadata({required this.controller, required this.semantic});
  final HostController controller;
  final JsonMap semantic;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Wrap(
        spacing: 10,
        runSpacing: 6,
        children: [
          Chip(label: Text('schema ${semantic['schema_version'] ?? '-'}')),
          Chip(
            label: Text(
              'mission ${semantic['mission_id'] ?? controller.missionId}',
            ),
          ),
          Chip(
            label: Text(
              'map v${semantic['base_map_version'] ?? controller.missionVersion}',
            ),
          ),
          Chip(
            label: Text(
              'result v${semantic['result_version'] ?? controller.currentResultVersion}',
            ),
          ),
          Chip(label: Text('source ${semantic['source'] ?? '-'}')),
          Chip(label: Text('confidence ${semantic['confidence'] ?? '-'}')),
          Chip(label: Text('units ${semantic['units'] ?? '-'}')),
          Chip(label: Text('review revision ${controller.reviewRevision}')),
          if (controller.previewVersion > 0)
            Chip(label: Text('SLAM preview v${controller.previewVersion}')),
          Text(
            '생성 ${semantic['generated_at'] ?? semantic['created_at'] ?? semantic['analyzed_at'] ?? '-'}',
          ),
        ],
      ),
    ),
  );
}

class _HistoryAndNotes extends StatelessWidget {
  const _HistoryAndNotes({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final editsValue = controller.currentResult?['host_edits'];
    final edits = editsValue is Map
        ? requireJsonMap(editsValue)
        : const <String, dynamic>{};
    final notes = edits['notes']?.toString() ?? '';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            IconButton.filledTonal(
              key: const Key('review-undo'),
              tooltip: '실행 취소',
              onPressed: controller.canUndo
                  ? () => controller.applyReview({'action': 'undo'})
                  : null,
              icon: const Icon(Icons.undo),
            ),
            IconButton.filledTonal(
              key: const Key('review-redo'),
              tooltip: '다시 실행',
              onPressed: controller.canRedo
                  ? () => controller.applyReview({'action': 'redo'})
                  : null,
              icon: const Icon(Icons.redo),
            ),
            OutlinedButton.icon(
              key: const Key('edit-review-notes'),
              onPressed: () async {
                final value = await _textDialog(
                  context,
                  title: '최종 구조계획 메모',
                  initial: notes,
                  multiline: true,
                );
                if (value != null) {
                  await controller.applyReview({
                    'action': 'set_notes',
                    'notes': value,
                  });
                }
              },
              icon: const Icon(Icons.notes),
              label: const Text('검토 메모 편집'),
            ),
            SizedBox(
              width: 500,
              child: Text(notes.isEmpty ? '검토 메모 없음' : notes),
            ),
          ],
        ),
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({
    required this.title,
    required this.icon,
    required this.children,
    this.actions = const [],
  });
  final String title;
  final IconData icon;
  final List<Widget> children;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) => Card(
    child: ExpansionTile(
      initiallyExpanded: true,
      leading: Icon(icon),
      title: Text(title),
      subtitle: actions.isEmpty
          ? null
          : Wrap(spacing: 8, runSpacing: 4, children: actions),
      children: children.isEmpty
          ? const [ListTile(title: Text('항목 없음'))]
          : children,
    ),
  );
}

class _VictimEditor extends StatelessWidget {
  const _VictimEditor({
    required this.controller,
    required this.item,
    required this.index,
  });
  final HostController controller;
  final JsonMap item;
  final int index;

  @override
  Widget build(BuildContext context) {
    final id = _id(item, index, 'victim');
    return ExpansionTile(
      initiallyExpanded: true,
      leading: const Icon(Icons.person_pin_circle_outlined),
      title: Text('요구조자 $id · ${item['host_status'] ?? 'pending'}'),
      subtitle: Text(_shortJson(item)),
      childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
      children: [
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final status in const ['pending', 'confirmed', 'excluded'])
              OutlinedButton(
                key: status == 'confirmed'
                    ? Key('confirm-victim-$index')
                    : null,
                onPressed: () => controller.applyReview({
                  'action': 'set_victim_status',
                  'victim_id': id,
                  'status': status,
                }),
                child: Text(switch (status) {
                  'pending' => '보류',
                  'confirmed' => '확인',
                  _ => '제외',
                }),
              ),
            OutlinedButton(
              key: Key('priority-victim-$index'),
              onPressed: () async {
                final priority = await _integerDialog(
                  context,
                  title: '$id 우선순위',
                  initial: (item['priority'] as num?)?.toInt() ?? 1,
                );
                if (priority != null) {
                  await controller.applyReview({
                    'action': 'set_victim_priority',
                    'victim_id': id,
                    'priority': priority,
                  });
                }
              },
              child: const Text('우선순위'),
            ),
            OutlinedButton(
              key: Key('position-victim-$index'),
              onPressed: () async {
                final point = await _pointDialog(
                  context,
                  title: '$id 지도 좌표',
                  initial: _rawPoint(item),
                );
                if (point != null) {
                  await controller.applyReview({
                    'action': 'set_victim_position',
                    'victim_id': id,
                    ...point,
                  });
                }
              },
              child: const Text('marker 좌표 수정'),
            ),
          ],
        ),
      ],
    );
  }
}

class _RiskEditor extends StatelessWidget {
  const _RiskEditor({
    required this.controller,
    required this.item,
    required this.index,
  });
  final HostController controller;
  final JsonMap item;
  final int index;

  @override
  Widget build(BuildContext context) {
    final id = _id(item, index, 'risk');
    final originalIds = _items(
      controller.originalSemantic ?? const {},
      'risk_zones',
    ).map((value) => _id(value, 0, 'risk')).toSet();
    final added = !originalIds.contains(id);
    return _ResponsiveEditorTile(
      icon: Icons.warning_amber,
      title: '위험 $id · ${item['state'] ?? 'unknown'}',
      subtitle: _shortJson(item),
      actions: Wrap(
        spacing: 5,
        children: [
          TextButton(
            key: Key('edit-risk-$index'),
            onPressed: () async {
              final value = await _riskDialog(
                context,
                initial: item,
                fixedId: id,
              );
              if (value != null) {
                await controller.applyReview({
                  'action': added
                      ? 'update_added_risk_zone'
                      : 'modify_risk_zone',
                  'risk_id': id,
                  'risk_zone': value,
                });
              }
            },
            child: const Text('polygon 수정'),
          ),
          TextButton(
            key: Key('remove-risk-$index'),
            onPressed: () => controller.applyReview({
              'action': added ? 'remove_added_risk_zone' : 'clear_risk_zone',
              'risk_id': id,
            }),
            child: Text(added ? '삭제' : '해제'),
          ),
        ],
      ),
    );
  }
}

class _RouteEditor extends StatelessWidget {
  const _RouteEditor({
    required this.controller,
    required this.item,
    required this.index,
  });
  final HostController controller;
  final JsonMap item;
  final int index;

  @override
  Widget build(BuildContext context) {
    final id = _id(item, index, 'route');
    return _ResponsiveEditorTile(
      icon: Icons.route_outlined,
      title: '경로 $id · ${item['host_status'] ?? '미결정'}',
      subtitle: _shortJson(item),
      actions: Wrap(
        spacing: 5,
        children: [
          TextButton(
            key: Key('approve-route-$index'),
            onPressed: () => controller.applyReview({
              'action': 'set_route_approved',
              'route_id': id,
              'approved': true,
            }),
            child: const Text('승인'),
          ),
          TextButton(
            key: Key('exclude-route-$index'),
            onPressed: () => controller.applyReview({
              'action': 'set_route_approved',
              'route_id': id,
              'approved': false,
            }),
            child: const Text('제외'),
          ),
        ],
      ),
    );
  }
}

class _TeamEditor extends StatelessWidget {
  const _TeamEditor({
    required this.controller,
    required this.item,
    required this.index,
  });
  final HostController controller;
  final JsonMap item;
  final int index;

  @override
  Widget build(BuildContext context) {
    final id = _id(item, index, 'team');
    return _ResponsiveEditorTile(
      icon: Icons.group,
      title: '팀 $id',
      subtitle: _shortJson(item),
      actions: Wrap(
        children: [
          TextButton(
            key: Key('edit-team-$index'),
            onPressed: () => _upsertAssignment(context, controller, item),
            child: const Text('배치/담당 수정'),
          ),
          TextButton(
            key: Key('remove-team-$index'),
            onPressed: () => controller.applyReview({
              'action': 'remove_team_assignment',
              'team_id': id,
            }),
            child: const Text('삭제'),
          ),
        ],
      ),
    );
  }
}

class _WaitingEditor extends StatelessWidget {
  const _WaitingEditor({
    required this.controller,
    required this.item,
    required this.index,
  });
  final HostController controller;
  final JsonMap item;
  final int index;

  @override
  Widget build(BuildContext context) {
    final id = _id(item, index, 'waiting');
    return _ResponsiveEditorTile(
      icon: Icons.place_outlined,
      title: '대기점 $id',
      subtitle: _shortJson(item),
      actions: Wrap(
        children: [
          TextButton(
            key: Key('edit-waiting-$index'),
            onPressed: () => _upsertWaiting(context, controller, item),
            child: const Text('marker 수정'),
          ),
          TextButton(
            key: Key('remove-waiting-$index'),
            onPressed: () => controller.applyReview({
              'action': 'remove_safe_waiting_point',
              'waiting_id': id,
            }),
            child: const Text('삭제'),
          ),
        ],
      ),
    );
  }
}

class _ResponsiveEditorTile extends StatelessWidget {
  const _ResponsiveEditorTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.actions,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final Widget actions;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 3, right: 12),
              child: Icon(icon),
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: Theme.of(context).textTheme.titleSmall),
                  const SizedBox(height: 3),
                  Text(subtitle),
                ],
              ),
            ),
          ],
        ),
        Align(alignment: Alignment.centerRight, child: actions),
      ],
    ),
  );
}

Future<void> _addRisk(BuildContext context, HostController controller) async {
  final value = await _riskDialog(context);
  if (value != null) {
    await controller.applyReview({
      'action': 'add_risk_zone',
      'risk_zone': value,
    });
  }
}

@visibleForTesting
const exposedReviewCommands = <String>{
  'set_victim_status',
  'set_victim_priority',
  'set_victim_position',
  'set_route_approved',
  'modify_risk_zone',
  'clear_risk_zone',
  'add_risk_zone',
  'remove_added_risk_zone',
  'update_added_risk_zone',
  'set_team_assignments',
  'upsert_team_assignment',
  'remove_team_assignment',
  'set_safe_waiting_points',
  'add_safe_waiting_point',
  'update_safe_waiting_point',
  'remove_safe_waiting_point',
  'set_notes',
  'undo',
  'redo',
};

Future<void> _upsertAssignment(
  BuildContext context,
  HostController controller,
  JsonMap? initial,
) async {
  final assignment = await _assignmentDialog(context, initial: initial);
  if (assignment != null) {
    await controller.applyReview({
      'action': 'upsert_team_assignment',
      'assignment': assignment,
    });
  }
}

Future<void> _upsertWaiting(
  BuildContext context,
  HostController controller,
  JsonMap? initial,
) async {
  final id = initial == null ? null : _id(initial, 0, 'waiting');
  final value = await _waitingDialog(context, initial: initial, fixedId: id);
  if (value != null) {
    await controller.applyReview({
      'action': initial == null
          ? 'add_safe_waiting_point'
          : 'update_safe_waiting_point',
      ...value,
    });
  }
}

Future<int?> _integerDialog(
  BuildContext context, {
  required String title,
  required int initial,
}) async {
  final controller = TextEditingController(text: initial.toString());
  final result = await showDialog<int>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: TextField(
        key: const Key('dialog-integer'),
        controller: controller,
        autofocus: true,
        keyboardType: TextInputType.number,
        decoration: const InputDecoration(labelText: '1 이상의 우선순위'),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('취소'),
        ),
        FilledButton(
          key: const Key('dialog-save'),
          onPressed: () {
            final value = int.tryParse(controller.text);
            if (value != null && value > 0) Navigator.pop(context, value);
          },
          child: const Text('저장'),
        ),
      ],
    ),
  );
  controller.dispose();
  return result;
}

Future<String?> _textDialog(
  BuildContext context, {
  required String title,
  required String initial,
  bool multiline = false,
}) async {
  final controller = TextEditingController(text: initial);
  final result = await showDialog<String>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: TextField(
        key: const Key('dialog-text'),
        controller: controller,
        autofocus: true,
        minLines: multiline ? 3 : 1,
        maxLines: multiline ? 8 : 1,
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('취소'),
        ),
        FilledButton(
          key: const Key('dialog-save'),
          onPressed: () => Navigator.pop(context, controller.text),
          child: const Text('저장'),
        ),
      ],
    ),
  );
  controller.dispose();
  return result;
}

Future<JsonMap?> _pointDialog(
  BuildContext context, {
  required String title,
  JsonMap? initial,
}) async {
  final x = TextEditingController(text: initial?['x']?.toString() ?? '0');
  final y = TextEditingController(text: initial?['y']?.toString() ?? '0');
  final result = await showDialog<JsonMap>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: SingleChildScrollView(
        child: Wrap(
          spacing: 10,
          runSpacing: 8,
          children: [
            SizedBox(
              width: 130,
              child: TextField(
                key: const Key('dialog-x'),
                controller: x,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                  signed: true,
                ),
                decoration: const InputDecoration(labelText: 'map x (m)'),
              ),
            ),
            SizedBox(
              width: 130,
              child: TextField(
                key: const Key('dialog-y'),
                controller: y,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                  signed: true,
                ),
                decoration: const InputDecoration(labelText: 'map y (m)'),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('취소'),
        ),
        FilledButton(
          key: const Key('dialog-save'),
          onPressed: () {
            final px = double.tryParse(x.text);
            final py = double.tryParse(y.text);
            if (px != null && py != null) {
              Navigator.pop(context, {'x': px, 'y': py});
            }
          },
          child: const Text('저장'),
        ),
      ],
    ),
  );
  x.dispose();
  y.dispose();
  return result;
}

Future<JsonMap?> _riskDialog(
  BuildContext context, {
  JsonMap? initial,
  String? fixedId,
}) async {
  final id = TextEditingController(
    text: fixedId ?? initial?['risk_id']?.toString() ?? 'host-risk-1',
  );
  final type = TextEditingController(
    text: initial?['risk_type']?.toString() ?? 'debris',
  );
  final severity = TextEditingController(
    text: initial?['severity']?.toString() ?? '0.5',
  );
  final confidence = TextEditingController(
    text: initial?['confidence']?.toString() ?? '1.0',
  );
  final polygon = TextEditingController(
    text: _polygonText(initial?['polygon']),
  );
  var state = initial?['state']?.toString() ?? 'observed';
  final result = await showDialog<JsonMap>(
    context: context,
    builder: (context) => StatefulBuilder(
      builder: (context, setState) => AlertDialog(
        title: const Text('위험 구역 polygon 편집'),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  key: const Key('risk-id'),
                  controller: id,
                  enabled: fixedId == null,
                  decoration: const InputDecoration(labelText: 'Risk ID'),
                ),
                TextField(
                  controller: type,
                  decoration: const InputDecoration(labelText: '위험 종류'),
                ),
                DropdownButtonFormField<String>(
                  initialValue: state,
                  decoration: const InputDecoration(labelText: '관측 상태'),
                  items: const [
                    DropdownMenuItem(
                      value: 'observed',
                      child: Text('observed'),
                    ),
                    DropdownMenuItem(
                      value: 'interpolated',
                      child: Text('interpolated'),
                    ),
                    DropdownMenuItem(value: 'unknown', child: Text('unknown')),
                  ],
                  onChanged: (value) => setState(() => state = value ?? state),
                ),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: severity,
                        decoration: const InputDecoration(
                          labelText: 'severity 0..1',
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: TextField(
                        controller: confidence,
                        decoration: const InputDecoration(
                          labelText: 'confidence 0..1',
                        ),
                      ),
                    ),
                  ],
                ),
                TextField(
                  key: const Key('risk-polygon'),
                  controller: polygon,
                  minLines: 2,
                  maxLines: 5,
                  decoration: const InputDecoration(
                    labelText: 'map polygon 좌표',
                    helperText: 'x,y; x,y; x,y 형식 (marker 위험은 한 점 허용)',
                  ),
                ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('취소'),
          ),
          FilledButton(
            key: const Key('dialog-save'),
            onPressed: () {
              final points = _parsePolygon(polygon.text);
              final sev = double.tryParse(severity.text);
              final conf = double.tryParse(confidence.text);
              if (id.text.trim().isNotEmpty &&
                  type.text.trim().isNotEmpty &&
                  points.isNotEmpty &&
                  sev != null &&
                  sev >= 0 &&
                  sev <= 1 &&
                  conf != null &&
                  conf >= 0 &&
                  conf <= 1) {
                Navigator.pop(context, {
                  'risk_id': id.text.trim(),
                  'risk_type': type.text.trim(),
                  'state': state,
                  'severity': sev,
                  'confidence': conf,
                  'polygon': points,
                  'source': initial?['source'] ?? 'host_user',
                });
              }
            },
            child: const Text('저장'),
          ),
        ],
      ),
    ),
  );
  for (final controller in [id, type, severity, confidence, polygon]) {
    controller.dispose();
  }
  return result;
}

Future<JsonMap?> _assignmentDialog(
  BuildContext context, {
  JsonMap? initial,
}) async {
  final position = _rawPoint(initial ?? const {});
  final team = TextEditingController(
    text: initial?['team_id']?.toString() ?? 'team-1',
  );
  final x = TextEditingController(text: position?['x']?.toString() ?? '0');
  final y = TextEditingController(text: position?['y']?.toString() ?? '0');
  final victim = TextEditingController(
    text: (initial?['victim_id'] ?? initial?['assigned_victim_id'] ?? '')
        .toString(),
  );
  final route = TextEditingController(
    text: initial?['route_id']?.toString() ?? '',
  );
  final result = await showDialog<JsonMap>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('팀 배치 / 담당 편집'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                key: const Key('team-id'),
                controller: team,
                decoration: const InputDecoration(labelText: 'Team ID'),
              ),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: x,
                      decoration: const InputDecoration(labelText: 'map x (m)'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextField(
                      controller: y,
                      decoration: const InputDecoration(labelText: 'map y (m)'),
                    ),
                  ),
                ],
              ),
              TextField(
                controller: victim,
                decoration: const InputDecoration(
                  labelText: '담당 victim ID (선택)',
                ),
              ),
              TextField(
                controller: route,
                decoration: const InputDecoration(labelText: 'route ID (선택)'),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('취소'),
        ),
        FilledButton(
          key: const Key('dialog-save'),
          onPressed: () {
            final px = double.tryParse(x.text);
            final py = double.tryParse(y.text);
            if (team.text.trim().isNotEmpty && px != null && py != null) {
              Navigator.pop(context, {
                'team_id': team.text.trim(),
                'position': {'x': px, 'y': py},
                'victim_id': victim.text.trim().isEmpty
                    ? null
                    : victim.text.trim(),
                'route_id': route.text.trim().isEmpty
                    ? null
                    : route.text.trim(),
              });
            }
          },
          child: const Text('저장'),
        ),
      ],
    ),
  );
  for (final controller in [team, x, y, victim, route]) {
    controller.dispose();
  }
  return result;
}

Future<JsonMap?> _waitingDialog(
  BuildContext context, {
  JsonMap? initial,
  String? fixedId,
}) async {
  final point = _rawPoint(initial ?? const {});
  final id = TextEditingController(text: fixedId ?? 'waiting-1');
  final x = TextEditingController(text: point?['x']?.toString() ?? '0');
  final y = TextEditingController(text: point?['y']?.toString() ?? '0');
  final result = await showDialog<JsonMap>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('안전 대기점 marker 편집'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              key: const Key('waiting-id'),
              controller: id,
              enabled: fixedId == null,
              decoration: const InputDecoration(labelText: 'Waiting ID'),
            ),
            TextField(
              controller: x,
              decoration: const InputDecoration(labelText: 'map x (m)'),
            ),
            TextField(
              controller: y,
              decoration: const InputDecoration(labelText: 'map y (m)'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('취소'),
        ),
        FilledButton(
          key: const Key('dialog-save'),
          onPressed: () {
            final px = double.tryParse(x.text);
            final py = double.tryParse(y.text);
            if (id.text.trim().isNotEmpty && px != null && py != null) {
              Navigator.pop(context, {
                'waiting_id': id.text.trim(),
                'x': px,
                'y': py,
              });
            }
          },
          child: const Text('저장'),
        ),
      ],
    ),
  );
  id.dispose();
  x.dispose();
  y.dispose();
  return result;
}

List<JsonMap> _items(JsonMap value, String key) {
  final item = value[key];
  return item is List
      ? item.whereType<Map>().map(requireJsonMap).toList(growable: false)
      : const [];
}

int? _version(JsonMap value) {
  final raw = value['result_version'] ?? value['version'];
  return raw is num ? raw.toInt() : int.tryParse(raw?.toString() ?? '');
}

String _id(JsonMap value, int index, String prefix) {
  for (final key in [
    '${prefix}_id',
    'detection_id',
    'candidate_id',
    'person_id',
    'route_id',
    'team_id',
    'waiting_id',
    'safe_waiting_id',
    'id',
  ]) {
    final item = value[key];
    if (item != null && item.toString().isNotEmpty) return item.toString();
  }
  return '$prefix-${index + 1}';
}

JsonMap? _rawPoint(JsonMap value) {
  var point = value;
  for (final key in const ['map_position', 'position', 'map_point', 'center']) {
    final nested = point[key];
    if (nested is Map) {
      point = requireJsonMap(nested);
      break;
    }
  }
  final x = point['x'] ?? point['map_x'];
  final y = point['y'] ?? point['map_y'];
  return x is num && y is num ? {'x': x.toDouble(), 'y': y.toDouble()} : null;
}

String _polygonText(Object? value) {
  if (value is! List) return '0,0; 1,0; 1,1';
  return value
      .whereType<Map>()
      .map((item) {
        final point = requireJsonMap(item);
        return '${point['x'] ?? 0},${point['y'] ?? 0}';
      })
      .join('; ');
}

List<JsonMap> _parsePolygon(String value) {
  final result = <JsonMap>[];
  for (final pair in value.split(';')) {
    final values = pair.split(',');
    if (values.length != 2) return const [];
    final x = double.tryParse(values[0].trim());
    final y = double.tryParse(values[1].trim());
    if (x == null || y == null) return const [];
    result.add({'x': x, 'y': y});
  }
  return result;
}

String _shortJson(JsonMap value) {
  final text = jsonEncode(value);
  return text.length > 220 ? '${text.substring(0, 220)}…' : text;
}
