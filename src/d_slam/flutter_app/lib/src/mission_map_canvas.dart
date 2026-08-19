part of 'jetson_app.dart';

class _MissionMapCanvas extends StatefulWidget {
  const _MissionMapCanvas({required this.controller, required this.baseMapBytes, required this.previewBytes});
  final JetsonController controller;
  final Uint8List? baseMapBytes;
  final Uint8List? previewBytes;
  @override State<_MissionMapCanvas> createState() => _MissionMapCanvasState();
}

class _MissionMapCanvasState extends State<_MissionMapCanvas> {
  ImageInfo? _baseInfo;
  ImageInfo? _previewInfo;
  ImageStream? _baseStream;
  ImageStream? _previewStream;
  ImageStreamListener? _baseListener;
  ImageStreamListener? _previewListener;
  Uint8List? _decodedBase;
  Uint8List? _decodedPreview;

  @override void didChangeDependencies() { super.didChangeDependencies(); _decodeImages(); }
  @override void didUpdateWidget(covariant _MissionMapCanvas oldWidget) { super.didUpdateWidget(oldWidget); if (!identical(oldWidget.baseMapBytes,widget.baseMapBytes)||!identical(oldWidget.previewBytes,widget.previewBytes)) _decodeImages(); }

  void _decodeImages() {
    _resolve(widget.baseMapBytes,previousBytes:_decodedBase,currentStream:_baseStream,currentListener:_baseListener,update:(stream,listener,info,bytes){_baseStream=stream;_baseListener=listener;_baseInfo=info;_decodedBase=bytes;});
    _resolve(widget.previewBytes,previousBytes:_decodedPreview,currentStream:_previewStream,currentListener:_previewListener,update:(stream,listener,info,bytes){_previewStream=stream;_previewListener=listener;_previewInfo=info;_decodedPreview=bytes;});
  }

  void _resolve(Uint8List? bytes,{required Uint8List? previousBytes,required ImageStream? currentStream,required ImageStreamListener? currentListener,required void Function(ImageStream? stream,ImageStreamListener? listener,ImageInfo? info,Uint8List? bytes) update}) {
    if (identical(bytes,previousBytes)) return;
    if (currentStream!=null&&currentListener!=null) currentStream.removeListener(currentListener);
    if (bytes==null) { update(null,null,null,null); return; }
    final stream=MemoryImage(bytes).resolve(createLocalImageConfiguration(context));
    late final ImageStreamListener listener;
    listener=ImageStreamListener((info,_){ if(!mounted)return; setState(()=>update(stream,listener,info,bytes)); });
    stream.addListener(listener); update(stream,listener,null,bytes);
  }

  @override void dispose() { if(_baseStream!=null&&_baseListener!=null)_baseStream!.removeListener(_baseListener!); if(_previewStream!=null&&_previewListener!=null)_previewStream!.removeListener(_previewListener!); super.dispose(); }

  @override Widget build(BuildContext context) {
    final mission=widget.controller.selectedMission;
    final manifest=_asMap(mission?['manifest'])??mission;
    final projection=_MissionProjection.fromManifest(manifest);
    return AspectRatio(aspectRatio:math.max(1,projection.imageWidth/projection.imageHeight),child:LayoutBuilder(builder:(context,constraints)=>CustomPaint(painter:_MissionMapPainter(projection:projection,baseMap:_baseInfo?.image,preview:_previewInfo?.image,manifest:manifest,result:widget.controller.currentResult,approvedPlan:widget.controller.approvedPlan,previewMetadata:widget.controller.preview),child:const SizedBox.expand())));
  }
}

class _MissionMapPainter extends CustomPainter {
  const _MissionMapPainter({required this.projection,required this.baseMap,required this.preview,required this.manifest,required this.result,required this.approvedPlan,required this.previewMetadata});
  final _MissionProjection projection;
  final ui.Image? baseMap;
  final ui.Image? preview;
  final JsonMap? manifest;
  final JsonMap? result;
  final JsonMap? approvedPlan;
  final JsonMap? previewMetadata;

  @override void paint(Canvas canvas,Size size) {
    final sourceSize=Size(projection.imageWidth,projection.imageHeight);
    final destination=_containRect(sourceSize,Offset.zero&size);
    canvas.drawRect(Offset.zero&size,Paint()..color=const Color(0xff071012));
    final baseImage=baseMap;
    if(baseImage!=null){canvas.drawImageRect(baseImage,Rect.fromLTWH(0,0,baseImage.width.toDouble(),baseImage.height.toDouble()),destination,Paint());}else{canvas.drawRect(destination,Paint()..color=const Color(0xff182a2d));}
    final previewImage=preview;
    if(previewImage!=null){canvas.drawImageRect(previewImage,Rect.fromLTWH(0,0,previewImage.width.toDouble(),previewImage.height.toDouble()),destination,Paint()..color=Colors.white.withValues(alpha:0.28));}
    _SemanticMapPainter(projection:projection,manifest:manifest,result:result,approvedPlan:approvedPlan,previewMetadata:previewMetadata,sourceRect:Rect.fromLTWH(0,0,projection.imageWidth,projection.imageHeight),destinationRect:destination).paint(canvas,size);
  }

  Rect _containRect(Size source,Rect destination){final scale=math.min(destination.width/source.width,destination.height/source.height);final width=source.width*scale;final height=source.height*scale;return Rect.fromLTWH(destination.left+(destination.width-width)/2,destination.top+(destination.height-height)/2,width,height);}
  @override bool shouldRepaint(covariant _MissionMapPainter oldDelegate)=>oldDelegate.baseMap!=baseMap||oldDelegate.preview!=preview||oldDelegate.manifest!=manifest||oldDelegate.result!=result||oldDelegate.approvedPlan!=approvedPlan||oldDelegate.previewMetadata!=previewMetadata;
}
