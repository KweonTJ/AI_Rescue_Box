import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';

import 'models.dart';

abstract interface class RescueTransport {
  Stream<ApiEvent> get events;

  Future<Object?> get(String path, {Map<String, Object?> query = const {}});

  Future<Uint8List> getBytes(
    String path, {
    Map<String, Object?> query = const {},
  });

  Future<Object?> post(
    String path, {
    Object? body,
    Map<String, Object?> query = const {},
  });

  Future<JsonMap> upload(
    String path, {
    required String filename,
    required Uint8List bytes,
    Map<String, Object?> query = const {},
  });

  Future<void> close();
}

final class HttpRescueTransport implements RescueTransport {
  HttpRescueTransport({
    required this.endpoints,
    http.Client? client,
    this.requestTimeout = const Duration(minutes: 3),
    this.reconnectDelay = const Duration(seconds: 2),
  }) : _client = client ?? http.Client();

  final ApiEndpoints endpoints;
  final Duration requestTimeout;
  final Duration reconnectDelay;
  final http.Client _client;
  final StreamController<ApiEvent> _events =
      StreamController<ApiEvent>.broadcast();

  WebSocketChannel? _socket;
  Timer? _reconnectTimer;
  bool _connecting = false;
  bool _closed = false;
  ApiEventCursor _eventCursor = const ApiEventCursor();

  @override
  Stream<ApiEvent> get events {
    _connectEvents();
    return _events.stream;
  }

  @override
  Future<Object?> get(
    String path, {
    Map<String, Object?> query = const {},
  }) async {
    final uri = endpoints.resolve(path, query);
    final response = await _client
        .get(uri, headers: const {'Accept': 'application/json'})
        .timeout(requestTimeout);
    return _decode('GET', uri, response);
  }

  @override
  Future<Uint8List> getBytes(
    String path, {
    Map<String, Object?> query = const {},
  }) async {
    final uri = endpoints.resolve(path, query);
    final response = await _client
        .get(uri, headers: const {'Accept': 'image/png,image/jpeg,*/*'})
        .timeout(requestTimeout);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      _decode('GET', uri, response);
    }
    return Uint8List.fromList(response.bodyBytes);
  }

  @override
  Future<Object?> post(
    String path, {
    Object? body,
    Map<String, Object?> query = const {},
  }) async {
    final uri = endpoints.resolve(path, query);
    final response = await _client
        .post(
          uri,
          headers: const {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
          },
          body: jsonEncode(body ?? <String, dynamic>{}),
        )
        .timeout(requestTimeout);
    return _decode('POST', uri, response);
  }

  @override
  Future<JsonMap> upload(
    String path, {
    required String filename,
    required Uint8List bytes,
    Map<String, Object?> query = const {},
  }) async {
    final uri = endpoints.resolve(path, {...query, 'filename': filename});
    final request = http.Request('POST', uri)
      ..headers.addAll(const {
        'Accept': 'application/json',
        'Content-Type': 'application/octet-stream',
      })
      ..bodyBytes = bytes;
    final streamed = await _client.send(request).timeout(requestTimeout);
    final response = await http.Response.fromStream(streamed);
    return requireJsonMap(_decode('POST', uri, response));
  }

  Object? _decode(String method, Uri uri, http.Response response) {
    Object? decoded;
    if (response.bodyBytes.isNotEmpty) {
      try {
        decoded = jsonDecode(utf8.decode(response.bodyBytes));
      } on Object {
        decoded = utf8.decode(response.bodyBytes, allowMalformed: true);
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      String message = response.reasonPhrase ?? 'request failed';
      if (decoded is Map) {
        final detail = decoded['detail'];
        if (detail is String) message = detail;
        if (detail is Map && detail['message'] is String) {
          message = detail['message'] as String;
        }
      } else if (decoded is String && decoded.isNotEmpty) {
        message = decoded;
      }
      throw ApiFailure(
        method: method,
        uri: uri,
        statusCode: response.statusCode,
        message: message,
        details: decoded,
      );
    }
    return decoded;
  }

  Future<void> _connectEvents() async {
    if (_closed || _connecting || _socket != null) return;
    _reconnectTimer?.cancel();
    _connecting = true;
    try {
      final socketUri = _eventCursor.sequence > 0
          ? eventReplayUri(
              endpoints.webSocketUri,
              _eventCursor.sequence,
              instanceId: _eventCursor.instanceId,
            )
          : endpoints.webSocketUri;
      final channel = WebSocketChannel.connect(socketUri);
      await channel.ready.timeout(requestTimeout);
      if (_closed) {
        await channel.sink.close();
        return;
      }
      _socket = channel;
      channel.stream.listen(
        (message) {
          try {
            final event = ApiEvent.decode(message.toString());
            _eventCursor = _eventCursor.observe(event);
            _events.add(event);
          } on Object catch (error, stackTrace) {
            _events.addError(error, stackTrace);
          }
        },
        onError: (Object error, StackTrace stackTrace) {
          if (!_closed) _events.addError(error, stackTrace);
          _socketEnded(channel);
        },
        onDone: () => _socketEnded(channel),
        cancelOnError: true,
      );
    } on Object catch (error, stackTrace) {
      if (!_closed) _events.addError(error, stackTrace);
      _scheduleReconnect();
    } finally {
      _connecting = false;
    }
  }

  void _socketEnded(WebSocketChannel channel) {
    if (identical(_socket, channel)) _socket = null;
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (_closed || _reconnectTimer?.isActive == true) return;
    _reconnectTimer = Timer(reconnectDelay, _connectEvents);
  }

  @override
  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _reconnectTimer?.cancel();
    final socket = _socket;
    _socket = null;
    if (socket != null) await socket.sink.close();
    _client.close();
    await _events.close();
  }
}

Uri eventReplayUri(
  Uri endpoint,
  int afterSequence, {
  String? instanceId,
}) => endpoint.replace(
  queryParameters: {
    ...endpoint.queryParameters,
    'after_sequence': afterSequence.clamp(0, 0x1fffffffffffff).toString(),
    if (instanceId != null && instanceId.isNotEmpty) 'instance_id': instanceId,
  },
);
