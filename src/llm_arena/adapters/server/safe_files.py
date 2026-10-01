"""Safe input writing and artifact collection for model-code work directories."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 20 * 1024 * 1024
MAX_WORKDIR_BYTES = 100 * 1024 * 1024


def validate_relative_name(name: str) -> PurePosixPath:
    """Accept portable relative file names without traversal or ambiguous components."""
    if not name or "\\" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError(f"invalid sandbox file name: {name!r}")
    parts = name.split("/")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in parts) or PureWindowsPath(name).drive:
        raise ValueError(f"invalid sandbox file name: {name!r}")
    return path


def write_inputs(root: Path, files: dict[str, bytes | str]) -> None:
    for name, content in files.items():
        relative = validate_relative_name(name)
        target = root.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)


def collect_artifacts(
    root: Path,
    patterns: tuple[str, ...],
) -> tuple[dict[str, bytes], dict[str, str]]:
    """Collect regular files without following links created by untrusted code."""
    if _workdir_size_exceeds(root, MAX_WORKDIR_BYTES):
        return {}, {"<workdir>": f"work directory exceeds {MAX_WORKDIR_BYTES} bytes"}

    files: dict[str, bytes] = {}
    omitted: dict[str, str] = {}
    total = 0
    seen: set[str] = set()
    for pattern in patterns:
        for candidate in root.glob(pattern):
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                continue
            name = relative.as_posix()
            if name in seen:
                continue
            seen.add(name)
            try:
                data = _read_regular_file(root, relative)
            except (OSError, ValueError) as exc:
                omitted[name] = _safe_reason(exc)
                continue
            if len(data) > MAX_ARTIFACT_BYTES:
                omitted[name] = f"file exceeds {MAX_ARTIFACT_BYTES} bytes"
                continue
            if total + len(data) > MAX_ARTIFACT_TOTAL_BYTES:
                omitted[name] = f"execution artifacts exceed {MAX_ARTIFACT_TOTAL_BYTES} bytes"
                continue
            files[name] = data
            total += len(data)
    return files, omitted


def _read_regular_file(root: Path, relative: Path) -> bytes:
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError("invalid artifact path")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    descriptors: list[int] = []
    try:
        current = os.open(root, os.O_RDONLY | directory)
        descriptors.append(current)
        for part in relative.parts[:-1]:
            current = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=current)
            descriptors.append(current)
        file_fd = os.open(relative.parts[-1], os.O_RDONLY | nofollow, dir_fd=current)
        descriptors.append(file_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("not a regular file")
        if info.st_size > MAX_ARTIFACT_BYTES:
            raise ValueError(f"file exceeds {MAX_ARTIFACT_BYTES} bytes")
        with os.fdopen(os.dup(file_fd), "rb") as handle:
            return handle.read(MAX_ARTIFACT_BYTES + 1)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _workdir_size_exceeds(root: Path, limit: int) -> bool:
    total = 0
    for current, directories, names in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if not (base / name).is_symlink()]
        for name in names:
            try:
                info = os.lstat(base / name)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > limit:
                    return True
    return False


def _safe_reason(exc: OSError | ValueError) -> str:
    if isinstance(exc, ValueError):
        return str(exc)
    if exc.errno == errno.ELOOP:
        return "symlinks are not collected"
    return "not a safe regular file"
