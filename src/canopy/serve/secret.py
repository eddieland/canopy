"""The listener secret (TRUST_MODEL T8, DESIGN §22): an operator-only file the web UI's sign-in checks against.

Kept free of the web stack, so `canopy secret` imports nothing it does not need. The secret is never in config, the
journal, logs, or prompts: the loop reads it once when it starts serving, and `canopy secret` prints it to the
operator's terminal.
"""

from __future__ import annotations

import os
import secrets
import stat
from typing import TYPE_CHECKING

from canopy.core import config
from canopy.infra import logs

if TYPE_CHECKING:
    from pathlib import Path

FILE_NAME = "listener-secret"
MIN_LENGTH = 32
# Anything longer is not a secret canopy wrote, and is refused rather than read whole.
MAX_LENGTH = 512


class SecretError(Exception):
    """The secret file is missing or unsafe to use. The message says which, and how to fix it."""


def path() -> Path:
    """`listener-secret` in the user config directory, next to `config.toml`.

    Returns:
        The file's path. It may not exist.
    """
    return config.user_config_dir() / FILE_NAME


def read(file: Path) -> str:
    """Return the secret in `file`, after checking the file is the operator's alone.

    Raises:
        SecretError: there is no file, it is a symlink or not a regular file, it is someone else's, others may read or
            write it, or it does not hold one line of at least 32 printable characters without spaces.
    """
    try:
        st = file.lstat()
    except FileNotFoundError:
        raise SecretError(f"there is no listener secret at {file}; make one with `canopy secret`") from None
    if not stat.S_ISREG(st.st_mode):
        raise SecretError(f"{file} is not a regular file (a symlink is refused); remove it and run `canopy secret`")
    if st.st_uid != os.getuid():
        raise SecretError(f"{file} is not yours; remove it and run `canopy secret`")
    if st.st_mode & 0o077:
        raise SecretError(
            f"{file} can be read or written by others; run `chmod 600 {file}`, or `canopy secret --rotate`"
        )
    fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding="utf-8", errors="replace") as f:
        text = f.read(MAX_LENGTH + 2).strip()
    if not MIN_LENGTH <= len(text) <= MAX_LENGTH or not text.isprintable() or any(c.isspace() for c in text):
        raise SecretError(
            f"{file} must hold one line of {MIN_LENGTH} to {MAX_LENGTH} characters without spaces; "
            "run `canopy secret --rotate` for a new one"
        )
    return text


def create(file: Path, *, rotate: bool) -> tuple[str, bool]:
    """Return the secret in `file`, writing a new one first if there is none or `rotate` is set. The bool: written.

    A new secret is 32 random bytes in URL-safe base64, in a file only the operator can read. Rotating it signs every
    browser out, since every session cookie is signed with the old one.

    Raises:
        SecretError: without `rotate`, the file exists but `read` refuses it.
    """
    if not rotate and (file.exists() or file.is_symlink()):
        return read(file), False
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if file.is_symlink():
        file.unlink()
    value = secrets.token_urlsafe(32)
    logs.write_private(file, value + "\n")
    return value, True
