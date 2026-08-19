import 'package:flutter_test/flutter_test.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

void main() {
  test('event cursor resets on process epoch change', () {
    const first=ApiEvent(sequence:10,eventType:'a',timestamp:'t',payload:{},instanceId:'one');
    const second=ApiEvent(sequence:1,eventType:'b',timestamp:'t',payload:{},instanceId:'two');
    expect(const ApiEventCursor().observe(first).observe(second).sequence,1);
  });
}
