"""`canopy-post-github`: posts what the operator approved in canopy, word for word (DESIGN §29).

On stdin, one JSON object: one PR's drafts, `{"pr": URL, "delete_pending": ID | null, "body": TEXT | null,
"replies": [{"comment": ID, "text": TEXT | null, "reaction": REACTION | null}, ...]}`, posted as one review: a pending
review, each reply's text added to the thread of the review comment it names, the body as the review's, submitted as
`COMMENT`; or one ticket's, `{"issue": URL, "ticket": KEY, "body": TEXT}`, posted as one comment on that issue, which
must be numbered as the key is. `delete_pending` names a pending review an earlier post left, which is deleted first,
and only if it is still pending, on that PR, and the poster's own. A reply's `reaction`, one of `+1`, `-1`, `laugh`,
`confused`, `heart`, `hooray`, `rocket`, and `eyes`, is added to the comment it names before the review is opened; a
reply with a reaction and no text adds the reaction alone, and a PR's drafts that are all such open no review.

On stdout, one JSON line each: `as`, the login it posts as; for a PR, `reaction` for each reaction added (the comment,
the reaction, and the comment's URL), then `pending`, the pending review's node id and its id, once it has one; once it
is submitted, `comment` for each reply (the comment it answered, the new comment's id and URL) and `review` (its id and
URL); for an issue, `comment`; last, `end`, saying whether it submitted: `"submitted": true` once the review or the
issue comment is submitted, or once every reaction is added when there is nothing else to post. `"submitted": false` is
printed only when nothing but the reactions its `reaction` lines name was posted, with `pending` naming a pending review
it could not delete; a pending review GitHub may have opened without saying so is looked for and deleted. No `end` line
means the outcome is unknown: the submit may have reached GitHub. A reaction GitHub already holds is not added twice, so
a reaction whose outcome is unknown is one to send again, never one that can post twice.

It never approves, requests changes, resolves a thread, or deletes a review but the pending one it is handed.

Exit codes: 0 posted; 1 GitHub refused, or the outcome is unknown, as the `end` line says; 2 stdin is not usable, `gh`
holds no token for the host, or a reply names a comment the PR has no thread for, and nothing was posted.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TextIO

from canopy_github import (
    Client,
    Endpoint,
    GitHubError,
    InputError,
    Ref,
    Token,
    client_for,
    emit,
    endpoint,
    gh_token,
    items,
    number,
    obj,
    parse_issue,
    parse_pr,
    read_input,
    text,
)
from canopy_github.read import threads

# GitHub's own limit on a comment's body.
MAX_TEXT = 65536
# Each reaction a reply may add, by the name canopy and GitHub's REST API give it, to the name GraphQL takes.
REACTIONS = {
    "+1": "THUMBS_UP",
    "-1": "THUMBS_DOWN",
    "laugh": "LAUGH",
    "confused": "CONFUSED",
    "heart": "HEART",
    "hooray": "HOORAY",
    "rocket": "ROCKET",
    "eyes": "EYES",
}
MAX_REPLIES = 100
# A key a GitHub Issues tracker gives a ticket: letters, a hyphen, the issue's number (DESIGN §17).
_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*-([1-9][0-9]{0,9})")

_VIEWER = "query Viewer { viewer { login } }"
_PR_ID = """
query PullRequestId($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) { id } }
}
"""
_ISSUE_ID = """
query IssueId($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { issue(number: $number) { id } }
}
"""
_PENDING = """
query PendingReviews($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) { reviews(states: [PENDING], first: 10) { nodes { id author { login } } } }
  }
}
"""
_REVIEW = """
query Review($id: ID!) {
  node(id: $id) { ... on PullRequestReview { state author { login } pullRequest { id } } }
}
"""
_ADD_REVIEW = """
mutation AddReview($pr: ID!) {
  addPullRequestReview(input: {pullRequestId: $pr}) { pullRequestReview { id fullDatabaseId } }
}
"""
_REPLY = """
mutation Reply($review: ID!, $thread: ID!, $body: String!) {
  addPullRequestReviewThreadReply(
    input: {pullRequestReviewId: $review, pullRequestReviewThreadId: $thread, body: $body}
  ) {
    comment { fullDatabaseId url }
  }
}
"""
_SUBMIT = """
mutation Submit($review: ID!, $body: String) {
  submitPullRequestReview(input: {pullRequestReviewId: $review, event: COMMENT, body: $body}) {
    pullRequestReview { fullDatabaseId url state }
  }
}
"""
_DELETE = """
mutation Delete($review: ID!) { deletePullRequestReview(input: {pullRequestReviewId: $review}) { clientMutationId } }
"""
_REACT = """
mutation React($subject: ID!, $content: ReactionContent!) {
  addReaction(input: {subjectId: $subject, content: $content}) { reaction { content } }
}
"""
_COMMENT = """
mutation Comment($subject: ID!, $body: String!) {
  addComment(input: {subjectId: $subject, body: $body}) { commentEdge { node { fullDatabaseId url } } }
}
"""


@dataclass(frozen=True)
class Reply:
    """A reply to post: the review comment whose thread it answers, its text, and its reaction on that comment.

    At least one of the text and the reaction is set.
    """

    comment: int
    text: str | None
    reaction: str | None


@dataclass(frozen=True)
class Review:
    """One PR's drafts, to post as one comment review."""

    pr: Ref
    delete_pending: str | None
    body: str | None
    replies: tuple[Reply, ...]


@dataclass(frozen=True)
class IssueComment:
    """One ticket's draft, to post as one comment on its issue."""

    issue: Ref
    body: str


class UnknownOutcomeError(GitHubError):
    """A submit or a comment that may have reached GitHub: no `end` line is printed for it."""

    def __init__(self, cause: GitHubError) -> None:
        """Wrap `cause`, which left the outcome unknown."""
        super().__init__(f"the outcome is unknown: {cause}", certain=False)


class Out:
    """What the program prints, and whether its `end` line is printed yet."""

    def __init__(self, stdout: TextIO) -> None:
        """Print to `stdout`."""
        self._stdout = stdout
        self.ended = False

    def line(self, line: Mapping[str, object]) -> None:
        """Print one line."""
        emit(self._stdout, line)
        if line.get("kind") == "end":
            self.ended = True


def run(
    argv: Sequence[str],
    stdin: TextIO,
    stdout: TextIO,
    *,
    endpoint_of: Endpoint = endpoint,
    token_of: Token = gh_token,
) -> int:
    """Post what `stdin` holds, and print what was posted on `stdout`.

    `endpoint_of` and `token_of` map a host to its GraphQL endpoint and its token.

    Returns:
        The exit code: 0 posted, 1 refused or unknown, 2 nothing posted for want of usable input.
    """
    parser = argparse.ArgumentParser(prog="canopy-post-github", description=__doc__.split("\n", 1)[0])
    parser.parse_args(argv)
    out = Out(stdout)
    try:
        request = parse_request(read_input(stdin))
        ref = request.pr if isinstance(request, Review) else request.issue
        client = client_for(ref.host, endpoint_of, token_of)
    except InputError as e:
        print(f"canopy-post-github: {e}", file=sys.stderr)  # noqa: T201
        return 2
    try:
        login = _id(obj(client.query(_VIEWER, {}).get("viewer"), "viewer").get("login"), "viewer's login")
        out.line({"kind": "as", "login": login})
        if isinstance(request, Review):
            post_review(client, request, login, out)
        else:
            post_comment(client, request, out)
    except InputError as e:
        # Refused before anything was opened, so nothing was posted.
        out.line({"kind": "end", "submitted": False})
        print(f"canopy-post-github: {e}", file=sys.stderr)  # noqa: T201
        return 2
    except GitHubError as e:
        # Anything but an unknown submit failed before what it posted could be seen.
        if not out.ended and not isinstance(e, UnknownOutcomeError):
            out.line({"kind": "end", "submitted": False})
        print(f"canopy-post-github: {e}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


def parse_request(request: Mapping[str, object]) -> Review | IssueComment:
    """Read one PR's or one ticket's drafts from what stdin held.

    Returns:
        What to post.

    Raises:
        InputError: It is neither shape, a text is empty or too long, or a reaction is not one GitHub offers.
    """
    if "issue" in request:
        issue = parse_issue(request.get("issue"))
        key = request.get("ticket")
        match = _KEY.fullmatch(key) if isinstance(key, str) else None
        if match is None or int(match.group(1)) != issue.number:
            raise InputError(f"ticket {key!r} is not issue #{issue.number}'s key")
        return IssueComment(issue=issue, body=_text(request.get("body"), "body"))
    pr = parse_pr(request.get("pr"))
    pending = request.get("delete_pending")
    if pending is not None and not (isinstance(pending, str) and pending):
        raise InputError("delete_pending must be a review's id or null")
    raw = request.get("replies", [])
    if not isinstance(raw, list) or len(raw) > MAX_REPLIES:
        raise InputError(f"replies must be a list of at most {MAX_REPLIES}")
    replies = tuple(_reply(r) for r in raw)
    body = request.get("body")
    if body is None and not replies:
        raise InputError("there is nothing to post: no body and no replies")
    return Review(
        pr=pr,
        delete_pending=pending,
        body=None if body is None else _text(body, "body"),
        replies=replies,
    )


def _reply(raw: object) -> Reply:
    found = items([raw])
    comment = number(found[0].get("comment")) if found else None
    if comment is None:
        raise InputError("each reply needs the id of the review comment it answers, and its text or reaction")
    reaction, text = found[0].get("reaction"), found[0].get("text")
    if reaction is not None and reaction not in REACTIONS:
        raise InputError(f"a reply's reaction must be one of {', '.join(REACTIONS)}")
    if reaction is not None and text is None:
        return Reply(comment=comment, text=None, reaction=str(reaction))
    return Reply(comment=comment, text=_text(text, "reply"), reaction=None if reaction is None else str(reaction))


def _text(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"the {what} is empty")
    if len(value) > MAX_TEXT:
        raise InputError(f"the {what} is longer than GitHub's {MAX_TEXT} characters")
    return value


def post_review(client: Client, review: Review, login: str, out: Out) -> None:
    """Post `review`'s drafts as one comment review, printing as the module says.

    Raises:
        InputError: A reply names a comment the PR has no thread for, or the pending review to delete is not one.
        GitHubError: GitHub refused a reaction, which opened no review; or as `_submit` raises it.
    """
    pr = review.pr
    found = {line.get("id"): (thread.id, line) for thread in threads(client, pr) for line in thread.comments}
    missing = [r.comment for r in review.replies if r.comment not in found]
    if missing:
        raise InputError(f"{pr.url} has no review thread with comment {', '.join(map(str, missing))}")
    variables = {"owner": pr.owner, "name": pr.name, "number": pr.number}
    pr_id = _id(obj(_repository(client, _PR_ID, variables).get("pullRequest"), "pullRequest").get("id"), "PR's id")
    if review.delete_pending is not None:
        _delete_left(client, review.delete_pending, pr_id, login)
    # First, since GitHub adds a reaction once however often it is asked: one added before a review that then fails
    # stays added, and sending again adds nothing more.
    for reply in review.replies:
        if reply.reaction is not None:
            _react(client, reply.comment, found[reply.comment][1], reply.reaction, out)
    replies = [(r.comment, found[r.comment][0], r.text) for r in review.replies if r.text is not None]
    if review.body is None and not replies:
        out.line({"kind": "end", "submitted": True})
        return
    _submit(client, pr, pr_id, review.body, replies, login, out)


def _submit(  # noqa: PLR0917  (what one review is posted from)
    client: Client,
    pr: Ref,
    pr_id: str,
    body: str | None,
    replies: Sequence[tuple[int, str, str]],
    login: str,
    out: Out,
) -> None:
    """Post `body` and `replies`, each a comment answered, its thread's node id, and the text, as one comment review.

    Raises:
        UnknownOutcomeError: The submit may have reached GitHub.
        GitHubError: GitHub refused before anything of it could be seen; the pending review is deleted, or named.
    """
    try:
        added = obj(client.query(_ADD_REVIEW, {"pr": pr_id}).get("addPullRequestReview"), "addPullRequestReview")
        opened = obj(added.get("pullRequestReview"), "pullRequestReview")
        pending = _id(opened.get("id"), "pending review's id")
    except GitHubError as e:
        if not e.certain:
            # GitHub may have opened it, and the next post could open no other while it stands.
            _abandon_unseen(client, pr, login, out)
        raise
    out.line({"kind": "pending", "review": pending, "id": number(opened.get("fullDatabaseId"))})
    posted: list[Mapping[str, object]] = []
    try:
        for answered, thread, words in replies:
            variables = {"review": pending, "thread": thread, "body": words}
            data = obj(client.query(_REPLY, variables).get("addPullRequestReviewThreadReply"), "reply")
            comment = obj(data.get("comment"), "comment")
            posted.append({"comment": answered, "id": number(comment.get("fullDatabaseId")), "url": comment.get("url")})
    except GitHubError:
        # Nobody else sees a pending review or its replies, so a reply that failed posted nothing.
        _abandon(client, pending, out)
        raise
    try:
        submit = client.query(_SUBMIT, {"review": pending, "body": body})
    except GitHubError as e:
        if not e.certain:
            raise UnknownOutcomeError(e) from e
        _abandon(client, pending, out)
        raise
    submitted = obj(obj(submit.get("submitPullRequestReview"), "submit").get("pullRequestReview"), "review")
    for line in posted:
        out.line({"kind": "comment", **line})
    out.line({"kind": "review", "id": number(submitted.get("fullDatabaseId")), "url": submitted.get("url")})
    out.line({"kind": "end", "submitted": True})


def _react(client: Client, comment: int, line: Mapping[str, object], reaction: str, out: Out) -> None:
    """Add the poster's `reaction` to review comment `comment`, whose line as the reader prints it is `line`.

    Raises:
        GitHubError: GitHub refused it, or its outcome is unknown; either way it is safe to send again.
    """
    subject = _id(line.get("node"), "review comment's node id")
    client.query(_REACT, {"subject": subject, "content": REACTIONS[reaction]})
    out.line({"kind": "reaction", "comment": comment, "reaction": reaction, "url": line.get("url")})


def _id(value: object, what: str) -> str:
    """`value` as an id GitHub sent, so a reply missing one is never passed on as null.

    Returns:
        The id.

    Raises:
        GitHubError: There is none, so GitHub's reply is not the shape asked for.
    """
    found = text(value)
    if not found:
        raise GitHubError(f"GitHub's reply has no {what}", certain=False)
    return found


def _repository(client: Client, document: str, variables: Mapping[str, object]) -> Mapping[str, object]:
    return obj(client.query(document, variables).get("repository"), "repository")


def _delete_left(client: Client, review_id: str, pr_id: str, login: str) -> None:
    """Delete the pending review an earlier post left, if it is still that: pending, on this PR, the poster's own.

    Raises:
        InputError: It was submitted, so it posted, or it is someone else's or another PR's.
        GitHubError: GitHub refused to look it up or to delete it.
    """
    try:
        node = client.query(_REVIEW, {"id": review_id}).get("node")
    except GitHubError as e:
        if "NOT_FOUND" in e.types:
            return
        raise
    if not isinstance(node, dict) or not node:
        return
    found = obj(node, "review")
    on = text(obj(found.get("pullRequest"), "pullRequest").get("id"))
    author = found.get("author")
    by = text(obj(author, "author").get("login")) if isinstance(author, dict) else None
    if on != pr_id or by != login:
        raise InputError(f"review {review_id} is not a review of this PR by {login}")
    if found.get("state") != "PENDING":
        raise InputError(f"review {review_id} was submitted, so what it held is posted")
    client.query(_DELETE, {"review": review_id})


def _abandon_unseen(client: Client, pr: Ref, login: str, out: Out) -> None:
    """Delete the poster's own pending review on `pr`, which GitHub may have opened without saying so."""
    variables = {"owner": pr.owner, "name": pr.name, "number": pr.number}
    try:
        found = obj(_repository(client, _PENDING, variables).get("pullRequest"), "pullRequest")
    except GitHubError:
        return
    for node in items(obj(found.get("reviews"), "reviews").get("nodes")):
        author = node.get("author")
        by = text(author.get("login")) if isinstance(author, dict) else None
        pending = text(node.get("id"))
        if by == login and pending:
            _abandon(client, pending, out)
            return


def _abandon(client: Client, pending: str, out: Out) -> None:
    try:
        client.query(_DELETE, {"review": pending})
    except GitHubError:
        out.line({"kind": "end", "submitted": False, "pending": pending})
        return
    out.line({"kind": "end", "submitted": False})


def post_comment(client: Client, comment: IssueComment, out: Out) -> None:
    """Post `comment` on its issue, printing as the module says.

    Raises:
        UnknownOutcomeError: The comment may have reached GitHub.
        GitHubError: GitHub refused it, so nothing was posted.
    """
    issue = comment.issue
    variables = {"owner": issue.owner, "name": issue.name, "number": issue.number}
    subject = text(obj(_repository(client, _ISSUE_ID, variables).get("issue"), f"issue {issue.url}").get("id"))
    try:
        data = obj(client.query(_COMMENT, {"subject": subject, "body": comment.body}).get("addComment"), "addComment")
    except GitHubError as e:
        if e.certain:
            raise
        raise UnknownOutcomeError(e) from e
    node = obj(obj(data.get("commentEdge"), "commentEdge").get("node"), "comment")
    out.line({"kind": "comment", "id": number(node.get("fullDatabaseId")), "url": node.get("url")})
    out.line({"kind": "end", "submitted": True})


def main() -> int:
    """The `canopy-post-github` command.

    Returns:
        The exit code.
    """
    return run(sys.argv[1:], sys.stdin, sys.stdout)
