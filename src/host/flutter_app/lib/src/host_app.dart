import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

import 'file_picker_adapter.dart';
import 'host_controller.dart';
import 'map_editor.dart';
import 'review_workspace.dart';

final class RescueHostApp extends StatefulWidget {
  const RescueHostApp({super.key, required this.controller, this.filePicker});

  final HostController controller;
  final MapFilePicker? filePicker;

  @override
  State<RescueHostApp> createState() => _RescueHostAppState();
}

class _RescueHostAppState extends State<RescueHostApp> {
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
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI Rescue Box Host',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xff00695c),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: _HostShell(
        controller: widget.controller,
        filePicker: widget.filePicker ?? PlatformMapFilePicker(),
      ),
    );
  }
}

class _HostShell extends StatefulWidget {
  const _HostShell({required this.controller, required this.filePicker});
  final HostController controller;
  final MapFilePicker filePicker;

  @override
  State<_HostShell> createState() => _HostShellState();
}

class _HostShellState extends State<_HostShell> {
  int page = 0;

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Rescue Box · Host'),
        actions: [
          _CompactStatus(controller: controller),
          const SizedBox(width: 12),
        ],
        bottom: controller.busy
            ? const PreferredSize(
                preferredSize: Size.fromHeight(3),
                child: LinearProgressIndicator(),
              )
            : null,
      ),
      body: Column(
        children: [
          if (controller.error != null)
            MaterialBanner(
              content: Text(controller.error!),
              actions: [
                TextButton(
                  onPressed: controller.clearError,
                  child: const Text('확인'),
                ),
              ],
            ),
          Expanded(
            child: IndexedStack(
              index: page,
              children: [
                _MissionPage(controller: controller, picker: widget.filePicker),
                ReviewWorkspace(controller: controller),
                _EventsPage(controller: controller),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: page,
        onDestinationSelected: (value) => setState(() => page = value),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.map_outlined), label: '임무'),
          NavigationDestination(
            icon: Icon(Icons.fact_check_outlined),
            label: '분석·검토',
          ),
          NavigationDestination(
            icon: Icon(Icons.monitor_heart_outlined),
            label: '상태·이벤트',
          ),
        ],
      ),
    );
  }
}

class _MissionPage extends StatelessWidget {
  const _MissionPage({required this.controller, required this.picker});
  final HostController controller;
  final MapFilePicker picker;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _MissionHistory(controller: controller),
        const SizedBox(height: 12),
        Wrap(
          spacing: 12,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            FilledButton.icon(
              key: const Key('upload-map'),
              onPressed: controller.busy
                  ? null
                  : () => controller.chooseAndUpload(picker),
              icon: const Icon(Icons.upload_file),
              label: const Text('JPEG/PNG 구조도 업로드'),
            ),
            if (controller.mapFilename != null)
              Text(
                '${controller.mapFilename} '
                '(${controller.imageWidth}×${controller.imageHeight})',
              ),
            SegmentedButton<MapEditMode>(
              segments: const [
                ButtonSegment(
                  value: MapEditMode.robotStart,
                  icon: Icon(Icons.smart_toy_outlined),
                  label: Text('시작 pose'),
                ),
                ButtonSegment(
                  value: MapEditMode.scaleFirst,
                  icon: Icon(Icons.straighten),
                  label: Text('축척'),
                ),
                ButtonSegment(
                  value: MapEditMode.entrance,
                  icon: Icon(Icons.door_front_door_outlined),
                  label: Text('출입구'),
                ),
              ],
              selected: {
                controller.editMode == MapEditMode.scaleSecond
                    ? MapEditMode.scaleFirst
                    : controller.editMode,
              },
              onSelectionChanged: (values) =>
                  controller.setEditMode(values.first),
            ),
          ],
        ),
        if (controller.uploadReceipt case final receipt?) ...[
          const SizedBox(height: 8),
          _NormalizedMapMetadata(metadata: receipt),
        ],
        const SizedBox(height: 12),
        MissionMapEditor(controller: controller),
        const SizedBox(height: 12),
        _MissionControls(controller: controller),
        const SizedBox(height: 12),
        TransferStatusCard(controller: controller),
        const SizedBox(height: 8),
        FilledButton.icon(
          key: const Key('send-mission'),
          onPressed: controller.missionReady && !controller.busy
              ? controller.createAndSendMission
              : null,
          icon: const Icon(Icons.podcasts),
          label: const Text('임무 생성 및 UWB 전송'),
        ),
        if (!controller.yawSpecified && controller.robotStart != null)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text(
              '초기 yaw 미지정: 지도에서 시작 방향으로 드래그하거나 slider를 조작하세요.',
              style: TextStyle(color: Colors.amber),
            ),
          ),
      ],
    );
  }
}

class _MissionHistory extends StatelessWidget {
  const _MissionHistory({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final currentKey = '${controller.missionId}:${controller.missionVersion}';
    final keys = controller.missions.map(_missionKey).toSet();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Wrap(
          spacing: 10,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SizedBox(
              width: 420,
              child: DropdownButtonFormField<String>(
                key: const Key('mission-selector'),
                isExpanded: true,
                initialValue: keys.contains(currentKey) ? currentKey : null,
                decoration: const InputDecoration(labelText: '저장된 임무 / 버전'),
                items: [
                  for (final mission in controller.missions)
                    DropdownMenuItem(
                      value: _missionKey(mission),
                      child: Text(_missionLabel(mission)),
                    ),
                ],
                onChanged: controller.busy
                    ? null
                    : (value) {
                        if (value == null) return;
                        controller.selectMission(
                          controller.missions.firstWhere(
                            (item) => _missionKey(item) == value,
                          ),
                        );
                      },
              ),
            ),
            OutlinedButton.icon(
              key: const Key('next-mission-version'),
              onPressed: controller.missionId.isEmpty
                  ? null
                  : controller.prepareNextVersion,
              icon: const Icon(Icons.fork_right),
              label: const Text('다음 버전 작성'),
            ),
            OutlinedButton.icon(
              key: const Key('resend-mission'),
              onPressed: controller.existingMissionSelected && !controller.busy
                  ? controller.resendSelectedMission
                  : null,
              icon: const Icon(Icons.replay),
              label: const Text('선택 버전 재전송'),
            ),
          ],
        ),
      ),
    );
  }
}

class _MissionControls extends StatelessWidget {
  const _MissionControls({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Wrap(
          spacing: 16,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SizedBox(
              width: 220,
              child: TextFormField(
                key: ValueKey('name-${controller.missionFormRevision}'),
                initialValue: controller.missionName,
                decoration: const InputDecoration(labelText: '임무 이름'),
                onChanged: (value) =>
                    controller.updateMissionFields(name: value),
              ),
            ),
            SizedBox(
              width: 220,
              child: TextFormField(
                key: ValueKey('id-${controller.missionFormRevision}'),
                initialValue: controller.missionId,
                decoration: const InputDecoration(labelText: '임무 ID (비우면 자동)'),
                onChanged: (value) => controller.updateMissionFields(id: value),
              ),
            ),
            SizedBox(
              width: 220,
              child: TextFormField(
                key: const Key('scale-distance'),
                initialValue: controller.scaleDistanceMeters.toString(),
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: InputDecoration(
                  labelText: '축척 두 점 실제 거리 (m)',
                  helperText: controller.metersPerPixel == null
                      ? '지도에서 두 점을 선택하세요'
                      : '${controller.metersPerPixel!.toStringAsFixed(5)} m/px',
                ),
                onChanged: (value) =>
                    controller.setScaleDistance(double.tryParse(value) ?? 0),
              ),
            ),
            SizedBox(
              width: 300,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    controller.yawSpecified
                        ? '초기 방향 ${(controller.robotYawRadians * 180 / mathPi).round()}°'
                        : '초기 방향 미지정',
                  ),
                  Slider(
                    key: const Key('robot-yaw'),
                    min: -mathPi,
                    max: mathPi,
                    value: controller.robotYawRadians,
                    onChanged: controller.robotStart == null
                        ? null
                        : controller.setYaw,
                  ),
                ],
              ),
            ),
            _CountField(
              formRevision: controller.missionFormRevision,
              label: '임무 버전',
              value: controller.missionVersion,
              onChanged: (value) =>
                  controller.updateMissionFields(version: value),
            ),
            _CountField(
              formRevision: controller.missionFormRevision,
              label: '구조팀 수',
              value: controller.teamCount,
              allowZero: true,
              onChanged: (value) =>
                  controller.updateMissionFields(teams: value),
            ),
            _CountField(
              formRevision: controller.missionFormRevision,
              label: '총 구조인원',
              value: controller.availableRescuers,
              allowZero: true,
              onChanged: (value) =>
                  controller.updateMissionFields(rescuers: value),
            ),
            SizedBox(
              width: 360,
              child: TextFormField(
                key: ValueKey('notes-${controller.missionFormRevision}'),
                initialValue: controller.missionNotes,
                minLines: 1,
                maxLines: 3,
                decoration: const InputDecoration(labelText: '임무 메모'),
                onChanged: (value) =>
                    controller.updateMissionFields(notes: value),
              ),
            ),
            TextButton.icon(
              onPressed: controller.entrances.isEmpty
                  ? null
                  : controller.clearEntrances,
              icon: const Icon(Icons.clear_all),
              label: Text('출입구 ${controller.entrances.length}개 지우기'),
            ),
          ],
        ),
      ),
    );
  }
}

const mathPi = 3.1415926535897932;

class _CountField extends StatelessWidget {
  const _CountField({
    required this.label,
    required this.value,
    required this.onChanged,
    required this.formRevision,
    this.allowZero = false,
  });
  final String label;
  final int value;
  final ValueChanged<int> onChanged;
  final bool allowZero;
  final int formRevision;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 130,
      child: TextFormField(
        key: ValueKey('$label-$formRevision'),
        initialValue: value.toString(),
        keyboardType: TextInputType.number,
        decoration: InputDecoration(labelText: label),
        onChanged: (text) {
          final parsed = int.tryParse(text);
          if (parsed != null && (allowZero ? parsed >= 0 : parsed > 0)) {
            onChanged(parsed);
          }
        },
      ),
    );
  }
}

class _NormalizedMapMetadata extends StatelessWidget {
  const _NormalizedMapMetadata({required this.metadata});
  final JsonMap metadata;

  @override
  Widget build(BuildContext context) {
    String value(String key) => metadata[key]?.toString() ?? '-';
    return Card(
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Wrap(
          spacing: 14,
          runSpacing: 6,
          children: [
            const Chip(label: Text('정규화 완료')),
            Text('원본 ${value('original_width')}×${value('original_height')}'),
            Text('전송 ${value('width')}×${value('height')}'),
            Text('형식 ${value('image_format')}'),
            Text('크기 ${value('file_size')} bytes'),
            Text('SHA-256 ${_abbreviate(value('sha256'))}'),
            Text('Map ID ${value('map_id')}'),
          ],
        ),
      ),
    );
  }
}

class TransferStatusCard extends StatelessWidget {
  const TransferStatusCard({super.key, required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'UWB 전송 · ${controller.transferArtifact.isEmpty ? controller.transferStage : '${controller.transferArtifact} / ${controller.transferStage}'}',
            ),
            const SizedBox(height: 6),
            LinearProgressIndicator(value: controller.transferProgress),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                _StepChip(label: '프레임 ACK', done: controller.frameAck),
                _StepChip(label: '원격 저장', done: controller.remoteSaved),
                _StepChip(label: '적용 ACK', done: controller.applicationAck),
                if (controller.activeOperation case final operation?)
                  Chip(
                    label: Text('operation ${operation['state'] ?? 'running'}'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _StepChip extends StatelessWidget {
  const _StepChip({required this.label, required this.done});
  final String label;
  final bool done;

  @override
  Widget build(BuildContext context) => Chip(
    avatar: Icon(
      done ? Icons.check_circle : Icons.radio_button_unchecked,
      size: 18,
    ),
    label: Text(label),
  );
}

class _EventsPage extends StatelessWidget {
  const _EventsPage({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final bridge = controller.bridgeStatus;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _BooleanStatus(
              label: 'Bridge',
              active: bridge['bridge_running'] == true,
              detail: bridge['state']?.toString(),
            ),
            _BooleanStatus(
              label: 'Serial',
              active: bridge['serial_connected'] == true,
            ),
            _BooleanStatus(
              label: 'Jetson peer',
              active: bridge['peer_connected'] == true,
            ),
            Chip(
              avatar: const Icon(Icons.sync_alt, size: 18),
              label: Text(
                'TX ${bridge['bytes_sent'] ?? 0} / RX ${bridge['bytes_received'] ?? 0}',
              ),
            ),
            Chip(label: Text('재시도 ${bridge['retry_count'] ?? 0}')),
            Chip(
              avatar: const Icon(Icons.hub_outlined, size: 18),
              label: Text(
                '${controller.webSocketState} #${controller.lastEventSequence}',
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          children: [
            FilledButton.tonalIcon(
              key: const Key('refresh-status'),
              onPressed: controller.busy ? null : controller.refreshStatus,
              icon: const Icon(Icons.refresh),
              label: const Text('상태 새로고침'),
            ),
            FilledButton.tonalIcon(
              key: const Key('reconnect-bridge'),
              onPressed: controller.busy ? null : controller.reconnectBridge,
              icon: const Icon(Icons.settings_input_antenna),
              label: const Text('Bridge 재연결'),
            ),
          ],
        ),
        const SizedBox(height: 12),
        TransferStatusCard(controller: controller),
        ExpansionTile(
          title: const Text('Backend 원본 상태'),
          children: [
            SelectableText(
              const JsonEncoder.withIndent(
                '  ',
              ).convert(controller.backendStatus),
            ),
          ],
        ),
        const Divider(),
        for (final event in controller.eventLog.take(500))
          ListTile(
            dense: true,
            leading: const Icon(Icons.chevron_right),
            title: Text(event),
          ),
      ],
    );
  }
}

class _BooleanStatus extends StatelessWidget {
  const _BooleanStatus({
    required this.label,
    required this.active,
    this.detail,
  });
  final String label;
  final bool active;
  final String? detail;

  @override
  Widget build(BuildContext context) => Chip(
    avatar: Icon(
      active ? Icons.check_circle : Icons.error_outline,
      color: active ? Colors.greenAccent : Colors.orangeAccent,
      size: 18,
    ),
    label: Text(detail == null ? label : '$label · $detail'),
  );
}

class _CompactStatus extends StatelessWidget {
  const _CompactStatus({required this.controller});
  final HostController controller;

  @override
  Widget build(BuildContext context) {
    final bridge = controller.bridgeStatus;
    final ready =
        bridge['bridge_running'] == true &&
        bridge['serial_connected'] == true &&
        bridge['peer_connected'] == true;
    return Chip(
      avatar: Icon(ready ? Icons.sensors : Icons.sensors_off, size: 18),
      label: Text(ready ? 'UWB 준비' : 'UWB 확인 필요'),
    );
  }
}

String _missionKey(JsonMap value) =>
    '${value['mission_id']}:${value['mission_version'] ?? value['version']}';

String _missionLabel(JsonMap value) =>
    '${value['mission_name'] ?? value['name'] ?? value['mission_id']} · '
    '${value['mission_id']} v${value['mission_version'] ?? value['version']}';

String _abbreviate(String value) => value.length <= 18
    ? value
    : '${value.substring(0, 10)}…${value.substring(value.length - 6)}';
