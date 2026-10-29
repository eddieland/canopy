"""`canopy-connect-github --repo OWNER/NAME`: one repository's GitHub Issues as canopy's `tracker` source (DESIGN §30).

On stdin, one JSON object naming what to observe, each key optional: `query`, in GitHub's search syntax, and
`tickets`, each `{"key": "GH-12", "comments_since": TIME}`. A ticket's key is `GH-` and its issue's number in the
repository (DESIGN §17, the `tracker-github` skill). On stdout, one JSON line per observation, in DESIGN §30's shapes,
as `canopy-connect-jira` prints Jira's:

- for each ticket asked and read whole, its `ticket` line, each label with the time its timeline last added it, then a
  `comment` line for each comment created at or after its `comments_since`, or for every comment without one;
- for each open issue the query returned, read to its last page, its `ticket` line; a PR it returns is passed over;
- for each issue one of those names as its blocker, its `ticket` line.

A ticket's blockers are the issues GitHub's issue dependencies say block it, and those a line of its body names,
`Blocked by #N`, as a worker orders follow-ups where the dependencies are not there (`tracker-github`). A key names an
issue of this repository alone, so a ticket an open issue of another repository blocks is not read whole: it stays
stale, and no dispatch rests on it (DESIGN §7). A closed one blocks nothing, and is left out.

Last, an `end` line naming the tickets read whole and, when the query was read to its last page, the open issues it
returned, in its order. A query that returns an issue of another repository is not read, since no key names it. A
ticket that could not be read whole prints nothing but its error on stderr, so a cut-off read never looks like a ticket
with no comments. Nothing is written to GitHub.

Exit codes: 0 everything was read; 1 something was not, and the `end` line names what was; 2 the repository, the
token, or stdin is not usable, and nothing was read.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TextIO

import click

from canopy_github import (
    Client,
    GitHubError,
    Hosts,
    InputError,
    Reply,
    ServerError,
    client_for,
    cut,
    emit,
    error_types,
    items,
    login,
    number,
    obj,
    pages,
    read_input,
    refusal,
    text,
)
from canopy_github.repository import MAX_SEARCH

#: A ticket's key is this, a hyphen, and its issue's number: issue 12 is `GH-12` (DESIGN §17).
PREFIX = "GH"
#: The host `--repo` is on when it names none.
DEFAULT_HOST = "github.com"
#: More than any one request needs: canopy asks for the tickets its state block lists.
MAX_TICKETS = 1000
#: Issues one query reads: each asks for some 400 nodes (a page each of labels, blockers, label events, and comments).
BATCH = 25
#: The most labels or blockers a ticket's line carries: canopy refuses a line with more, so a ticket with more is not
#: read whole.
MAX_LIST = 100
#: A ticket's key as canopy sends one, and as this tracker gives one: a number GraphQL's 32-bit `Int` holds.
_ASKED = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
_KEY = re.compile(rf"{PREFIX}-([1-9][0-9]{{0,8}})")
#: `--repo`: `OWNER/NAME`, or `HOST/OWNER/NAME` for GitHub Enterprise.
_REPO = re.compile(
    r"(?:([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::[0-9]{1,5})?)/)?"
    r"([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})",
)
#: A line of an issue's body naming a blocker in the same repository (`tracker-github`).
_BLOCKED_BY = re.compile(r"^[ \t]*blocked by #([1-9][0-9]{0,8})\b", re.IGNORECASE | re.MULTILINE)
#: The login GitHub shows for an account since deleted, which no one can hold: a comment with no author is its.
_GHOST = "ghost"

_TICKET = """
fragment Ticket on Issue {
  number title body state updatedAt
  repository { nameWithOwner }
  labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
  blockedBy(first: 100) { pageInfo { hasNextPage } nodes { number state repository { nameWithOwner } } }
}
"""

# What an asked ticket is read with besides: read from the newest, as the newest label event and comment matter most.
_LABELED = "pageInfo { hasPreviousPage startCursor } nodes { ... on LabeledEvent { createdAt label { name } } }"
_COMMENTS = (
    "pageInfo { hasPreviousPage startCursor } nodes { fullDatabaseId createdAt body author { __typename login } }"
)
_HISTORY = f"""
fragment History on Issue {{
  timelineItems(itemTypes: [LABELED_EVENT], last: 100) {{ {_LABELED} }}
  comments(last: 100) {{ {_COMMENTS} }}
}}
"""

_MORE_LABELED = f"""
query Labeled($owner: String!, $name: String!, $number: Int!, $before: String) {{
  repository(owner: $owner, name: $name) {{
    issue(number: $number) {{ timelineItems(itemTypes: [LABELED_EVENT], last: 100, before: $before) {{ {_LABELED} }} }}
  }}
}}
"""

_MORE_COMMENTS = f"""
query IssueComments($owner: String!, $name: String!, $number: Int!, $before: String) {{
  repository(owner: $owner, name: $name) {{
    issue(number: $number) {{ comments(last: 100, before: $before) {{ {_COMMENTS} }} }}
  }}
}}
"""

_SEARCH = (
    """
query IssueSearch($query: String!, $after: String) {
  search(query: $query, type: ISSUE, first: 100, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { __typename ...Ticket }
  }
}
"""
    + _TICKET
)


@dataclass(frozen=True)
class Repository:
    """The repository whose issues are the tickets, as `--repo` names it."""

    host: str
    owner: str
    name: str

    @property
    def full(self) -> str:
        """`OWNER/NAME`, lowercased, as GitHub compares a repository's name.

        Returns:
            The name.
        """
        return f"{self.owner}/{self.name}".lower()


@dataclass(frozen=True)
class Asked:
    """A ticket the request names, its issue's number, and the time of the newest of its comments canopy holds."""

    key: str
    number: int | None
    since: datetime | None = None


@dataclass(frozen=True)
class Request:
    """What one run is asked to observe: the query, when asked, and the tickets."""

    query: str | None
    tickets: Sequence[Asked]


def observe(repo: str, hosts: Hosts, stdin: TextIO, stdout: TextIO) -> int:
    """Read the request on `stdin`, and print what the repository's issues hold of it, the `end` line last.

    Returns:
        The exit code, as the module says.
    """
    try:
        repository = parse_repo(repo)
        request = _request(read_input(stdin))
        client = client_for(repository.host, hosts.endpoint_of, hosts.token_of)
    except InputError as e:
        _say(str(e))
        return 2
    reader = _Reader(client, repository, stdout)
    query = reader.read(request)
    end: dict[str, object] = {"kind": "end", "tickets": reader.whole}
    if query is not None:
        end["query"] = query
    emit(stdout, end)
    return 1 if reader.failed else 0


def parse_repo(value: str) -> Repository:
    """Read `--repo`: `OWNER/NAME`, on github.com, or `HOST/OWNER/NAME`.

    Returns:
        The repository.

    Raises:
        InputError: `value` is not such a name.
    """
    match = _REPO.fullmatch(value)
    if match is None or match[3] in {".", ".."}:
        raise InputError(f"--repo {value!r} is not OWNER/NAME, or HOST/OWNER/NAME")
    host, owner, name = match.groups()
    return Repository((host or DEFAULT_HOST).lower(), owner, name)


def _request(raw: Mapping[str, object]) -> Request:
    """Read the request: a key canopy sends another kind of source is not this one's, and is passed over.

    Returns:
        The request, each ticket once, in the order given; a key this tracker gives no issue has no number.

    Raises:
        InputError: The query or a ticket is not usable.
    """
    query = raw.get("query")
    if query is not None and not (isinstance(query, str) and query.strip()):
        raise InputError("the query must be GitHub's search syntax, a string that is not blank")
    tickets = raw.get("tickets", [])
    if not isinstance(tickets, list):
        raise InputError('stdin\'s tickets must be a list: {"tickets": [{"key": "GH-1"}]}')
    if len(tickets) > MAX_TICKETS:
        raise InputError(f"stdin names {len(tickets)} tickets; at most {MAX_TICKETS} a read")
    asked: dict[str, Asked] = {}
    for ticket in tickets:
        fields = obj(ticket, "ticket") if isinstance(ticket, dict) else {}
        key = fields.get("key")
        if not isinstance(key, str) or not _ASKED.fullmatch(key):
            raise InputError(f"{key!r} is not a ticket's key")
        since = fields.get("comments_since")
        moment = None if since is None else _moment(since)
        if since is not None and moment is None:
            raise InputError(f"{key}'s comments_since {since!r} is not an ISO 8601 time")
        match = _KEY.fullmatch(key)
        asked.setdefault(key, Asked(key, None if match is None else int(match[1]), moment))
    return Request(query if isinstance(query, str) else None, list(asked.values()))


@dataclass
class _Reader:
    """One run's reads: what it printed whole, the blockers left to read, and whether anything was not read."""

    client: Client
    repository: Repository
    stdout: TextIO
    #: The tickets printed whole, in the order printed.
    whole: list[str] = field(default_factory=list[str])
    #: The issues the tickets printed name as blockers, in the order named.
    blockers: dict[int, None] = field(default_factory=dict[int, None])
    #: The tickets that could not be read whole: neither the query nor a blocker prints one asked without its comments.
    missed: set[str] = field(default_factory=set[str])
    failed: bool = False

    def read(self, request: Request) -> list[str] | None:
        """Read and print the tickets asked, then the query's, then the blockers any of them names.

        Returns:
            The open tickets the query returned, in its order; None when it was not asked or not read to the end.
        """
        self._asked(request.tickets)
        query = None if request.query is None else self._query(request.query)
        self._blockers()
        return query

    def _asked(self, asked: Sequence[Asked]) -> None:
        """Read each ticket asked whole, with its labels' times and its comments, and print it."""
        numbered: list[tuple[Asked, int]] = []
        for ticket in asked:
            if ticket.number is None:
                self.missed.add(ticket.key)
                self._miss(ticket.key, f"it is not a key of GitHub Issues, {PREFIX}- and the issue's number")
            else:
                numbered.append((ticket, ticket.number))
        found = self._fetch([n for _, n in numbered], history=True)
        for ticket, issue_number in numbered:
            try:
                issue = self._own(found[issue_number])
                labels = self._label_times(issue_number, issue)
                lines = [self._ticket(issue, labels), *self._comments(ticket, issue_number, issue)]
            except GitHubError as e:
                self.missed.add(ticket.key)
                self._miss(ticket.key, e)
                continue
            self._print(ticket.key, lines, issue)

    def _query(self, query: str) -> list[str] | None:
        """Run the query to its last page, printing each open issue it returns that was not printed already.

        Returns:
            The open tickets it returned, in its order; None when it could not be read to the end.
        """

        def fetch(after: str | None) -> Mapping[str, object]:
            found = obj(self.client.query(_SEARCH, {"query": query, "after": after}).get("search"), "search")
            total = found.get("issueCount")
            if isinstance(total, int) and total > MAX_SEARCH:
                raise GitHubError(f"it matches {total}, more than the {MAX_SEARCH} GitHub returns", certain=True)
            return found

        keys: dict[str, None] = {}
        try:
            for issue in pages(fetch):
                if issue.get("__typename") != "Issue":
                    continue
                where = _where(issue)
                if where.lower() != self.repository.full:
                    narrow = f"repo:{self.repository.owner}/{self.repository.name}"
                    self._miss(
                        "the query",
                        f"it returned {where}#{issue.get('number')}, which no key names; narrow it with {narrow}",
                    )
                    return None
                key = _key(_number(issue))
                if _state(issue) != "open" or key in keys:
                    continue
                keys[key] = None
                if key not in self.whole and key not in self.missed:
                    self._print_one(key, issue, follow=True)
        except GitHubError as e:
            self._miss("the query", e)
            return None
        return list(keys)

    def _blockers(self) -> None:
        """Read and print each blocker not printed already. A blocker's own blockers are not followed."""
        pending = [n for n in self.blockers if _key(n) not in self.whole and _key(n) not in self.missed]
        found = self._fetch(pending, history=False)
        for issue_number in pending:
            try:
                issue = self._own(found[issue_number])
            except GitHubError as e:
                self._miss(f"blocker {_key(issue_number)}", e)
                continue
            self._print_one(_key(issue_number), issue, follow=False)

    def _print_one(self, key: str, issue: Mapping[str, object], *, follow: bool) -> None:
        """Print a ticket's line alone, as the query and a blocker are read; one that cannot be printed is named."""
        try:
            line = self._ticket(issue, {})
        except GitHubError as e:
            self.missed.add(key)
            self._miss(key if follow else f"blocker {key}", e)
            return
        self._print(key, [line], issue if follow else None)

    def _fetch(self, numbers: Sequence[int], *, history: bool) -> dict[int, Mapping[str, object] | GitHubError]:
        """Fetch each issue, `BATCH` to a query, with its history when asked.

        A query of many issues GitHub answers with a server error is read again in halves rather than sent again
        whole, as one too heavy to answer in time would fail each time; a query of one issue is sent again.

        Returns:
            Each issue, or why it was not read, by its number.
        """
        found: dict[int, Mapping[str, object] | GitHubError] = {}
        for start in range(0, len(numbers), BATCH):
            chunk = numbers[start : start + BATCH]
            found |= self._read(chunk, self._ask(chunk, history=history), history=history)
        return found

    def _ask(self, numbers: Sequence[int], *, history: bool) -> Reply | GitHubError:
        variables: dict[str, object] = {"owner": self.repository.owner, "name": self.repository.name}
        variables |= {f"k{i}": n for i, n in enumerate(numbers)}
        try:
            return self.client.ask(_batch(len(numbers), history=history), variables, retry=len(numbers) == 1)
        except GitHubError as e:
            return e

    def _read(
        self,
        numbers: Sequence[int],
        reply: Reply | GitHubError,
        *,
        history: bool,
        split: bool = True,
    ) -> dict[int, Mapping[str, object] | GitHubError]:
        """Each of `numbers` from the reply to the query that read them, or, for a server error, from its halves'.

        When both halves fail, GitHub is failing whatever it is asked, and neither is split again.

        Returns:
            Each issue, or why it was not read, by its number.
        """
        if split and isinstance(reply, ServerError) and len(numbers) > 1:
            middle = len(numbers) // 2
            halves = (numbers[:middle], numbers[middle:])
            replies = [self._ask(half, history=history) for half in halves]
            again = not all(isinstance(r, GitHubError) for r in replies)
            found: dict[int, Mapping[str, object] | GitHubError] = {}
            for half, half_reply in zip(halves, replies, strict=True):
                found |= self._read(half, half_reply, history=history, split=again)
            return found
        if isinstance(reply, GitHubError):
            return dict.fromkeys(numbers, reply)
        return {n: _aliased(reply, f"i{i}") for i, n in enumerate(numbers)}

    def _own(self, issue: Mapping[str, object] | GitHubError) -> Mapping[str, object]:
        """The issue, once it is this repository's: one GitHub returned from another was moved there.

        Returns:
            The issue.

        Raises:
            GitHubError: It was not read, or it is another repository's.
        """
        if isinstance(issue, GitHubError):
            raise issue
        where = _where(issue)
        if where.lower() != self.repository.full:
            raise GitHubError(f"it was moved to {where}, where no key names it", certain=True)
        return issue

    def _ticket(self, issue: Mapping[str, object], added: Mapping[str, datetime]) -> dict[str, object]:
        """A ticket's line, from the issue as GitHub sent it and the times its labels were added.

        Returns:
            The line.

        Raises:
            GitHubError: The issue has no number or state, more labels or blockers than its line may carry, or an open
                blocker in another repository.
        """
        labels = _labels(issue)
        line: dict[str, object] = {
            "kind": "ticket",
            "key": _key(_number(issue)),
            "title": " ".join((text(issue.get("title")) or "").split()) or "(no title)",
            "body": cut(issue.get("body")).strip(),
            "state": _state(issue),
            "labels": [
                {"name": label, **({"added_at": _format(added[label])} if label in added else {})} for label in labels
            ],
            "blockers": [_key(n) for n in self._blockers_of(issue)],
        }
        updated = _moment(issue.get("updatedAt"))
        if updated is not None:
            line["updated_at"] = _format(updated)
        return line

    def _blockers_of(self, issue: Mapping[str, object]) -> list[int]:
        """The issues that block this one: its dependencies' "blocked by", then its body's `Blocked by #N` lines.

        Returns:
            Their numbers, each once, in that order, the issue's own left out.

        Raises:
            GitHubError: It has more than its line may carry, or an open one is another repository's.
        """
        dependencies = obj(issue.get("blockedBy"), "blockedBy")
        if obj(dependencies.get("pageInfo"), "pageInfo").get("hasNextPage") is True:
            raise GitHubError(f"it is blocked by more than {MAX_LIST} issues", certain=True)
        found: dict[int, None] = {}
        for node in items(dependencies.get("nodes")):
            where, blocker = _where(node), _number(node)
            if where.lower() == self.repository.full:
                found[blocker] = None
            elif node.get("state") != "CLOSED":
                why = f"it is blocked by {where}#{blocker}, open in a repository no key names"
                raise GitHubError(why, certain=True)
        for match in _BLOCKED_BY.finditer(text(issue.get("body")) or ""):
            found.setdefault(int(match[1]))
        found.pop(_number(issue), None)
        if len(found) > MAX_LIST:
            raise GitHubError(f"it is blocked by more than {MAX_LIST} issues", certain=True)
        return list(found)

    def _label_times(self, issue_number: int, issue: Mapping[str, object]) -> dict[str, datetime]:
        """When the timeline last added each label the issue has; a label it never added has none.

        Returns:
            Each label's time, by name.
        """
        labels = set(_labels(issue))
        added: dict[str, datetime] = {}
        if not labels:
            return added

        def before(cursor: str) -> Mapping[str, object]:
            return obj(self._more(_MORE_LABELED, issue_number, cursor).get("timelineItems"), "timelineItems")

        for page in _backward(obj(issue.get("timelineItems"), "timelineItems"), before):
            for event in page:
                label = event.get("label")
                name = text(obj(label, "label").get("name")) if isinstance(label, dict) else None
                moment = _moment(event.get("createdAt"))
                if name in labels and moment is not None and (name not in added or added[name] < moment):
                    added[name] = moment
            if labels <= added.keys():
                break
        return added

    def _comments(self, ticket: Asked, issue_number: int, issue: Mapping[str, object]) -> list[dict[str, object]]:
        """Read the ticket's comments created at or after its `since`, from the newest, stopping at an older one.

        Returns:
            The comments' lines, oldest first.

        Raises:
            GitHubError: A page could not be read, or a comment has no id or time.
        """

        def before(cursor: str) -> Mapping[str, object]:
            return obj(self._more(_MORE_COMMENTS, issue_number, cursor).get("comments"), "comments")

        found: list[tuple[datetime, dict[str, object]]] = []
        for page in _backward(obj(issue.get("comments"), "comments"), before):
            lines = [_comment(ticket.key, node) for node in page]
            found.extend(c for c in lines if ticket.since is None or c[0] >= ticket.since)
            if ticket.since is not None and any(c[0] < ticket.since for c in lines):
                break
        return [line for _, line in sorted(found, key=operator.itemgetter(0))]

    def _more(self, document: str, issue_number: int, cursor: str) -> Mapping[str, object]:
        """One more page of an issue's connection, read from its end.

        Returns:
            The issue's node.

        Raises:
            GitHubError: GitHub refused the page, could not be reached, or no longer has the issue.
        """
        variables = {
            "owner": self.repository.owner,
            "name": self.repository.name,
            "number": issue_number,
            "before": cursor,
        }
        repository = obj(self.client.query(document, variables).get("repository"), "repository")
        return obj(repository.get("issue"), f"issue {_key(issue_number)}")

    def _print(self, key: str, lines: Iterable[Mapping[str, object]], issue: Mapping[str, object] | None) -> None:
        """Print a ticket read whole, and note its blockers to read, unless it is a blocker itself (`issue` None)."""
        for line in lines:
            emit(self.stdout, line)
        self.whole.append(key)
        if issue is not None:
            for blocker in self._blockers_of(issue):
                self.blockers.setdefault(blocker)

    def _miss(self, what: str, why: object) -> None:
        self.failed = True
        _say(f"cannot read {what}: {why}")


def _batch(count: int, *, history: bool) -> str:
    """The query that reads `count` issues of one repository, each under its alias, its number a variable.

    Returns:
        The query.
    """
    params = "".join(f", $k{i}: Int!" for i in range(count))
    spread = "...Ticket ...History" if history else "...Ticket"
    fields = "\n".join(f"    i{i}: issue(number: $k{i}) {{ {spread} }}" for i in range(count))
    fragments = _TICKET + (_HISTORY if history else "")
    head = f"query Issues($owner: String!, $name: String!{params})"
    return f"{head} {{\n  repository(owner: $owner, name: $name) {{\n{fields}\n  }}\n}}\n{fragments}"


def _aliased(reply: Reply, alias: str) -> Mapping[str, object] | GitHubError:
    """The issue under `alias` in a batch's reply, or why it is not there.

    Returns:
        The issue's node; or the errors about it, or about no one issue; or, when GitHub returned none, an error.
    """
    errors = [e for e in reply.errors if _about(e, alias)]
    if errors:
        return GitHubError(refusal(errors), certain=True, types=error_types(errors))
    repository = reply.data.get("repository")
    issue = obj(repository, "repository").get(alias) if isinstance(repository, dict) else None
    if not isinstance(issue, dict):
        return GitHubError("GitHub did not return it: deleted, or not visible to you", certain=True)
    return obj(issue, "issue")


def _about(error: Mapping[str, object], alias: str) -> bool:
    # An error with no path, or about the repository, is about every issue in the query.
    path = error.get("path")
    return not isinstance(path, list) or len(path) < 2 or path[1] == alias  # noqa: PLR2004


def _backward(
    last: Mapping[str, object],
    fetch: Callable[[str], Mapping[str, object]],
) -> Iterator[list[Mapping[str, object]]]:
    """Each page of a connection read from its end, its last page in hand and each earlier one fetched by its cursor.

    Yields:
        Each page's nodes, the newest page first, each page in GitHub's order.

    Raises:
        GitHubError: The pages never end: GitHub sent a page's cursor twice.
    """
    seen: set[str] = set()
    page = last
    while True:
        yield items(page.get("nodes"))
        info = obj(page.get("pageInfo"), "pageInfo")
        cursor = info.get("startCursor")
        if info.get("hasPreviousPage") is not True or not isinstance(cursor, str):
            return
        if cursor in seen:
            raise GitHubError("its pages never end: GitHub sent a page's cursor twice", certain=True)
        seen.add(cursor)
        page = fetch(cursor)


def _key(issue_number: int) -> str:
    return f"{PREFIX}-{issue_number}"


def _number(issue: Mapping[str, object]) -> int:
    found = number(issue.get("number"))
    if found is None:
        raise GitHubError("GitHub sent an issue with no number", certain=True)
    return found


def _where(issue: Mapping[str, object]) -> str:
    """The repository an issue is in, `OWNER/NAME`, as GitHub names it.

    Returns:
        The name.

    Raises:
        GitHubError: GitHub named none.
    """
    repository = issue.get("repository")
    where = text(obj(repository, "repository").get("nameWithOwner")) if isinstance(repository, dict) else None
    if where is None:
        raise GitHubError(f"GitHub sent issue #{issue.get('number')} with no repository", certain=True)
    return where


def _state(issue: Mapping[str, object]) -> str:
    """Whether the issue is closed, whatever it was closed as (`tracker-github`).

    Returns:
        `closed` or `open`.

    Raises:
        GitHubError: The issue has no state.
    """
    match issue.get("state"):
        case "OPEN":
            return "open"
        case "CLOSED":
            return "closed"
        case state:
            raise GitHubError(f"issue #{issue.get('number')} has no state an issue has: {state!r}", certain=True)


def _labels(issue: Mapping[str, object]) -> list[str]:
    """The issue's labels' names.

    Returns:
        The names, in GitHub's order.

    Raises:
        GitHubError: It has more than its line may carry.
    """
    labels = obj(issue.get("labels"), "labels")
    if obj(labels.get("pageInfo"), "pageInfo").get("hasNextPage") is True:
        raise GitHubError(f"it has more than {MAX_LIST} labels", certain=True)
    return [name for node in items(labels.get("nodes")) if (name := text(node.get("name"))) is not None]


def _comment(key: str, node: Mapping[str, object]) -> tuple[datetime, dict[str, object]]:
    """A comment's line, and its time to order it by. Its author is their login (`tracker-github`).

    Returns:
        The time and the line.

    Raises:
        GitHubError: The comment has no id or no time.
    """
    id_ = number(node.get("fullDatabaseId"))
    moment = _moment(node.get("createdAt"))
    if id_ is None or moment is None:
        raise GitHubError(f"a comment on {key} has no id or time", certain=True)
    line: dict[str, object] = {
        "kind": "comment",
        "ticket": key,
        "id": str(id_),
        "author": _author(node.get("author")),
        "time": _format(moment),
        "body": cut(node.get("body")),
    }
    return moment, line


def _author(author: object) -> str:
    """A comment's author's login: a bot's ends `[bot]`, as GitHub's REST API names it, so it is never a replier.

    Returns:
        The login; a deleted account's is `ghost`.
    """
    return login(author) or _GHOST


def _moment(value: object) -> datetime | None:
    """A time as GitHub writes it, `2026-10-18T10:00:00Z`, or as canopy does, in ISO 8601.

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


def _format(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _say(message: str) -> None:
    click.echo(f"canopy-connect-github: {message}", err=True)
