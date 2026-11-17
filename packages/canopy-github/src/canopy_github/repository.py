"""Reading a repository's branches under canopy's prefix, and a search of a host's PRs.

What the `vcs` source reads beside the PRs it is named (DESIGN §30).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from canopy_github import Client, GitHubError, InputError, Repository, obj, pages, parse_pr, text

#: The most branches under the prefix a repository may have before it counts as not read: narrow the prefix.
MAX_BRANCHES: Final = 1000
#: The most results GitHub's search returns of one query; a query that matches more cannot be read to its end.
MAX_SEARCH: Final = 1000

_BRANCHES: Final = """
query Branches($owner: String!, $name: String!, $prefix: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    refs(refPrefix: "refs/heads/", query: $prefix, first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { name target { oid } }
    }
  }
}
"""

_SEARCH: Final = """
query Search($query: String!, $after: String) {
  search(query: $query, type: ISSUE, first: 100, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { url } }
  }
}
"""


def branches(client: Client, repository: Repository, prefix: str) -> list[Mapping[str, object]]:
    """A `branch` line for each branch of `repository` whose name starts with `prefix`, every page of them.

    GitHub matches `query` against a ref's name more loosely than a prefix, so each name is held to it here.

    Returns:
        The lines, in GitHub's order.

    Raises:
        GitHubError: A page could not be read, GitHub has no such repository, or it has more than `MAX_BRANCHES`.
    """
    where = f"repository {repository.owner}/{repository.repo}"

    def fetch(after: str | None) -> Mapping[str, object]:
        variables = {"owner": repository.owner, "name": repository.repo, "prefix": prefix, "after": after}
        return obj(obj(client.query(_BRANCHES, variables).get("repository"), where).get("refs"), "refs")

    lines: list[Mapping[str, object]] = []
    for node in pages(fetch):
        name, sha = text(node.get("name")), text(obj(node.get("target"), "target").get("oid"))
        if name is None or sha is None or not name.startswith(prefix):
            continue
        if len(lines) == MAX_BRANCHES:
            raise GitHubError(f"it has more than {MAX_BRANCHES} branches under {prefix}", certain=True)
        lines.append({"kind": "branch", "repository": repository.name, "name": name, "head_sha": sha})
    return lines


def search(client: Client, query: str) -> list[str]:
    """The PRs a search in GitHub's own syntax returns, to its last page; an issue it returns is passed over.

    Returns:
        Their URLs, each once, in the search's order.

    Raises:
        GitHubError: A page could not be read, or the search matches more than `MAX_SEARCH`, which GitHub cuts short.
    """

    def fetch(after: str | None) -> Mapping[str, object]:
        found = obj(client.query(_SEARCH, {"query": query, "after": after}).get("search"), "search")
        total = found.get("issueCount")
        if isinstance(total, int) and total > MAX_SEARCH:
            raise GitHubError(f"it matches {total}, more than the {MAX_SEARCH} GitHub returns", certain=True)
        return found

    urls: dict[str, None] = {}
    for node in pages(fetch):
        try:
            urls.setdefault(parse_pr(node.get("url")).url)
        except InputError:
            continue
    return list(urls)
