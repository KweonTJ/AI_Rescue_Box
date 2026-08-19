from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while block := source.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def _temporary_path(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)
    os.close(descriptor)
    return Path(name)


def atomic_write_bytes(destination: Path, content: bytes) -> Path:
    destination = Path(destination)
    partial = _temporary_path(destination)
    try:
        with partial.open("wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def atomic_write_json(destination: Path, value: Any) -> Path:
    return atomic_write_bytes(destination, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def atomic_copy(source: Path, destination: Path, max_bytes: int | None = None) -> Path:
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError("artifact source must be a regular non-symlink file")
    if max_bytes is not None and source.stat().st_size > max_bytes:
        raise ValueError(f"artifact exceeds maximum size of {max_bytes} bytes")
    partial = _temporary_path(destination)
    try:
        with source.open("rb") as input_file, partial.open("wb") as output_file:
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination
