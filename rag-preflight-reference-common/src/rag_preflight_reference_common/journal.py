"""Durable local operation journal and cross-platform local writer lock."""
from contextlib import contextmanager
import errno
import importlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, BinaryIO, Iterator


_WINDOWS = os.name == 'nt'


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
        # POSIX permits syncing directory metadata after the replace. Windows
        # does not expose a portable directory descriptor through os.open.
        if not _WINDOWS:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextmanager
def _locked_stream(stream: BinaryIO) -> Iterator[None]:
    if not _WINDOWS:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return

    msvcrt: Any = importlib.import_module('msvcrt')
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b'\0')
        stream.flush()
        os.fsync(stream.fileno())
    while True:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError as exc:
            if (exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
                    and getattr(exc, 'winerror', None) not in (33, 36)):
                raise
            time.sleep(0.05)
    try:
        yield
    finally:
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def writer_lock(state_root: Path) -> Iterator[None]:
    """Serialize this application's local writers; this is not a distributed lock."""
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state_root / 'writer.lock').open('a+b') as stream:
        with _locked_stream(stream):
            yield


def pending(state_root: Path) -> Path:
    return state_root / 'pending-operation.json'


def read_pending(state_root: Path) -> dict[str, Any] | None:
    path = pending(state_root)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
