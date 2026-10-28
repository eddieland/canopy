"""`canopy-connect-jira`: canopy's Jira connector (DESIGN §30). Prints what it reads of Jira Cloud's tickets.

Run as `canopy-connect-jira --site acme.atlassian.net`, with the email and API token in a file of the operator's
(`--credentials-file`, by default `$XDG_CONFIG_HOME/canopy/jira-credentials`, one line `EMAIL:API_TOKEN`, mode 600).

On stdin, one JSON object naming what to observe, each key optional: `query`, in JQL, and `tickets`, each
`{"key": "PROJ-1", "comments_since": TIME}`. On stdout, one JSON line per observation, in DESIGN §30's shapes:

- for each ticket asked and read whole, its `ticket` line, each label with the time its changelog last added it, then
  a `comment` line for each comment created at or after its `comments_since`, or for every comment without one;
- for each open ticket the query returned, read to its last page, its `ticket` line;
- for each ticket one of those names as its blocker (an inward link of type Blocks, "is blocked by"), its `ticket`
  line.

Last, an `end` line naming the tickets read whole and, when the query was read to its last page, the open tickets it
returned, in its order. A ticket that could not be read whole prints nothing but its error on stderr, so a cut-off
read never looks like a ticket with no comments. Nothing is written to Jira.

Exit codes: 0 everything was read; 1 something was not, and the `end` line names what was; 2 the site, the
credentials file, or stdin is not usable, and nothing was read.
"""

from __future__ import annotations

import itertools
import operator
import re
import sys
import urllib.parse
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final, TextIO

import click

from canopy_jira import (
    Client,
    Endpoint,
    InputError,
    JiraError,
    default_credentials_file,
    document_text,
    emit,
    endpoint,
    format_time,
    items,
    parse_site,
    parse_time,
    read_credentials,
    read_input,
    text,
)
from canopy_jira import field as at

#: The fields each ticket is read with: no more than its line needs.
FIELDS: Final = ("summary", "description", "status", "labels", "updated", "issuelinks")
#: More than any one request needs: canopy asks for the tickets its state block lists.
MAX_TICKETS: Final = 1000
#: The most open tickets a query may return before it counts as not read: narrow a query that returns more.
MAX_QUERY: Final = 1000
#: Items a page asks for: the most Jira returns of an issue's comments or changelog, and of issues fetched at once.
PAGE: Final = 100
#: The link type whose inward side, "is blocked by", names a ticket's blockers (the `tracker-jira` skill).
BLOCKS: Final = "Blocks"
#: A ticket's key, as canopy reads one.
_KEY: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")


@dataclass(frozen=True)
class Asked:
    """A ticket the request names, and the time of the newest of its comments canopy already holds."""

    key: str
    since: datetime | None = None


@dataclass(frozen=True)
class Request:
    """What one run is asked to observe: the query, when asked, and the tickets."""

    query: str | None
    tickets: Sequence[Asked]


@dataclass(frozen=True)
class Sites:
    """How the connector reaches a Jira site: as Jira Cloud's are reached, unless a test gives its own."""

    #: The site's host, to the base URL of its REST API.
    endpoint_of: Endpoint = endpoint


@click.command("canopy-connect-jira", context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--site", required=True, help="Your Jira Cloud site, such as acme.atlassian.net.")
@click.option(
    "--credentials-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help=f"One line, EMAIL:API_TOKEN, readable by you alone. Default: {default_credentials_file()}",
)
@click.pass_context
def main(ctx: click.Context, site: str, credentials_file: Path | None) -> None:
    """Read Jira Cloud's tickets into canopy's journal: canopy's tracker source for Jira (DESIGN §30).

    The request is one JSON object on stdin; what was read is JSON lines on stdout, the `end` line last.
    """
    sites = ctx.find_object(Sites) or Sites()
    try:
        host = parse_site(site)
        request = _request(read_input(sys.stdin))
        email, token = read_credentials(credentials_file or default_credentials_file())
    except InputError as e:
        _say(str(e))
        ctx.exit(2)
    reader = _Reader(Client(sites.endpoint_of(host), email, token), sys.stdout)
    query = reader.read(request)
    end: dict[str, object] = {"kind": "end", "tickets": reader.whole}
    if query is not None:
        end["query"] = query
    emit(sys.stdout, end)
    ctx.exit(1 if reader.failed else 0)


def _request(raw: Mapping[str, object]) -> Request:
    """Read the request: a key canopy sends another kind of source is not this one's, and is passed over.

    Returns:
        The request, each ticket once, in the order given.

    Raises:
        InputError: The query or a ticket is not usable.
    """
    query = raw.get("query")
    if query is not None and not (isinstance(query, str) and query.strip()):
        raise InputError("the query must be JQL, a string that is not blank")
    tickets = raw.get("tickets", [])
    if not isinstance(tickets, list):
        raise InputError('stdin\'s tickets must be a list: {"tickets": [{"key": "PROJ-1"}]}')
    if len(tickets) > MAX_TICKETS:
        raise InputError(f"stdin names {len(tickets)} tickets; at most {MAX_TICKETS} a read")
    asked: dict[str, Asked] = {}
    for ticket in tickets:
        key = at(ticket, "key")
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise InputError(f"{key!r} is not a ticket's key")
        since = at(ticket, "comments_since")
        moment = None if since is None else parse_time(since)
        if since is not None and moment is None:
            raise InputError(f"{key}'s comments_since {since!r} is not an ISO 8601 time")
        asked.setdefault(key, Asked(key, moment))
    return Request(query if isinstance(query, str) else None, list(asked.values()))


@dataclass
class _Reader:
    """One run's reads: what it printed whole, the blockers left to read, and whether anything was not read."""

    client: Client
    stdout: TextIO
    #: The tickets printed whole, in the order printed.
    whole: list[str] = field(default_factory=list[str])
    #: The blockers the tickets printed name, in the order named.
    blockers: dict[str, None] = field(default_factory=dict[str, None])
    #: The tickets asked that were not read whole: neither the query nor a link prints one without its comments.
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
        for chunk in _chunks(asked, PAGE):
            try:
                found = self._fetch([a.key for a in chunk], changelog=True)
            except JiraError as e:
                self.missed.update(a.key for a in chunk)
                self._miss(", ".join(a.key for a in chunk), e)
                continue
            for ticket in chunk:
                issue = found.get(ticket.key)
                if issue is None:
                    self.missed.add(ticket.key)
                    self._miss(ticket.key, "Jira did not return it: moved, deleted, or not visible to you")
                    continue
                try:
                    lines = [_ticket(issue, self._label_times(ticket.key, issue)), *self._comments(ticket)]
                except JiraError as e:
                    self.missed.add(ticket.key)
                    self._miss(ticket.key, e)
                    continue
                self._print(ticket.key, lines, issue)

    def _query(self, jql: str) -> list[str] | None:
        """Run the query to its last page, printing each open ticket it returns that was not printed already.

        Returns:
            The open tickets it returned, in its order; None when it could not be read to the end.
        """
        keys: dict[str, None] = {}
        try:
            for issue in self._search(jql):
                key = _key(issue)
                if _state(issue) != "open" or key in keys:
                    continue
                keys[key] = None
                if len(keys) > MAX_QUERY:
                    self._miss("the query", f"it returned more than {MAX_QUERY} open tickets; narrow tracker.query")
                    return None
                if key not in self.whole and key not in self.missed:
                    self._print(key, [_ticket(issue, {})], issue)
        except JiraError as e:
            self._miss("the query", e)
            return None
        return list(keys)

    def _search(self, jql: str) -> Iterator[Mapping[str, object]]:
        """Each ticket a JQL search returns, page by page, to the last.

        Yields:
            Each ticket, in the query's order.

        Raises:
            JiraError: A page could not be read, or the pages never end.
        """
        tokens: set[str] = set()
        token: str | None = None
        while True:
            body: dict[str, object] = {"jql": jql, "fields": list(FIELDS), "maxResults": PAGE}
            if token is not None:
                body["nextPageToken"] = token
            reply = self.client.post("/rest/api/3/search/jql", body)
            yield from items(reply.get("issues"))
            token = text(reply.get("nextPageToken"))
            if not token or reply.get("isLast") is True:
                return
            if token in tokens:
                raise JiraError("its pages never end: Jira sent a page's token twice")
            tokens.add(token)

    def _blockers(self) -> None:
        """Read and print each blocker not printed already. A blocker's own blockers are not followed."""
        pending = [key for key in self.blockers if key not in self.whole and key not in self.missed]
        for chunk in _chunks(pending, PAGE):
            try:
                found = self._fetch(chunk, changelog=False)
            except JiraError as e:
                self._miss(f"blockers {', '.join(chunk)}", e)
                continue
            for key in chunk:
                issue = found.get(key)
                if issue is None:
                    self._miss(f"blocker {key}", "Jira did not return it: moved, deleted, or not visible to you")
                    continue
                try:
                    line = _ticket(issue, {})
                except JiraError as e:
                    self._miss(f"blocker {key}", e)
                    continue
                self._print(key, [line], None)

    def _fetch(self, keys: Sequence[str], *, changelog: bool) -> dict[str, Mapping[str, object]]:
        """Fetch up to `PAGE` tickets at once; one Jira cannot return is left out.

        Returns:
            Each ticket returned, by its key.
        """
        body: dict[str, object] = {"issueIdsOrKeys": list(keys), "fields": list(FIELDS)}
        if changelog:
            body["expand"] = ["changelog"]
        reply = self.client.post("/rest/api/3/issue/bulkfetch", body)
        return {key: issue for issue in items(reply.get("issues")) if (key := text(issue.get("key"))) is not None}

    def _label_times(self, key: str, issue: Mapping[str, object]) -> dict[str, datetime]:
        """When the changelog last added each label the ticket has; a label it never added (set at creation) has none.

        The changelog came with the ticket; one cut short, missing, or not saying how long it is, is read whole on
        its own.

        Returns:
            Each label's time, by name.
        """
        labels = _labels(issue)
        if not labels:
            return {}
        log = at(issue, "changelog")
        histories = items(at(log, "histories"))
        total = at(log, "total")
        if not isinstance(log, dict) or not isinstance(total, int) or total > len(histories):
            histories = list(self._changelog(key))
        added: dict[str, datetime] = {}
        for history in histories:
            moment = parse_time(history.get("created"))
            if moment is None:
                continue
            for change in items(history.get("items")):
                if change.get("fieldId") != "labels" and change.get("field") != "labels":
                    continue
                before = set((text(change.get("fromString")) or "").split())
                for label in set((text(change.get("toString")) or "").split()) - before:
                    if label in labels and (label not in added or added[label] < moment):
                        added[label] = moment
        return added

    def _changelog(self, key: str) -> Iterator[Mapping[str, object]]:
        """Each entry of a ticket's changelog, page by page.

        Yields:
            Each entry, oldest first.
        """
        start = 0
        while True:
            reply = self.client.get(f"/rest/api/3/issue/{_path(key)}/changelog", {"startAt": start, "maxResults": PAGE})
            page = items(reply.get("values"))
            yield from page
            start += len(page)
            if not page or reply.get("isLast") is not False:
                return

    def _comments(self, ticket: Asked) -> list[dict[str, object]]:
        """Read the ticket's comments created at or after its `since`, newest first, stopping at an older one.

        Jira is asked for them newest first; a page that is not in that order is read on to the last page.

        Returns:
            The comments' lines, oldest first.

        Raises:
            JiraError: A page could not be read, or a comment has no id or time.
        """
        found: list[tuple[datetime, dict[str, object]]] = []
        start = 0
        while True:
            params: dict[str, str | int] = {"orderBy": "-created", "startAt": start, "maxResults": PAGE}
            reply = self.client.get(f"/rest/api/3/issue/{_path(ticket.key)}/comment", params)
            page = [_comment(ticket.key, c) for c in items(reply.get("comments"))]
            found.extend(c for c in page if ticket.since is None or c[0] >= ticket.since)
            start += len(page)
            total = reply.get("total")
            if not page or (isinstance(total, int) and start >= total):
                break
            newest_first = all(a[0] >= b[0] for a, b in itertools.pairwise(page))
            if ticket.since is not None and newest_first and page[-1][0] < ticket.since:
                break
        return [line for _, line in sorted(found, key=operator.itemgetter(0))]

    def _print(self, key: str, lines: Iterable[Mapping[str, object]], issue: Mapping[str, object] | None) -> None:
        """Print a ticket read whole, and note its blockers to read, unless it is a blocker itself (`issue` None)."""
        for line in lines:
            emit(self.stdout, line)
        self.whole.append(key)
        if issue is not None:
            for blocker in _blockers_of(issue):
                self.blockers.setdefault(blocker)

    def _miss(self, what: str, why: object) -> None:
        self.failed = True
        _say(f"cannot read {what}: {why}")


def _ticket(issue: Mapping[str, object], added: Mapping[str, datetime]) -> dict[str, object]:
    """A ticket's line, from the ticket as Jira sent it and the times its labels were added.

    Returns:
        The line.

    Raises:
        JiraError: The ticket has no key or no status.
    """
    fields = at(issue, "fields")
    line: dict[str, object] = {
        "kind": "ticket",
        "key": _key(issue),
        "title": " ".join((text(at(fields, "summary")) or "").split()) or "(no title)",
        "body": document_text(at(fields, "description")),
        "state": _state(issue),
        "labels": [
            {"name": label, **({"added_at": format_time(added[label])} if label in added else {})}
            for label in _labels(issue)
        ],
        "blockers": _blockers_of(issue),
    }
    updated = parse_time(at(fields, "updated"))
    if updated is not None:
        line["updated_at"] = format_time(updated)
    return line


def _key(issue: Mapping[str, object]) -> str:
    key = text(issue.get("key"))
    if key is None or not _KEY.fullmatch(key):
        raise JiraError(f"Jira sent a ticket whose key is not one: {key!r}")
    return key


def _state(issue: Mapping[str, object]) -> str:
    """Whether the ticket is closed: its status's category is Done, whatever the status is named (`tracker-jira`).

    Returns:
        `closed` or `open`.

    Raises:
        JiraError: The ticket has no status category.
    """
    category = text(at(issue, "fields", "status", "statusCategory", "key"))
    if category is None:
        raise JiraError(f"{issue.get('key')} has no status category")
    return "closed" if category == "done" else "open"


def _labels(issue: Mapping[str, object]) -> list[str]:
    labels = at(issue, "fields", "labels")
    return [label for label in labels if isinstance(label, str)] if isinstance(labels, list) else []


def _blockers_of(issue: Mapping[str, object]) -> list[str]:
    """The tickets that block this one: links of type Blocks read from the inward side, "is blocked by".

    Returns:
        Their keys, each once, in the order linked.
    """
    found: dict[str, None] = {}
    for link in items(at(issue, "fields", "issuelinks")):
        key = text(at(link, "inwardIssue", "key"))
        if at(link, "type", "name") == BLOCKS and key is not None and _KEY.fullmatch(key):
            found[key] = None
    return list(found)


def _comment(ticket: str, comment: Mapping[str, object]) -> tuple[datetime, dict[str, object]]:
    """A comment's line, and its time to order it by. Its author is their account id (`tracker-jira`).

    Returns:
        The time and the line.

    Raises:
        JiraError: The comment has no id or no time.
    """
    id_ = text(comment.get("id"))
    moment = parse_time(comment.get("created"))
    if id_ is None or moment is None:
        raise JiraError(f"a comment on {ticket} has no id or time")
    author = text(at(comment, "author", "accountId")) or "unknown"
    line: dict[str, object] = {
        "kind": "comment",
        "ticket": ticket,
        "id": id_,
        "author": author,
        "time": format_time(moment),
        "body": document_text(comment.get("body")),
    }
    return moment, line


def _path(key: str) -> str:
    return urllib.parse.quote(key, safe="")


def _chunks[T](values: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _say(message: str) -> None:
    click.echo(f"canopy-connect-jira: {message}", err=True)
