"""Small atomic file helpers used by app-owned data directories."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping


def atomic_write_bytes(path: Path, content: bytes, *, overwrite: bool = False) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".part", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if path.exists() and not overwrite:
            raise FileExistsError(path)
        os.replace(temporary, path)
        return path
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(
    path: Path, value: Mapping[str, Any], *, overwrite: bool = False
) -> Path:
    content = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ).encode("utf-8") + b"\n"
    return atomic_write_bytes(path, content, overwrite=overwrite)


def atomic_copy(source: Path, destination: Path, *, overwrite: bool = False) -> Path:
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}-", suffix=".part", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as input_file, temporary.open("wb") as output_file:
            shutil.copyfileobj(input_file, output_file, 1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        if destination.exists() and not overwrite:
            raise FileExistsError(destination)
        os.replace(temporary, destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
