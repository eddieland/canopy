"""canopy's Jira programs (DESIGN §30): `canopy-connect-jira` reads Jira Cloud into canopy's journal.

canopy runs it as a command, never imports it, so the harness holds no token and opens no connection (TRUST_MODEL T2,
D003). It talks to Jira Cloud's REST API at the one site the operator names, with an email and API token read from a
file of the operator's that nobody else can read, held to the Slack sink's checks (§20): never from argv, the
environment, or canopy's config. This module holds the site, the credentials, the client, and the reading of what
Jira sends: its times and its rich text (Atlassian Document Format).

click (D025), canopy-http for every request (D130), and nothing from canopy.
"""

from __future__ import annotations

import base64
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TextIO

import canopy_http

#: How long a read Jira answered with a server error, or whose reply broke off, waits before each new try: one try,
#: then one more for each pause. Every request this program makes is a read (canopy-http).
RETRY_PAUSES: Final[Sequence[float]] = (1.0, 3.0)
#: How much of a description's or comment's text is printed. canopy bounds what it records again.
MAX_BODY: Final = 8000
#: How deep a document's nodes are read: Jira's own documents nest a few levels, and a deeper one is cut there.
_MAX_DEPTH: Final = 50
_HOST: Final = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::[0-9]{1,5})?")

#: The site's host, to the base URL its REST API is under.
Endpoint = Callable[[str], str]


class InputError(Exception):
    """What the program was given cannot be used, so it did nothing. Exit 2."""


class JiraError(Exception):
    """Jira refused a request, answered with something not the shape asked for, or could not be reached."""


def parse_site(site: str) -> str:
    """Read the operator's Jira site, `acme.atlassian.net` or `https://acme.atlassian.net`.

    Only a host is taken: a path, query, user, or a scheme but https would send the credentials somewhere the
    operator did not name.

    Returns:
        The site's host, in lower case.

    Raises:
        InputError: `site` is not such a site.
    """
    given = site.strip().removesuffix("/")
    host = given.removeprefix("https://")
    if "://" in host or not _HOST.fullmatch(host):
        raise InputError(f"{site!r} is not a Jira site; give its host, such as acme.atlassian.net")
    return host.lower()


def endpoint(host: str) -> str:
    """The base URL of a site's REST API.

    Returns:
        `https://HOST`.
    """
    return f"https://{host}"


def default_credentials_file() -> Path:
    """`$XDG_CONFIG_HOME/canopy/jira-credentials`, or `~/.config/canopy/jira-credentials`.

    Returns:
        The path, whether or not the file exists.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "canopy" / "jira-credentials"


def read_credentials(path: Path) -> tuple[str, str]:
    """Read the email and API token in `path`, one line `EMAIL:TOKEN`, from a regular file of the operator's.

    The file is held to the Slack sink's checks (DESIGN §20): it belongs to the operator, and nobody else can read it.
    No error quotes its text.

    Returns:
        The email and the token.

    Raises:
        InputError: The file cannot be read, is not a regular file, belongs to someone else, is readable by others,
            or does not hold one `EMAIL:TOKEN` line.
    """
    try:
        st = path.stat()
    except OSError as e:
        raise InputError(f"cannot read the credentials file {path}: {e.strerror}") from e
    # Checked before reading: opening a FIFO would block.
    if not stat.S_ISREG(st.st_mode):
        raise InputError(f"the credentials file {path} is not a regular file")
    if st.st_uid != os.getuid():
        raise InputError(f"the credentials file {path} belongs to someone else; it must be yours")
    if st.st_mode & 0o077:
        raise InputError(f"the credentials file {path} is readable by others; run: chmod 600 {path}")
    try:
        found = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as e:
        raise InputError(f"cannot read the credentials file {path}: {e}") from e
    # An API token has no colon; an email in practice has none either, but the token is what follows the last one.
    email, _, token = found.rpartition(":")
    # ASCII, since both go in a header.
    if not email or not token or not all(_header_safe(part) for part in (email, token)):
        raise InputError(f"the credentials file {path} must hold one line, EMAIL:API_TOKEN")
    return email, token


def _header_safe(value: str) -> bool:
    return value.isascii() and not any(c.isspace() or not c.isprintable() for c in value)


class Client:
    """Jira Cloud's REST API at one site, with one email and API token, sent there alone (canopy-http)."""

    def __init__(self, base: str, email: str, token: str) -> None:
        """Talk to the REST API under `base` as `email`, with `token`."""
        auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        headers = {"Authorization": f"Basic {auth}", "User-Agent": "canopy-jira"}
        retry = canopy_http.Retry(pauses=RETRY_PAUSES)
        self._http = canopy_http.Client(base, name="Jira", headers=headers, retry=retry)

    def get(self, path: str, params: Mapping[str, str | int]) -> Mapping[str, object]:
        """GET `path` with `params` in its query.

        Returns:
            The reply, a JSON object.

        Raises:
            JiraError: Jira refused it, its reply is not a JSON object, or it could not be reached.
        """
        return self._send("GET", path, params={k: str(v) for k, v in params.items()})

    def post(self, path: str, body: Mapping[str, object]) -> Mapping[str, object]:
        """POST `body` as JSON to `path`. Jira's searches are posts; nothing here writes.

        Returns:
            The reply, a JSON object.

        Raises:
            JiraError: Jira refused it, its reply is not a JSON object, or it could not be reached.
        """
        return self._send("POST", path, body=dict(body))

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: object = None,
    ) -> Mapping[str, object]:
        """Send one read, sent again as canopy-http sends a read.

        Returns:
            The reply, a JSON object.

        Raises:
            JiraError: Jira refused it, its reply is not a JSON object, or it could not be reached.
        """
        try:
            parsed = self._http.json(method, path, params=params, body=body, again=True)
        except canopy_http.HttpError as e:
            raise JiraError(str(e)) from e
        return obj(parsed, "reply")


def obj(value: object, what: str) -> Mapping[str, object]:
    """`value` as a JSON object.

    Returns:
        The object, with string keys.

    Raises:
        JiraError: `value` is not an object, so Jira's reply is not the shape asked for.
    """
    if not isinstance(value, dict):
        raise JiraError(f"Jira's reply has no {what}")
    return {str(k): v for k, v in value.items()}


def items(value: object) -> list[Mapping[str, object]]:
    """`value` as a JSON array of objects: what is not an object is left out, and anything but an array is empty.

    Returns:
        The objects.
    """
    if not isinstance(value, list):
        return []
    return [{str(k): v for k, v in item.items()} for item in value if isinstance(item, dict)]


def field(value: object, *path: str) -> object:
    """The value at `path` in nested JSON objects, such as `field(issue, "fields", "status")`.

    Returns:
        The value, or None where an object or a key is missing.
    """
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def text(value: object) -> str | None:
    """`value` if it is a string.

    Returns:
        The string, or None.
    """
    return value if isinstance(value, str) else None


def parse_time(value: object) -> datetime | None:
    """A time as Jira writes it, `2026-10-18T10:00:00.000+0000`, or as canopy does, in ISO 8601.

    Returns:
        The time, in UTC when it names no offset; None for anything else.
    """
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def format_time(moment: datetime) -> str:
    """A time as the connector prints it: ISO 8601, in UTC.

    Returns:
        Such as `2026-10-18T10:00:00.123000+00:00`.
    """
    return moment.astimezone(UTC).isoformat()


#: The nodes of a document that sit inside a paragraph's line, rather than start a block of their own.
_INLINE: Final = frozenset(
    {
        "text",
        "hardBreak",
        "mention",
        "emoji",
        "date",
        "status",
        "inlineCard",
        "mediaInline",
        "placeholder",
        "inlineExtension",
    },
)


def document_text(node: object) -> str:
    """The plain text of an Atlassian Document Format document, as Jira's v3 API sends a description or a comment.

    Each block on its own line, a list's items marked, a mention, emoji, status, or link as its text. Marks such as
    bold are dropped. A string is taken as it is, as an older API sends one.

    Returns:
        The text, cut at `MAX_BODY` characters.
    """
    return _node_text(node, 0).strip()[:MAX_BODY]


def _node_text(node: object, depth: int) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict) or depth > _MAX_DEPTH:
        return ""
    kind = field(node, "type")
    atom = _atom_text(kind, node)
    if atom is not None:
        return atom
    children = items(field(node, "content"))
    parts = [_node_text(child, depth + 1) for child in children]
    if children and all(child.get("type") in _INLINE for child in children):
        return "".join(parts)
    if kind == "bulletList":
        parts = [f"- {part}" for part in parts]
    elif kind == "orderedList":
        parts = [f"{i}. {part}" for i, part in enumerate(parts, 1)]
    return "\n".join(part for part in parts if part)


def _atom_text(kind: object, node: object) -> str | None:  # noqa: PLR0911
    """The text of a node that holds no others: a run of text, a break, a mention, an emoji, a link, a date, a rule.

    Returns:
        Its text, or None for a node that holds others.
    """
    attrs = field(node, "attrs")
    match kind:
        case "text":
            return text(field(node, "text")) or ""
        case "hardBreak":
            return "\n"
        case "mention" | "status":
            return text(field(attrs, "text")) or ""
        case "emoji":
            return text(field(attrs, "text")) or text(field(attrs, "shortName")) or ""
        case "inlineCard" | "blockCard" | "embedCard":
            return text(field(attrs, "url")) or ""
        case "date":
            return _date(field(attrs, "timestamp"))
        case "rule":
            return "---"
        case _:
            return None


def _date(timestamp: object) -> str:
    """A date node's day: Jira writes its timestamp as milliseconds since the epoch, in a string.

    Returns:
        The day, such as `2026-10-18`, or an empty string.
    """
    if not isinstance(timestamp, str) or not timestamp.isascii() or not timestamp.isdigit():
        return ""
    try:
        return datetime.fromtimestamp(int(timestamp) / 1000, UTC).date().isoformat()
    except (OverflowError, ValueError, OSError):
        return ""


def read_input(stdin: TextIO) -> Mapping[str, object]:
    """The one JSON object on `stdin`.

    Returns:
        The object.

    Raises:
        InputError: `stdin` is not one JSON object.
    """
    try:
        parsed: object = json.loads(stdin.read())
    except json.JSONDecodeError as e:
        raise InputError(f"stdin is not JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise InputError("stdin is not a JSON object")
    return {str(k): v for k, v in parsed.items()}


def emit(stdout: TextIO, line: Mapping[str, object]) -> None:
    """Print `line` as one JSON line, and flush it, so what was printed survives a kill."""
    stdout.write(json.dumps(dict(line), ensure_ascii=False, separators=(",", ":")) + "\n")
    stdout.flush()
