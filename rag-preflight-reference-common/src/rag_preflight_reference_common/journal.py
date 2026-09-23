"""Durable local operation journal and single-process-writer lock."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator


def atomic_json(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(item, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextmanager
def writer_lock(state_root: Path) -> Iterator[None]:
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state_root / 'writer.lock').open('a+b') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def pending(state_root: Path) -> Path:
    return state_root / 'pending-operation.json'


def read_pending(state_root: Path) -> dict[str, Any] | None:
    path = pending(state_root)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
