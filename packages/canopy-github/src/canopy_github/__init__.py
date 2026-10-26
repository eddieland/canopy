"""canopy's GitHub programs (DESIGN §29): `canopy-connect-github` reads, `canopy-post-github` writes.

canopy runs them as commands, never imports them, so the harness holds no token and opens no connection (TRUST_MODEL
T2, D003). Each reads the token `gh` holds for the host its PR's URL or repository's clone URL names, when it runs,
and talks to that host's GraphQL API, so GitHub Enterprise works as github.com does. This module holds what both
share: reading a PR's or an issue's URL and a clone URL, the token, the GraphQL client, and the JSON lines they print.

click for the command lines (D025), and nothing from canopy.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, TextIO, override

if TYPE_CHECKING:
    from email.message import Message

TIMEOUT_SECONDS = 30
#: The media type that names the preview a PR's `mergeStateStatus` was introduced under.
MERGE_INFO_PREVIEW = "application/vnd.github.merge-info-preview+json"
# How much of a comment's or review's body is printed. canopy bounds what it records again.
MAX_BODY = 8000
#: How long a query GitHub answered with a server error, such as its unicorn page, waits before each new try: one
#: try, then one more for each pause. A mutation is sent once, as one GitHub failed to answer may have been carried out.
RETRY_PAUSES: Sequence[float] = (1.0, 3.0)
# How much of GitHub's reply an error quotes.
_MAX_REPLY = 500
# A query, which reads and so may be sent again, as a mutation may not: the operation each document names first.
_QUERY = re.compile(r"\s*query\b")
_HOST = r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::[0-9]{1,5})?"
_NAME = r"[A-Za-z0-9_.-]{1,100}"
_NUMBER = r"[1-9][0-9]{0,9}"
_PR = re.compile(rf"https://({_HOST})/({_NAME})/({_NAME})/pull/({_NUMBER})")
_ISSUE = re.compile(rf"https://({_HOST})/({_NAME})/({_NAME})/issues/({_NUMBER})")
# A clone URL as `git clone` takes it: https, scp-style SSH, or ssh://, with an optional `.git` and trailing slash. An
# SSH URL's port is the SSH server's, not the API's, so it is not part of the host.
_HOST_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
_CLONE = re.compile(
    rf"(?:https://({_HOST})/|ssh://git@({_HOST_NAME})(?::[0-9]{{1,5}})?/|git@({_HOST_NAME}):)"
    rf"({_NAME})/({_NAME}?)(?:\.git)?/?",
)

# The host a token is for, to the GraphQL endpoint to send it to; and the host to the token.
Endpoint = Callable[[str], str]
Token = Callable[[str], str]


class InputError(Exception):
    """What the program was given cannot be used, so it did nothing. Exit 2."""


class GitHubError(Exception):
    """GitHub refused a request, or could not be reached.

    `certain` is whether GitHub is known not to have carried out the request: a reply that refused it. A request that
    timed out or got a server error may have been carried out.
    """

    def __init__(self, message: str, *, certain: bool, types: tuple[str, ...] = ()) -> None:
        """Make the error; `certain` as the class says, `types` the GraphQL errors' types, such as `NOT_FOUND`."""
        super().__init__(message)
        self.certain = certain
        self.types = types


class ServerError(GitHubError):
    """GitHub answered with a server error, as when it shows its unicorn, or with what is not JSON.

    It may have carried the request out, so it is never `certain`. A query too heavy to answer in time gets one.
    """


@dataclass(frozen=True)
class Ref:
    """A PR or an issue, as its URL names it."""

    url: str
    host: str
    owner: str
    name: str
    number: int


@dataclass(frozen=True)
class Repository:
    """A repository canopy names, and where its clone URL says it is on GitHub."""

    #: canopy's name for it, which its `branch` lines carry.
    name: str
    host: str
    owner: str
    repo: str


def parse_repository(name: str, url: object) -> Repository:
    """Read where a repository is from its clone URL: `https://HOST/OWNER/REPO`, `git@HOST:OWNER/REPO`, or `ssh://`.

    Returns:
        The repository.

    Raises:
        InputError: `url` is not such a URL.
    """
    match = _CLONE.fullmatch(url) if isinstance(url, str) else None
    if match is None or match[5] in {".", ".."}:
        raise InputError(f"its clone URL {url!r} names no repository on a GitHub host")
    host = next(h for h in match.groups()[:3] if h is not None)
    return Repository(name=name, host=host.lower(), owner=match[4], repo=match[5])


def parse_pr(url: object) -> Ref:
    """Read a PR's URL, `https://HOST/OWNER/REPO/pull/N`.

    Returns:
        The PR it names.

    Raises:
        InputError: `url` is not such a URL.
    """
    return _parse(_PR, url, "a PR's URL, https://HOST/OWNER/REPO/pull/N")


def parse_issue(url: object) -> Ref:
    """Read an issue's URL, `https://HOST/OWNER/REPO/issues/N`.

    Returns:
        The issue it names.

    Raises:
        InputError: `url` is not such a URL.
    """
    return _parse(_ISSUE, url, "an issue's URL, https://HOST/OWNER/REPO/issues/N")


def _parse(pattern: re.Pattern[str], url: object, what: str) -> Ref:
    match = pattern.fullmatch(url) if isinstance(url, str) else None
    if match is None:
        raise InputError(f"{url!r} is not {what}")
    host, owner, name, number = match.groups()
    return Ref(url=match.group(0), host=host.lower(), owner=owner, name=name, number=int(number))


def endpoint(host: str) -> str:
    """The GraphQL endpoint for `host`: github.com's API host, or an Enterprise server's own `/api/graphql`.

    Returns:
        The endpoint's URL.
    """
    return "https://api.github.com/graphql" if host == "github.com" else f"https://{host}/api/graphql"


def gh_token(host: str) -> str:
    """The token `gh` holds for `host`, read now, once `gh` names `host` as one it is logged in to. It is never printed.

    `gh auth token` alone is not enough: with `GH_ENTERPRISE_TOKEN` set, it answers that token for any host but
    github.com, so a PR's URL naming a host of its writer's choosing would be sent it (TRUST_MODEL T2).

    Returns:
        The token.

    Raises:
        InputError: `gh` is not installed, is not logged in to `host`, or holds no token for it.
    """
    status = _gh(["auth", "status", "--json", "hosts", "--hostname", host], host)
    try:
        hosts: object = json.loads(status.stdout).get("hosts")
    except (json.JSONDecodeError, AttributeError) as e:
        raise InputError(f"cannot read the hosts gh is logged in to: {status.stderr.strip()[:_MAX_REPLY]}") from e
    if status.returncode != 0 or not isinstance(hosts, dict) or host not in hosts:
        raise InputError(f"gh is not logged in to {host}; run: gh auth login --hostname {host}")
    done = _gh(["auth", "token", "--hostname", host], host)
    token = done.stdout.strip()
    if done.returncode != 0 or not token or any(c.isspace() or not c.isprintable() for c in token):
        raise InputError(f"gh holds no token for {host}; run: gh auth login --hostname {host}")
    return token


def _gh(args: list[str], host: str) -> subprocess.CompletedProcess[str]:
    argv = ["gh", *args]
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as e:
        raise InputError(f"cannot run gh to read the token for {host}: {e}") from e


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follows no redirect: urllib would carry the request's headers, the token among them, to wherever it pointed."""

    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        return None


class Client:
    """GitHub's GraphQL API at one endpoint, with one token, sent to that endpoint alone: a redirect is refused."""

    def __init__(self, url: str, token: str) -> None:
        """Talk to the endpoint at `url` with `token`."""
        self._url = url
        self._token = token
        self._opener = urllib.request.build_opener(_NoRedirect())

    def query(self, document: str, variables: Mapping[str, object]) -> Mapping[str, object]:
        """Send one query or mutation, which GitHub must answer whole.

        Returns:
            The reply's `data`.

        Raises:
            GitHubError: GitHub refused it, answered with errors, or could not be reached.
        """
        reply = self.ask(document, variables)
        if reply.errors:
            raise GitHubError(refusal(reply.errors), certain=True, types=error_types(reply.errors))
        return reply.data

    def ask(self, document: str, variables: Mapping[str, object]) -> Reply:
        """Send one query, which GitHub may answer in part: an error about one field leaves the rest of `data`.

        Returns:
            The reply's `data`, and its errors.

        Raises:
            GitHubError: GitHub refused it whole, could not be reached, or answered with a server error, a query each
                time it was sent.
        """
        payload = json.dumps({"query": document, "variables": dict(variables)}).encode()
        headers = {
            "Authorization": f"bearer {self._token}",
            "Content-Type": "application/json",
            # A PR's `mergeStateStatus` was a preview; asking for it names the preview, which GitHub otherwise ignores.
            "Accept": f"{MERGE_INFO_PREVIEW}, application/json",
            "User-Agent": "canopy-github",
        }
        request = urllib.request.Request(self._url, data=payload, headers=headers, method="POST")  # noqa: S310
        parsed = self._send(request, RETRY_PAUSES if _QUERY.match(document) else ())
        body = obj(parsed, "reply")
        errors = items(body.get("errors"))
        data = body.get("data")
        if errors and not isinstance(data, dict):
            raise GitHubError(refusal(errors), certain=True, types=error_types(errors))
        return Reply(obj(data, "data"), tuple(errors))

    def _send(self, request: urllib.request.Request, pauses: Iterable[float]) -> object:
        """Send `request`, and again after each of `pauses` while GitHub answers with a server error.

        Returns:
            GitHub's reply, parsed.

        Raises:
            GitHubError: GitHub refused it, could not be reached, or answered its last try with a server error.
        """
        for pause in pauses:
            try:
                return self._post(request)
            except ServerError:
                time.sleep(pause)
        return self._post(request)

    def _post(self, request: urllib.request.Request) -> object:
        """Send `request` once.

        Returns:
            GitHub's reply, parsed.

        Raises:
            GitHubError: GitHub refused it, or could not be reached.
            ServerError: GitHub answered with a server error, or with what is not JSON, as its error pages are.
        """
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                reply = response.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            # GitHub's error page is HTML, its unicorn's image among it: naming the page says more than quoting it.
            text = e.read().decode(errors="replace")[:_MAX_REPLY]
            if "html" in (e.headers.get("Content-Type") or ""):
                text = "GitHub's error page"
            if e.code >= 500:  # noqa: PLR2004
                # A server error may come after the request was carried out; a refusal comes before.
                raise ServerError(f"HTTP {e.code}: {text}", certain=False) from e
            raise GitHubError(f"HTTP {e.code}: {text}", certain=True) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Not tried again: a try that timed out has waited `TIMEOUT_SECONDS`, which a connector's run cannot spend
            # many times over.
            raise GitHubError(f"cannot reach {self._url}: {e}", certain=False) from e
        try:
            return json.loads(reply)
        except json.JSONDecodeError as e:
            raise ServerError(f"GitHub's reply is not JSON: {reply[:_MAX_REPLY]}", certain=False) from e


@dataclass(frozen=True)
class Reply:
    """GitHub's answer to one query: its `data`, and the errors that left parts of it out."""

    data: Mapping[str, object]
    #: Each error as GitHub sent it; one about a field names it in its `path`.
    errors: Sequence[Mapping[str, object]] = ()


def refusal(errors: Iterable[Mapping[str, object]]) -> str:
    """What GitHub's errors say, for a `GitHubError`.

    Returns:
        Their messages, quoted only so far.
    """
    messages = "; ".join(str(e.get("message")) for e in errors)
    return f"GitHub refused it: {messages[:_MAX_REPLY]}"


def error_types(errors: Iterable[Mapping[str, object]]) -> tuple[str, ...]:
    """The types GitHub's errors name, such as `NOT_FOUND`.

    Returns:
        The types, in order.
    """
    return tuple(t for e in errors if isinstance(t := e.get("type"), str))


def client_for(host: str, endpoint_of: Endpoint, token_of: Token) -> Client:
    """A client for `host`, with its endpoint and token.

    Returns:
        The client.
    """
    return Client(endpoint_of(host), token_of(host))


def pages(fetch: Callable[[str | None], Mapping[str, object]]) -> Iterator[Mapping[str, object]]:
    """Each node of a connection, page by page: `fetch(cursor)` returns one page, `None` for the first.

    Yields:
        Each node, in order.

    Raises:
        GitHubError: The pages never end: GitHub sent a page's cursor twice.
    """
    seen: set[str] = set()
    cursor: str | None = None
    while True:
        page = fetch(cursor)
        yield from items(page.get("nodes"))
        info = obj(page.get("pageInfo"), "pageInfo")
        after = info.get("endCursor")
        if info.get("hasNextPage") is not True or not isinstance(after, str):
            return
        if after in seen:
            raise GitHubError("its pages never end: GitHub sent a page's cursor twice", certain=True)
        seen.add(after)
        cursor = after


def more(first: Mapping[str, object], fetch: Callable[[str], Mapping[str, object]]) -> Iterator[Mapping[str, object]]:
    """Each node of a connection whose first page is in hand, the rest fetched by `fetch(cursor)` as `pages` does.

    Returns:
        The nodes, in order, as `pages` yields them.
    """
    return pages(lambda after: first if after is None else fetch(after))


def obj(value: object, what: str) -> Mapping[str, object]:
    """`value` as a JSON object.

    Returns:
        The object, with string keys.

    Raises:
        GitHubError: `value` is not an object, so GitHub's reply is not the shape asked for.
    """
    if not isinstance(value, dict):
        raise GitHubError(f"GitHub's reply has no {what}", certain=False)
    return {str(k): v for k, v in value.items()}


def items(value: object) -> list[Mapping[str, object]]:
    """`value` as a JSON array of objects: what is not an object is left out, and anything but an array is empty.

    Returns:
        The objects.
    """
    if not isinstance(value, list):
        return []
    return [{str(k): v for k, v in item.items()} for item in value if isinstance(item, dict)]


def text(value: object) -> str | None:
    """`value` if it is a string.

    Returns:
        The string, or None.
    """
    return value if isinstance(value, str) else None


def number(value: object) -> int | None:
    """`value` as a positive integer: GitHub sends a BigInt id as a string of digits.

    Returns:
        The integer, or None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value) or None
    return None


def cut(body: object) -> str:
    """`body` cut at `MAX_BODY` characters; anything but a string is empty.

    Returns:
        The text.
    """
    return body[:MAX_BODY] if isinstance(body, str) else ""


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


@dataclass(frozen=True)
class Hosts:
    """How a program reaches a GitHub host: as GitHub's own are reached, unless a test gives its own."""

    #: A host to its GraphQL endpoint.
    endpoint_of: Endpoint = endpoint
    #: A host to its token.
    token_of: Token = gh_token
