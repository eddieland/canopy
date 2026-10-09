"""`canopy-notify-relay`: shows canopy's notifications on a machine canopy does not run on (DESIGN §20).

canopy keeps a mailbox sink's messages in its journal. This program runs on the operator's other machine, the laptop
they sit at, collects those messages over SSH or the web UI's listener, and passes each on stdin to a local sink
command, `canopy-notify-desktop` unless the arguments after `--` name another. It polls, keeps its place in a file of
its own, and passes on nothing older than a day.

    canopy-notify-relay --ssh devbox --remote-cmd 'cd ~/src/api && ~/.local/bin/canopy notify read'
    canopy-notify-relay --url http://127.0.0.1:8765        # with `ssh -L 8765:127.0.0.1:8765 devbox` open

Over SSH it runs `canopy notify read SINK --after ID` on the other machine with `ssh -o BatchMode=yes`, so the
operator's own SSH keys and config are the only credential. Over HTTP it signs in with the listener secret, read from
a file that belongs to the operator and that nobody else can read: `--secret-file PATH`, by default
`$XDG_CONFIG_HOME/canopy/relay-secret`. The secret is never in argv or the environment.

Exit codes: 2 for bad arguments or an unusable secret file, at once. With `--once`, 0 when every message was passed on
and 1 when reading or a local command failed. Without it, it runs until stopped, saying on stderr when reading or
passing on starts or stops failing, and retrying at each poll.

Stdlib only, importing nothing from canopy: it opens connections, which canopy itself never does (D035).
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

PROG = "canopy-notify-relay"
DEFAULT_SINK = "remote"
DEFAULT_COMMAND = ("canopy-notify-desktop",)
DEFAULT_REMOTE_CMD = "canopy notify read"
# canopy's own limits: a sink's name (DESIGN §20) and the listener secret's length (TRUST_MODEL T8).
SINK_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
MIN_SECRET = 32
MAX_SECRET = 512
# What one read returns at most (canopy.core.mailbox.READ_LIMIT): a full read means more may wait.
READ_LIMIT = 50
READ_TIMEOUT_SECONDS = 60
COMMAND_TIMEOUT_SECONDS = 30
MIN_EVERY_SECONDS = 5


class UsageError(Exception):
    """An argument or the secret file is not usable. Exit 2."""


class ReadError(Exception):
    """Reading the mailbox failed this time; the next poll tries again."""


@dataclass(frozen=True)
class Kept:
    """One message canopy kept: its id, when, and the message as its sink's format rendered it."""

    id: int
    at: datetime
    message: str


class Source(Protocol):
    """Where the messages come from."""

    def read(self, after: int | None) -> list[Kept]:
        """The messages after id `after`, oldest first; with None, only the newest."""
        ...


def parse(body: str, sink: str) -> list[Kept]:
    """Read `canopy notify read`'s output, which the HTTP route returns too: `{"sink": ..., "messages": [...]}`."""
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError as e:
        raise ReadError(f"not canopy's mailbox output: {e}") from e
    if not isinstance(parsed, dict) or parsed.get("sink") != sink or not isinstance(parsed.get("messages"), list):
        raise ReadError(f"not canopy's mailbox output for sink {sink!r}")
    found: list[Kept] = []
    for item in parsed["messages"]:
        if not isinstance(item, dict):
            raise ReadError("a mailbox message is not an object")
        kept_id, at, message = item.get("id"), item.get("at"), item.get("message")
        if not isinstance(kept_id, int) or not isinstance(at, str) or not isinstance(message, str):
            raise ReadError("a mailbox message lacks its id, time, or text")
        try:
            when = datetime.fromisoformat(at)
        except ValueError as e:
            raise ReadError(f"a mailbox message's time is not a time: {at!r}") from e
        found.append(Kept(kept_id, when if when.tzinfo else when.replace(tzinfo=UTC), message))
    return found


@dataclass(frozen=True)
class Ssh:
    """Reads by running `canopy notify read` on `host` over SSH."""

    host: str
    remote_cmd: str
    sink: str

    def argv(self, after: int | None) -> list[str]:
        """The ssh command for one read. The sink name and id are checked, so the remote command line is fixed."""
        remote = f"{self.remote_cmd} {self.sink}" + (f" --after {after}" if after is not None else "")
        # BatchMode: never stop to ask for a password or a host key; the operator's agent and known_hosts must do.
        return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "--", self.host, remote]

    def read(self, after: int | None) -> list[Kept]:
        """The messages after `after`, from canopy on the other machine."""
        argv = self.argv(after)
        try:
            result = subprocess.run(  # noqa: S603  (an argv list, no shell here)
                argv, capture_output=True, text=True, timeout=READ_TIMEOUT_SECONDS, check=False
            )
        except FileNotFoundError:
            raise ReadError("ssh is not installed") from None
        except subprocess.TimeoutExpired:
            raise ReadError(f"ssh {self.host} timed out") from None
        if result.returncode != 0:
            raise ReadError(f"ssh {self.host} exited {result.returncode}: {result.stderr.strip()[-500:]}")
        # A shell startup file on the other machine may print first; canopy's answer is the last line.
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        return parse(lines[-1] if lines else "", self.sink)


class Http:
    """Reads from the web UI's `GET /api/mailbox/{sink}`, signed in with the listener secret."""

    def __init__(self, url: str, secret_file: Path, sink: str) -> None:
        """Read from the canopy web UI at `url`, signing in with the secret in `secret_file`."""
        self.url = url
        self.secret_file = secret_file
        self.sink = sink
        self._cookie: str | None = None

    def read(self, after: int | None) -> list[Kept]:
        """The messages after `after`, signing in first if there is no session yet or it has ended."""
        query = f"?after={after}" if after is not None else ""
        target = f"{self.url}/api/mailbox/{self.sink}{query}"
        if self._cookie is None:
            self._sign_in()
        status, body = self._request("GET", target)
        if status == 401:  # noqa: PLR2004  (the session ended: a new secret, or 30 days)
            self._sign_in()
            status, body = self._request("GET", target)
        if status == 404:  # noqa: PLR2004
            raise ReadError(f"canopy at {self.url} has no mailbox sink named {self.sink!r}")
        if status != 200:  # noqa: PLR2004
            raise ReadError(f"canopy at {self.url} answered HTTP {status}: {body[:500]}")
        return parse(body, self.sink)

    def _sign_in(self) -> None:
        secret = read_secret(self.secret_file)
        status, body = self._request("POST", f"{self.url}/api/session", {"secret": secret})
        if status == 401:  # noqa: PLR2004
            raise ReadError(f"canopy at {self.url} refused the secret in {self.secret_file}; copy it again")
        if status != 200 or self._cookie is None:  # noqa: PLR2004
            raise ReadError(f"signing in to canopy at {self.url} failed: HTTP {status}: {body[:500]}")

    def _request(self, method: str, url: str, payload: dict[str, str] | None = None) -> tuple[int, str]:
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if self._cookie is not None:
            headers["Cookie"] = self._cookie
        # `check_url` allowed only http and https.
        request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=READ_TIMEOUT_SECONDS) as response:  # noqa: S310
                self._keep_cookie(response.headers.get_all("Set-Cookie") or [])
                return int(response.status), response.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ReadError(f"cannot reach canopy at {self.url}: {e}") from e

    def _keep_cookie(self, headers: list[str]) -> None:
        # canopy's session cookie is the one it sets (`canopy_session_<port>`); only its name and value are sent back.
        for header in headers:
            pair = header.split(";", 1)[0].strip()
            if pair.startswith("canopy_session_") and "=" in pair:
                self._cookie = pair


def read_secret(path: Path) -> str:
    """Return the listener secret in `path`, which must be the operator's alone, as canopy checks its own copy.

    Raises:
        UsageError: the file is missing, a symlink or not a regular file, someone else's, open to others, or does not
            hold one line of 32 to 512 characters without spaces.
    """
    try:
        st = path.lstat()
    except OSError as e:
        raise UsageError(f"cannot read the secret file {path}: {e.strerror}; copy the listener secret there") from e
    if not stat.S_ISREG(st.st_mode):
        raise UsageError(f"the secret file {path} is not a regular file (a symlink is refused)")
    if st.st_uid != os.getuid():
        raise UsageError(f"the secret file {path} belongs to someone else; it must be yours")
    if st.st_mode & 0o077:
        raise UsageError(f"the secret file {path} is open to others; run: chmod 600 {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding="utf-8", errors="replace") as f:
        text = f.read(MAX_SECRET + 2).strip()
    if not MIN_SECRET <= len(text) <= MAX_SECRET or not text.isprintable() or any(c.isspace() for c in text):
        raise UsageError(f"the secret file {path} must hold the listener secret (`canopy secret` prints it)")
    return text


def check_url(url: str) -> tuple[str, bool]:
    """Return the web UI's base URL without a trailing slash, and whether it is reached over plain HTTP off loopback.

    Raises:
        UsageError: not an http or https URL with a host, or it carries a user, query, or fragment.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        _ = parts.port  # raises on a malformed port
    except ValueError as e:
        raise UsageError(f"--url {url!r} is not a URL: {e}") from e
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise UsageError(f"--url {url!r} must be http:// or https:// with a host")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise UsageError(f"--url {url!r} must not carry a user, query, or fragment")
    return url.rstrip("/"), parts.scheme == "http" and not _loopback(parts.hostname)


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def default_secret_file() -> Path:
    """`$XDG_CONFIG_HOME/canopy/relay-secret`, or `~/.config/canopy/relay-secret`."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "canopy" / "relay-secret"


def default_state_file(sink: str, where: str) -> Path:
    """Where the relay keeps its place for `sink` at `where`: under `$XDG_STATE_HOME`, or `~/.local/state`."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", where).strip("_") or "canopy"
    return Path(base).expanduser() / "canopy" / "relay" / f"{sink}@{slug}"


def load_cursor(path: Path) -> int | None:
    """The id of the last message passed on or skipped, or None before the first."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise UsageError(f"cannot read the state file {path}: {e.strerror}") from e
    return int(text) if text.isdigit() else None


def save_cursor(path: Path, cursor: int) -> None:
    """Keep the relay's place, replacing the file whole so a stop never leaves half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(f"{cursor}\n", encoding="utf-8")
    tmp.replace(path)


def pass_on(command: Sequence[str], message: str) -> str | None:
    """Run the local sink command with `message` on stdin. Returns None on exit 0, else why it failed."""
    try:
        result = subprocess.run(  # noqa: S603  (the operator's argv, no shell)
            list(command), input=message, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS, check=False
        )
    except FileNotFoundError:
        return f"{command[0]} is not installed"
    except subprocess.TimeoutExpired:
        return f"{command[0]} timed out"
    if result.returncode != 0:
        tail = result.stderr.strip()[-500:]
        return f"{command[0]} exited {result.returncode}" + (f": {tail}" if tail else "")
    return None


@dataclass(frozen=True)
class Poll:
    """What one poll did: messages passed on, messages too old to pass on, and the failure that stopped it."""

    shown: int
    skipped: int
    error: str | None


def poll(
    source: Source,
    state_file: Path,
    command: Sequence[str],
    *,
    max_age: timedelta,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Poll:
    """Read every message after the relay's place and pass each on in order, moving the place past each.

    A message older than `max_age` is skipped. A failed local command stops the poll at that message, so the next poll
    tries it again, until it is too old.
    """
    shown = skipped = 0
    cursor = load_cursor(state_file)
    while True:
        first = cursor is None
        try:
            batch = source.read(cursor)
        except ReadError as e:
            return Poll(shown, skipped, str(e))
        for kept in batch:
            if now() - kept.at > max_age:
                skipped += 1
            else:
                failure = pass_on(command, kept.message)
                if failure is not None:
                    return Poll(shown, skipped, failure)
                shown += 1
            cursor = kept.id
            save_cursor(state_file, cursor)
        # Without a place, a read returns the newest message alone; after it, a short read is the end.
        if first or len(batch) < READ_LIMIT:
            return Poll(shown, skipped, None)


def parser() -> argparse.ArgumentParser:
    """The command's arguments."""
    p = argparse.ArgumentParser(
        prog=PROG,
        description=__doc__.split("\n", 1)[0] if __doc__ else None,
        usage=f"{PROG} (--ssh HOST | --url URL) [options] [-- COMMAND ...]",
    )
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--ssh", metavar="HOST", help="read over SSH from HOST (an ssh destination or config alias)")
    where.add_argument("--url", help="read from canopy's web UI at URL, e.g. http://127.0.0.1:8765")
    p.add_argument("--sink", default=DEFAULT_SINK, help=f"the mailbox sink's name in canopy's config [{DEFAULT_SINK}]")
    p.add_argument(
        "--remote-cmd",
        default=DEFAULT_REMOTE_CMD,
        help=f"with --ssh, the remote shell command that runs canopy in a repository [{DEFAULT_REMOTE_CMD}]",
    )
    p.add_argument(
        "--secret-file", type=Path, help="with --url, the listener secret's file [~/.config/canopy/relay-secret]"
    )
    p.add_argument(
        "--state-file", type=Path, help="where to keep the relay's place [under ~/.local/state/canopy/relay]"
    )
    p.add_argument("--every", type=int, default=60, metavar="SECONDS", help="seconds between polls [60]")
    p.add_argument("--max-age-hours", type=int, default=24, metavar="HOURS", help="skip older messages [24]")
    p.add_argument("--once", action="store_true", help="poll once and exit")
    p.add_argument("command", nargs=argparse.REMAINDER, help="the local sink command [canopy-notify-desktop]")
    return p


@dataclass(frozen=True)
class Setup:
    """The parsed arguments, checked."""

    source: Source
    state_file: Path
    command: tuple[str, ...]
    every: int
    max_age: timedelta
    once: bool
    warning: str | None


def setup(argv: Sequence[str]) -> Setup:
    """Parse and check `argv`.

    Raises:
        UsageError: an argument or the secret file is not usable.
    """
    args = parser().parse_args(argv)
    sink: str = args.sink
    if not SINK_NAME_RE.fullmatch(sink):
        raise UsageError(f"--sink {sink!r} must match {SINK_NAME_RE.pattern}, as canopy's sink names do")
    every: int = args.every
    if every < MIN_EVERY_SECONDS:
        raise UsageError(f"--every must be at least {MIN_EVERY_SECONDS} seconds")
    hours: int = args.max_age_hours
    if hours < 1:
        raise UsageError("--max-age-hours must be at least 1")
    raw: list[str] = args.command
    command = tuple(raw[1:] if raw[:1] == ["--"] else raw) or DEFAULT_COMMAND
    warning = None
    source: Source
    if args.ssh is not None:
        host: str = args.ssh
        if not host or host.startswith("-") or any(c.isspace() for c in host):
            raise UsageError(f"--ssh {host!r} must be a host or ssh config alias")
        source, where = Ssh(host, args.remote_cmd, sink), host
    else:
        url, plain = check_url(args.url)
        secret_file: Path = args.secret_file or default_secret_file()
        read_secret(secret_file)
        source, where = Http(url, secret_file, sink), urllib.parse.urlsplit(url).netloc
        if plain:
            warning = f"{url} is plain HTTP off this machine: the network can read it. An SSH forward is safer."
    state_file: Path = args.state_file or default_state_file(sink, where)
    load_cursor(state_file)
    return Setup(source, state_file, command, every, timedelta(hours=hours), args.once, warning)


def _say(text: str) -> None:
    stamp = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{PROG}: {stamp} {text}", file=sys.stderr, flush=True)  # noqa: T201


def run(argv: Sequence[str], *, sleep: Callable[[float], None] = time.sleep) -> int:
    """Run the relay with `argv`. Returns the exit code."""
    try:
        s = setup(argv)
    except UsageError as e:
        print(f"{PROG}: {e}", file=sys.stderr)  # noqa: T201
        return 2
    if s.warning:
        _say(s.warning)
    last_error: str | None = None
    while True:
        try:
            result = poll(s.source, s.state_file, s.command, max_age=s.max_age)
        except UsageError as e:
            print(f"{PROG}: {e}", file=sys.stderr)  # noqa: T201
            return 2
        if result.shown or result.skipped:
            _say(f"passed on {result.shown}, skipped {result.skipped} older than {s.max_age.total_seconds() / 3600:g}h")
        if result.error != last_error:
            _say(f"failing: {result.error}" if result.error else "working again")
            last_error = result.error
        if s.once:
            return 1 if result.error else 0
        sleep(s.every)


def main() -> int:
    """The `canopy-notify-relay` command."""
    try:
        return run(sys.argv[1:])
    except KeyboardInterrupt:
        return 130
