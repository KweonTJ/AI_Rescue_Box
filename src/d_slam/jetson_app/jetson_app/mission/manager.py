from __future__ import annotations
import json, os, shutil, uuid
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from ..domain import MissionManifest, StaleVersionError, ValidationError, utc_now
from .artifacts import validate_approved_plan, validate_semantic_result

def _sha256(path: Path) -> str:
    import hashlib
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

class MissionManager:
    def __init__(self, root: Path, *, max_map_bytes: int=10*1024*1024, max_json_bytes: int=2*1024*1024) -> None:
        self.root=Path(root); self.max_map_bytes=max_map_bytes; self.max_json_bytes=max_json_bytes
    def mission_directory(self, mission_id: str, version: int) -> Path: return self.root/mission_id/f"v{version}"
    def latest_mission_version(self, mission_id: str):
        root=self.root/mission_id
        versions=[int(p.name[1:]) for p in root.glob('v[0-9]*') if p.is_dir() and p.name[1:].isdigit()] if root.is_dir() else []
        return max(versions,default=None)
    def list_missions(self):
        if not self.root.is_dir(): return ()
        result=[]
        for mission in self.root.iterdir():
            if mission.is_dir():
                for version in mission.glob('v[0-9]*'):
                    if version.is_dir() and version.name[1:].isdigit(): result.append((mission.name,int(version.name[1:])))
        return tuple(sorted(result))
    def apply_mission(self, manifest_path: Path, base_map_path: Path):
        manifest=MissionManifest.from_dict(json.loads(Path(manifest_path).read_text(encoding='utf-8'))); source=Path(base_map_path)
        if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= self.max_map_bytes: raise ValidationError('invalid base map file')
        if _sha256(source) != manifest.base_map_sha256: raise ValidationError('base map SHA-256 does not match mission manifest')
        try:
            with Image.open(source) as image: image.verify()
            with Image.open(source) as image: size=image.size; fmt=image.format
        except (OSError,UnidentifiedImageError) as error: raise ValidationError('base map is not a valid image') from error
        if size != (manifest.base_map_width,manifest.base_map_height) or fmt not in {'JPEG','PNG'}: raise ValidationError('base map metadata mismatch')
        latest=self.latest_mission_version(manifest.mission_id)
        if latest is not None and manifest.mission_version <= latest: raise StaleVersionError('mission version is not newer')
        destination=self.mission_directory(manifest.mission_id,manifest.mission_version); destination.parent.mkdir(parents=True,exist_ok=True)
        staging=destination.parent/f".{destination.name}.{uuid.uuid4().hex}.part"; staging.mkdir()
        try:
            stored=staging/('base_map.jpg' if fmt=='JPEG' else 'base_map.png'); shutil.copyfile(source,stored)
            (staging/'mission_manifest.json').write_text(json.dumps(manifest.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
            (staging/'verification.json').write_text(json.dumps({'verified_at':utc_now(),'status':'verified','base_map_sha256':_sha256(stored)},indent=2),encoding='utf-8')
            os.replace(staging,destination)
        except Exception:
            shutil.rmtree(staging,ignore_errors=True); raise
        return destination
    def load_mission(self, mission_id: str, version: int|None=None):
        selected=version or self.latest_mission_version(mission_id)
        if selected is None: raise ValidationError('mission is not stored')
        path=self.mission_directory(mission_id,selected)/'mission_manifest.json'
        return MissionManifest.from_dict(json.loads(path.read_text(encoding='utf-8')))
