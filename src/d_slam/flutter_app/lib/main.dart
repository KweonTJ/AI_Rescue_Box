import 'package:flutter/material.dart';
import 'package:rescue_api_client/rescue_api_client.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final endpoints=ApiEndpoints.fromEnvironment(defaultBaseUrl:'http://127.0.0.1:8081');
  runApp(JetsonApp(backend:RestJetsonBackend(HttpRescueTransport(endpoints:endpoints))));
}

class JetsonApp extends StatelessWidget {
  const JetsonApp({super.key, required this.backend});
  final JetsonBackend backend;
  @override Widget build(BuildContext context) => MaterialApp(title:'AI Rescue Box Jetson',theme:ThemeData(useMaterial3:true),home=JetsonStatusPage(backend:backend));
}
class JetsonStatusPage extends StatefulWidget { const JetsonStatusPage({super.key,required this.backend}); final JetsonBackend backend; @override State<JetsonStatusPage> createState()=>_JetsonStatusPageState(); }
class _JetsonStatusPageState extends State<JetsonStatusPage> { JsonMap? status; Object? error; @override void initState(){super.initState(); _load();} Future<void> _load() async { try { final value=await widget.backend.status(); if(mounted)setState(()=>status=value); } catch(e){if(mounted)setState(()=>error=e);} } @override Widget build(BuildContext context)=>Scaffold(appBar:AppBar(title:const Text('AI Rescue Box · Jetson')),body:Padding(padding:const EdgeInsets.all(24),child:error!=null?Text('$error'):status==null?const CircularProgressIndicator():SelectableText(status.toString()))); }
