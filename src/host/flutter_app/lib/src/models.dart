import 'dart:convert';

typedef JsonMap = Map<String, dynamic>;

JsonMap requireJsonMap(Object? value, {String context = 'response'}) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((key, item) => MapEntry(key.toString(), item));
  throw FormatException('$context must be a JSON object');
}

List<JsonMap> jsonObjectList(Object? value, {String context = 'items'}) {
  if (value is! List) throw FormatException('$context must be a JSON array');
  return value.map((item) => requireJsonMap(item, context: '$context item')).toList(growable: false);
}

final class ApiEvent {
  const ApiEvent({required this.sequence, required this.eventType, required this.timestamp, required this.payload, this.instanceId});
  factory ApiEvent.fromJson(JsonMap value) {
    final sequence = value['sequence'] ?? value['event_id'];
    final eventType = value['event_type'] ?? value['type'];
    final timestamp = value['timestamp'] ?? value['created_at'] ?? value['occurred_at'] ?? '';
    final instanceId = value['instance_id'] ?? value['process_instance_id'];
    if (sequence is! num || eventType is! String || timestamp is! String) throw const FormatException('invalid API event envelope');
    if (instanceId != null && (instanceId is! String || instanceId.isEmpty)) throw const FormatException('invalid API event instance_id');
    return ApiEvent(sequence: sequence.toInt(), eventType: eventType, timestamp: timestamp, instanceId: instanceId as String?, payload: requireJsonMap(value['payload'] ?? <String, dynamic>{}, context: 'event payload'));
  }
  factory ApiEvent.decode(String text) => ApiEvent.fromJson(requireJsonMap(jsonDecode(text), context: 'event'));
  final int sequence;
  final String eventType;
  final String timestamp;
  final JsonMap payload;
  final String? instanceId;
}

final class ApiEventCursor {
  const ApiEventCursor({this.sequence = 0, this.instanceId});
  final int sequence;
  final String? instanceId;
  ApiEventCursor observe(ApiEvent event) {
    final incomingInstance = event.instanceId;
    if (incomingInstance != null && incomingInstance != instanceId) return ApiEventCursor(sequence: event.sequence, instanceId: incomingInstance);
    return ApiEventCursor(sequence: event.sequence > sequence ? event.sequence : sequence, instanceId: instanceId ?? incomingInstance);
  }
}

final class ApiFailure implements Exception {
  const ApiFailure({required this.method, required this.uri, required this.statusCode, required this.message, this.details});
  final String method;
  final Uri uri;
  final int statusCode;
  final String message;
  final Object? details;
  @override String toString() => 'ApiFailure($statusCode, $method $uri): $message';
}

final class ApiEndpoints {
  ApiEndpoints({required Uri baseUri, Uri? webSocketUri}) : baseUri = _normaliseBase(baseUri), webSocketUri = webSocketUri ?? _webSocketFor(baseUri);
  factory ApiEndpoints.fromEnvironment({String defaultBaseUrl = 'http://127.0.0.1:8080'}) {
    const configuredBase = String.fromEnvironment('API_BASE_URL');
    const configuredSocket = String.fromEnvironment('WS_URL');
    final base = Uri.parse(configuredBase.isEmpty ? defaultBaseUrl : configuredBase);
    return ApiEndpoints(baseUri: base, webSocketUri: configuredSocket.isEmpty ? null : Uri.parse(configuredSocket));
  }
  final Uri baseUri;
  final Uri webSocketUri;
  Uri resolve(String path, [Map<String, Object?> query = const {}]) {
    final clean = path.startsWith('/') ? path.substring(1) : path;
    final resolved = baseUri.resolve(clean);
    if (query.isEmpty) return resolved;
    return resolved.replace(queryParameters: query.map((key, value) => MapEntry(key, value?.toString() ?? '')));
  }
  static Uri _normaliseBase(Uri value) {
    if (!value.hasScheme || value.host.isEmpty) throw ArgumentError.value(value, 'baseUri', 'absolute HTTP URI required');
    final path = value.path.endsWith('/') ? value.path : '${value.path}/';
    return value.replace(path: path, query: null, fragment: null);
  }
  static Uri _webSocketFor(Uri value) {
    final base = _normaliseBase(value);
    return base.replace(scheme: base.scheme == 'https' ? 'wss' : 'ws', path: base.resolve('api/v1/events/ws').path, query: null, fragment: null);
  }
}
