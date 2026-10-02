"""Persistent loopback UI token and derived session-cookie validation."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import stat
from pathlib import Path

COOKIE_NAME = "arena_session"
COOKIE_CONTEXT = b"llm-arena/ui-session/v1"


def token_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "llm-arena" / "ui-token"


def load_ui_token(*, rotate: bool = False, path: Path | None = None) -> str:
    target = path or token_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    if not rotate:
        try:
            token = _read_token(target)
            if token:
                return token
        except FileNotFoundError:
            pass
    token = secrets.token_urlsafe(32)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(6)}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return token


def _read_token(target: Path) -> str:
    descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"UI token path is not a regular file: {target}")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "r", encoding="ascii") as handle:
            descriptor = -1
            token = handle.read(513).strip()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(token) > 512:
        raise ValueError(f"UI token file is unexpectedly large: {target}")
    return token


def session_cookie(token: str) -> str:
    return hmac.new(token.encode("ascii"), COOKIE_CONTEXT, hashlib.sha256).hexdigest()


def token_matches(expected: str, presented: str) -> bool:
    return hmac.compare_digest(expected.encode("utf-8"), presented.encode("utf-8"))


def cookie_matches(token: str, presented: str | None) -> bool:
    if presented is None:
        return False
    return hmac.compare_digest(session_cookie(token), presented)
