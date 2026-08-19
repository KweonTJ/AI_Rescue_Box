"""Conservative OccupancyGrid preview generation."""
from __future__ import annotations
import hashlib,io,math
from dataclasses import dataclass
from PIL import Image,PngImagePlugin
from .providers import SlamSnapshot
@dataclass(frozen=True)
class RenderedMapPreview:
    png:bytes; content_signature:str; width:int; height:int
class OccupancyPreviewRenderer:
    FREE_COLOR=(248,250,252); UNCERTAIN_COLOR=(245,158,11); UNKNOWN_COLOR=(124,58,237); OCCUPIED_COLOR=(17,24,39)
    def __init__(self,*,occupied_threshold:int=65,max_dimension:int=768)->None:
        if not 0<=occupied_threshold<=100: raise ValueError("occupied_threshold must be in [0, 100]")
        if max_dimension<=0: raise ValueError("max_dimension must be positive")
        self.occupied_threshold=occupied_threshold; self.max_dimension=max_dimension
    def render(self,snapshot:SlamSnapshot,*,mission_id:str|None=None,base_map_version:int|None=None,artifact_version:int|None=None)->RenderedMapPreview:
        grid=snapshot.occupancy_grid; scale=max(1,math.ceil(max(grid.width,grid.height)/self.max_dimension)); width=math.ceil(grid.width/scale); height=math.ceil(grid.height/scale); pixels=[]
        for image_y in range(height):
            block_y=height-image_y-1; y_start=block_y*scale; y_stop=min(grid.height,y_start+scale)
            for image_x in range(width):
                x_start=image_x*scale; x_stop=min(grid.width,x_start+scale); values=[grid.value(x,y) for y in range(y_start,y_stop) for x in range(x_start,x_stop)]
                pixels.append(self.OCCUPIED_COLOR if any(v>=self.occupied_threshold for v in values) else self.UNKNOWN_COLOR if any(v==-1 for v in values) else self.UNCERTAIN_COLOR if any(v>0 for v in values) else self.FREE_COLOR)
        image=Image.new("RGB",(width,height)); image.putdata(pixels); pixel_content=image.tobytes(); geometry=f"{width}x{height}|{grid.width}x{grid.height}|{grid.resolution:.17g}|{grid.origin.x:.17g},{grid.origin.y:.17g}|{grid.frame_id}|threshold={self.occupied_threshold}".encode(); signature=hashlib.sha256(geometry+b"\0"+pixel_content).hexdigest(); metadata=PngImagePlugin.PngInfo(); metadata.add_text("frame_id",grid.frame_id); metadata.add_text("resolution_m_per_cell",f"{grid.resolution:.17g}"); metadata.add_text("origin_x_m",f"{grid.origin.x:.17g}"); metadata.add_text("origin_y_m",f"{grid.origin.y:.17g}"); metadata.add_text("map_version",str(snapshot.map_version)); metadata.add_text("content_signature",signature)
        if mission_id is not None: metadata.add_text("mission_id",mission_id)
        if base_map_version is not None: metadata.add_text("base_map_version",str(base_map_version))
        if artifact_version is not None: metadata.add_text("artifact_version",str(artifact_version))
        output=io.BytesIO(); image.save(output,format="PNG",pnginfo=metadata,compress_level=9); return RenderedMapPreview(output.getvalue(),signature,width,height)
