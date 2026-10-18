"""`canopy-connect-github`: canopy's GitHub reader (DESIGN §29). Prints what it reads of each PR it is given.

On stdin, one JSON object naming the PRs to read: `{"prs": ["https://HOST/OWNER/REPO/pull/N", ...]}`. On stdout, one
JSON line per observation, in ROADMAP M36's shapes: for each PR read whole, its `pr` line, then a `review` line for
each review (`"item": "review"`) and for each review comment (`"item": "comment"`, with its thread's id, path, line,
side, and whether it is outdated or resolved). Last, an `end` line naming the PRs read whole. A PR that could not be
read whole prints nothing but its error on stderr, so a cut-off read never looks like a PR with no reviews.

Exit codes: 0 every PR was read whole; 1 some were not, and the `end` line names those that were; 2 stdin is not
usable, or `gh` holds no token for a PR's host, and nothing was read.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO

from canopy_github import (
    Endpoint,
    GitHubError,
    InputError,
    Ref,
    Token,
    client_for,
    emit,
    endpoint,
    gh_token,
    parse_pr,
    read_input,
)
from canopy_github.read import pull_request

# More than any one read needs: canopy names the PRs of one run, or of the drafts waiting.
MAX_PRS = 100


def run(
    argv: Sequence[str],
    stdin: TextIO,
    stdout: TextIO,
    *,
    endpoint_of: Endpoint = endpoint,
    token_of: Token = gh_token,
) -> int:
    """Read the PRs named on `stdin`, and print what was read on `stdout`.

    `endpoint_of` and `token_of` map a host to its GraphQL endpoint and its token.

    Returns:
        The exit code: 0 every PR read whole, 1 some were not, 2 nothing was read.
    """
    parser = argparse.ArgumentParser(prog="canopy-connect-github", description=__doc__.split("\n", 1)[0])
    parser.parse_args(argv)
    try:
        refs = _refs(read_input(stdin))
        clients = {host: client_for(host, endpoint_of, token_of) for host in sorted({r.host for r in refs})}
    except InputError as e:
        print(f"canopy-connect-github: {e}", file=sys.stderr)  # noqa: T201
        return 2
    whole: list[str] = []
    for ref in refs:
        try:
            lines = pull_request(clients[ref.host], ref)
        except GitHubError as e:
            print(f"canopy-connect-github: cannot read {ref.url}: {e}", file=sys.stderr)  # noqa: T201
            continue
        for line in lines:
            emit(stdout, line)
        whole.append(ref.url)
    emit(stdout, {"kind": "end", "prs": whole})
    return 0 if len(whole) == len(refs) else 1


def _refs(request: Mapping[str, object]) -> list[Ref]:
    prs = request.get("prs")
    if not isinstance(prs, list) or not prs:
        raise InputError('stdin must name the PRs to read: {"prs": ["https://..."]}')
    if len(prs) > MAX_PRS:
        raise InputError(f"stdin names {len(prs)} PRs; at most {MAX_PRS} a read")
    # Each PR once, in the order given.
    return list({ref.url: ref for ref in map(parse_pr, prs)}.values())


def main() -> int:
    """The `canopy-connect-github` command.

    Returns:
        The exit code.
    """
    return run(sys.argv[1:], sys.stdin, sys.stdout)
