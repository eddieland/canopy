"""`canopy-connect-github`: canopy's GitHub reader, the `vcs` source (DESIGN §29, §30). Prints what it reads.

On stdin, one JSON object naming what to observe, each key optional: `prs`, PRs' URLs; `repositories`, each
`{"name": NAME, "url": CLONE_URL}`, with `branch_prefix`; and `review_query`, in GitHub's search syntax. On stdout, one
JSON line per observation, in DESIGN §30's shapes:

- for each PR read whole, its `pr` line (with its labels and mergeable state), a `check` line for each context at its
  head, check run or commit status, then a `review` line for each review (`"item": "review"`) and for each review
  comment (`"item": "comment"`, with its thread's id, path, line, side, and whether it is outdated or resolved);
- for each repository read whole, a `branch` line for each branch under the prefix.

Last, an `end` line naming the PRs and the repositories read whole and, when the review query was read to its end,
the PRs it returned, in its order. The PRs are read many to a query; the review query is run on each host the
repositories are on, or on github.com when none is named. What could not be read whole prints nothing but its error
on stderr, so a cut-off read never looks like a PR with no checks or a repository with no branches. Nothing is
written to GitHub.

Exit codes: 0 everything was read; 1 something was not, and the `end` line names what was; 2 stdin or the command line
is not usable, and nothing was read.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TextIO

import click

from canopy_github import (
    Client,
    Endpoint,
    GitHubError,
    Hosts,
    InputError,
    Ref,
    Repository,
    Token,
    client_for,
    emit,
    parse_pr,
    parse_repository,
    read_input,
)
from canopy_github.read import Pulled, pull_requests
from canopy_github.repository import branches, search

#: More than any one request needs: canopy names every PR of a ticket not marked done, and those drafts wait on.
MAX_PRS = 1000
#: More than any workspace's map holds.
MAX_REPOSITORIES = 100
#: The host a review query runs on when no repository names one.
DEFAULT_HOST = "github.com"
#: A repository's name as canopy sends it, and a branch prefix: plain, printable, one line.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
_PREFIX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,254}")


@dataclass(frozen=True)
class Asked:
    """A repository the request names, and its clone URL, if it has one."""

    name: str
    url: object = None


@dataclass(frozen=True)
class Request:
    """What one run is asked to observe. `repositories` is None when not asked, which the `end` line keeps apart."""

    prs: Sequence[Ref] = ()
    repositories: Sequence[Asked] | None = None
    branch_prefix: str = ""
    review_query: str | None = None


@click.command("canopy-connect-github", context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def main(ctx: click.Context) -> None:
    """Read GitHub's PRs and branches into canopy's journal: canopy's vcs source (DESIGN §29, §30).

    The request is one JSON object on stdin; what was read is JSON lines on stdout, the `end` line last.
    """
    hosts = ctx.find_object(Hosts) or Hosts()
    try:
        request = _request(read_input(sys.stdin))
    except InputError as e:
        _say(str(e))
        ctx.exit(2)
    reader = _Reader(sys.stdout, hosts.endpoint_of, hosts.token_of)
    reader.prs(request.prs)
    end: dict[str, object] = {"kind": "end", "prs": reader.whole_prs}
    repositories = [] if request.repositories is None else reader.repositories(request)
    if request.repositories is not None:
        end["repositories"] = reader.whole_repositories
    if request.review_query is not None:
        found = reader.review_query(request.review_query, repositories)
        if found is not None:
            end["review_query"] = found
    emit(sys.stdout, end)
    ctx.exit(1 if reader.failed else 0)


def _request(raw: Mapping[str, object]) -> Request:
    """Read the request: a key canopy sends another kind of source is not this one's, and is passed over.

    Returns:
        The request, each PR and repository once, in the order given.

    Raises:
        InputError: A PR, a repository, the branch prefix, or the review query is not usable.
    """
    prs = raw.get("prs", [])
    if not isinstance(prs, list):
        raise InputError('stdin\'s prs must be a list: {"prs": ["https://..."]}')
    if len(prs) > MAX_PRS:
        raise InputError(f"stdin names {len(prs)} PRs; at most {MAX_PRS} a read")
    refs = list({ref.url: ref for ref in map(parse_pr, prs)}.values())
    query = raw.get("review_query")
    if query is not None and not (isinstance(query, str) and query.strip()):
        raise InputError("the review query must be a string that is not blank")
    review_query = query if isinstance(query, str) else None
    if "repositories" not in raw:
        return Request(refs, None, review_query=review_query)
    asked = _repositories(raw["repositories"])
    prefix = raw.get("branch_prefix")
    if asked and not (isinstance(prefix, str) and _PREFIX.fullmatch(prefix)):
        raise InputError(f"the repositories need the branch prefix their branches are under, not {prefix!r}")
    return Request(refs, asked, branch_prefix=prefix if isinstance(prefix, str) else "", review_query=review_query)


def _repositories(raw: object) -> list[Asked]:
    """Read the repositories the request names.

    Returns:
        Each once, in the order given.

    Raises:
        InputError: They are not a list of repositories, each with a name.
    """
    if not isinstance(raw, list):
        raise InputError('stdin\'s repositories must be a list: {"repositories": [{"name": "api", "url": "..."}]}')
    if len(raw) > MAX_REPOSITORIES:
        raise InputError(f"stdin names {len(raw)} repositories; at most {MAX_REPOSITORIES} a read")
    asked: dict[str, Asked] = {}
    for repository in raw:
        if not isinstance(repository, dict):
            raise InputError(f"{repository!r} is not a repository: {{'name': NAME, 'url': CLONE_URL}}")
        name: object = repository.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise InputError(f"{name!r} is not a repository's name")
        asked.setdefault(name, Asked(name, repository.get("url")))
    return list(asked.values())


@dataclass
class _Reader:
    """One run's reads: a client for each host, what it printed whole, and whether anything was not read."""

    stdout: TextIO
    endpoint_of: Endpoint
    token_of: Token
    #: The PRs and repositories printed whole, in the order asked.
    whole_prs: list[str] = field(default_factory=list[str])
    whole_repositories: list[str] = field(default_factory=list[str])
    failed: bool = False
    #: Each host's client, or why it has none, as `gh` holds no token for it: asked once a run.
    _clients: dict[str, Client | InputError] = field(default_factory=dict[str, Client | InputError])

    def prs(self, refs: Sequence[Ref]) -> None:
        """Read each PR whole, many to a query on each host, and print them in the order asked."""
        found: dict[str, Pulled] = {}
        for host in sorted({ref.host for ref in refs}):
            on_host = [ref for ref in refs if ref.host == host]
            client = self._client(host)
            if isinstance(client, InputError):
                found.update((ref.url, Pulled(error=GitHubError(str(client), certain=True))) for ref in on_host)
                continue
            found.update(pull_requests(client, on_host))
        for ref in refs:
            pulled = found[ref.url]
            if pulled.error is not None:
                self._miss(ref.url, pulled.error)
                continue
            for line in pulled.lines:
                emit(self.stdout, line)
            self.whole_prs.append(ref.url)

    def repositories(self, request: Request) -> list[Repository]:
        """Read and print each repository's branches under the prefix.

        Returns:
            The repositories whose clone URL names where they are on GitHub, read whole or not.
        """
        found: list[Repository] = []
        for asked in request.repositories or ():
            try:
                repository = parse_repository(asked.name, asked.url)
            except InputError as e:
                self._miss(f"repository {asked.name}", e)
                continue
            found.append(repository)
            client = self._client(repository.host)
            if isinstance(client, InputError):
                self._miss(f"repository {asked.name}", client)
                continue
            try:
                lines = branches(client, repository, request.branch_prefix)
            except GitHubError as e:
                self._miss(f"repository {asked.name}", e)
                continue
            for line in lines:
                emit(self.stdout, line)
            self.whole_repositories.append(asked.name)
        return found

    def review_query(self, query: str, repositories: Sequence[Repository]) -> list[str] | None:
        """Run the review query on each host the repositories are on, or on github.com, each to its last page.

        Returns:
            The PRs it returned, each once, host by host in the order the repositories name them; None when it was not
            read to the end on every host.
        """
        urls: dict[str, None] = {}
        for host in list(dict.fromkeys(r.host for r in repositories)) or [DEFAULT_HOST]:
            client = self._client(host)
            if isinstance(client, InputError):
                self._miss(f"the review query on {host}", client)
                return None
            try:
                urls.update(dict.fromkeys(search(client, query)))
            except GitHubError as e:
                self._miss(f"the review query on {host}", e)
                return None
        return list(urls)

    def _client(self, host: str) -> Client | InputError:
        if host not in self._clients:
            try:
                self._clients[host] = client_for(host, self.endpoint_of, self.token_of)
            except InputError as e:
                self._clients[host] = e
        return self._clients[host]

    def _miss(self, what: str, why: object) -> None:
        self.failed = True
        _say(f"cannot read {what}: {why}")


def _say(message: str) -> None:
    print(f"canopy-connect-github: {message}", file=sys.stderr)  # noqa: T201
