from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "host" / "host_app"))
sys.path.insert(0, str(ROOT / "src" / "d_slam" / "jetson_app"))
