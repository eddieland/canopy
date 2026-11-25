"""`canopy-post-github`: posts what the operator approved in canopy, word for word (DESIGN §29, §34).

On stdin, one JSON object: one PR's drafts, `{"pr": URL, "delete_pending": ID | null, "body": TEXT | null,
"replies": [{"comment": ID, "text": TEXT | null, "reaction": REACTION | null}, ...]}`, posted as one review: a pending
review, each reply's text added to the thread of the review comment it names, the body as the review's, submitted as
`COMMENT`; or one ticket's, `{"issue": URL, "ticket": KEY, "body": TEXT}`, posted as one comment on that issue, which
must be numbered as the key is. A review of a PR canopy reviewed (§34) names the commit it read, `"commit": SHA`, and
its comments, `"comments": [{"path": PATH, "line": N, "text": TEXT}, ...]`: the pending review is opened on that
commit, and each comment starts a thread of its own on line N of PATH, on the commit's side, before the submit. A
PR's drafts with `"submit": false` are staged instead: the pending review is opened with the body as its own and each
reply and comment added, and left for the operator to submit on GitHub. `delete_pending` names a pending review an
earlier post left, which is deleted first, and only if it is still pending, on that PR, and the poster's own.

GitHub keeps one pending review a person on a PR, so a stage on a PR where the poster already has one adds to that one
instead, joining it: its own comments and body stay as they are, and it is neither submitted nor deleted. A reply or a
comment it already holds, word for word on the same thread or line, as an earlier stage that stopped part way left, is
not added again. The body goes in as the review's own when it has none, and below it, after a blank line, when it has
one that does not already hold it, so neither text is lost. A review whose comments sit on another commit than the
request's, or whose body and the request's together are longer than GitHub takes, is refused, and nothing is added. A
post that submits is refused on such a PR, since submitting would submit what the review already holds. A pending
review that turns up between the look and the opening is joined as well.

A reply's `reaction`, one of `+1`, `-1`, `laugh`, `confused`, `heart`, `hooray`, `rocket`, and `eyes`, is added to the
comment it names before the review is opened, staged or not, since GitHub has no pending reaction; a reply with a
reaction and no text adds the reaction alone, and a PR's drafts that are all such open no review.

On stdout, one JSON line each: `as`, the login it posts as; for a PR, `reaction` for each reaction added (the comment,
the reaction, and the comment's URL), then `pending`, the pending review's node id and its id, once it has one, with
`"joined": true` for one it joined; once it is submitted, `comment` for each reply (the comment it answered, the new
comment's id and URL), and for each of `comments` (its `index` there, from 1, and the new comment's id and URL), and
`review` (its id and URL); once a staged review holds every reply and comment, their `comment` lines; for an issue,
`comment`; last, `end`, saying whether it submitted: `"submitted": true` once the review or the issue comment is
submitted, or once every reaction is added when there is nothing else to post; `"submitted": false, "staged": true`
once a staged review holds every reply, with `"joined": true` for one it joined. A joined review GitHub refused part of
is left as it is, never deleted: the `comment` lines name each reply and comment it now holds, and `end` says
`"submitted": false, "joined": true`, so a later stage adds only the rest. Otherwise `"submitted": false` is printed
only when nothing but the reactions its `reaction` lines name was posted, with `pending` naming a pending review it
could not delete; a pending review GitHub may have opened without saying so is looked for and deleted. No `end` line
means the outcome is unknown: the submit may have reached GitHub. A reaction GitHub already holds is not added twice, so
a reaction whose outcome is unknown is one to send again, never one that can post twice.

It never approves, requests changes, resolves a thread, or deletes a review but the pending one it is handed, or one it
opened and could not fill; never one it joined.

Exit codes: 0 posted; 1 GitHub refused, or the outcome is unknown, as the `end` line says; 2 stdin or the command line
is not usable, `gh` holds no token for the host, or a reply names a comment the PR has no thread for, and nothing was
posted. A comment GitHub refuses, as on a line its diff of the PR does not show, posts nothing of a review the poster
opened, and the error names it.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TextIO

import click

from canopy_github import (
    Client,
    GitHubError,
    Hosts,
    InputError,
    Ref,
    client_for,
    emit,
    items,
    number,
    obj,
    parse_issue,
    parse_pr,
    read_input,
    text,
)
from canopy_github.read import threads

#: GitHub's own limit on a comment's body.
MAX_TEXT: Final = 65536
#: Each reaction a reply may add, by the name canopy and GitHub's REST API give it, to the name GraphQL takes.
REACTIONS: Final = {
    "+1": "THUMBS_UP",
    "-1": "THUMBS_DOWN",
    "laugh": "LAUGH",
    "confused": "CONFUSED",
    "heart": "HEART",
    "hooray": "HOORAY",
    "rocket": "ROCKET",
    "eyes": "EYES",
}
MAX_REPLIES: Final = 100
#: As many comments as replies: canopy sends at most 30 (DESIGN §34).
MAX_COMMENTS: Final = 100
#: A commit's full object id, SHA-1 or SHA-256, as GitHub's `GitObjectID` takes it.
_COMMIT: Final = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
#: A key a GitHub Issues tracker gives a ticket: letters, a hyphen, the issue's number (DESIGN §17).
_KEY: Final = re.compile(r"[A-Za-z][A-Za-z0-9_]*-([1-9][0-9]{0,9})")
#: How many pages of a joined review's comments are read to find those already in it: 100 to a page.
_MAX_HELD_PAGES: Final = 20
#: What GitHub's refusal to open a second pending review a person says.
_ONE_PENDING: Final = "one pending review"

_VIEWER: Final = "query Viewer { viewer { login } }"
_PR_ID: Final = """
query PullRequestId($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) { id } }
}
"""
_ISSUE_ID: Final = """
query IssueId($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { issue(number: $number) { id } }
}
"""
_PENDING: Final = """
query PendingReviews($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviews(states: [PENDING], first: 10) {
        nodes { id fullDatabaseId author { login } body comments { totalCount } }
      }
    }
  }
}
"""
_HELD: Final = """
query PendingReview($id: ID!, $after: String) {
  node(id: $id) {
    ... on PullRequestReview {
      state body commit { oid }
      comments(first: 100, after: $after) {
        nodes { fullDatabaseId url body path line originalLine replyTo { fullDatabaseId } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
_REVIEW: Final = """
query Review($id: ID!) {
  node(id: $id) { ... on PullRequestReview { state author { login } pullRequest { id } } }
}
"""
_ADD_REVIEW: Final = """
mutation AddReview($pr: ID!, $body: String, $commit: GitObjectID) {
  addPullRequestReview(input: {pullRequestId: $pr, body: $body, commitOID: $commit}) {
    pullRequestReview { id fullDatabaseId }
  }
}
"""
_REPLY: Final = """
mutation Reply($review: ID!, $thread: ID!, $body: String!) {
  addPullRequestReviewThreadReply(
    input: {pullRequestReviewId: $review, pullRequestReviewThreadId: $thread, body: $body}
  ) {
    comment { fullDatabaseId url }
  }
}
"""
_THREAD: Final = """
mutation Thread($review: ID!, $path: String!, $line: Int!, $body: String!) {
  addPullRequestReviewThread(
    input: {pullRequestReviewId: $review, path: $path, line: $line, side: RIGHT, body: $body}
  ) {
    thread { comments(first: 1) { nodes { fullDatabaseId url } } }
  }
}
"""
_SUBMIT: Final = """
mutation Submit($review: ID!, $body: String) {
  submitPullRequestReview(input: {pullRequestReviewId: $review, event: COMMENT, body: $body}) {
    pullRequestReview { fullDatabaseId url state }
  }
}
"""
_UPDATE: Final = """
mutation UpdateReview($review: ID!, $body: String!) {
  updatePullRequestReview(input: {pullRequestReviewId: $review, body: $body}) { pullRequestReview { id } }
}
"""
_DELETE: Final = """
mutation Delete($review: ID!) { deletePullRequestReview(input: {pullRequestReviewId: $review}) { clientMutationId } }
"""
_REACT: Final = """
mutation React($subject: ID!, $content: ReactionContent!) {
  addReaction(input: {subjectId: $subject, content: $content}) { reaction { content } }
}
"""
_COMMENT: Final = """
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
class NewComment:
    """A comment that starts a thread of its own: the file, the line on the commit's side, and its text."""

    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Review:
    """One PR's drafts, to post as one comment review, or with `submit` false to stage as a pending one.

    A review of a commit canopy reviewed names it, `commit`, and carries its `comments`, each a thread of its own.
    """

    pr: Ref
    delete_pending: str | None
    body: str | None
    replies: tuple[Reply, ...]
    submit: bool = True
    commit: str | None = None
    comments: tuple[NewComment, ...] = ()


@dataclass(frozen=True)
class IssueComment:
    """One ticket's draft, to post as one comment on its issue."""

    issue: Ref
    body: str


@dataclass(frozen=True)
class Pending:
    """The poster's own pending review on a PR, as read before a stage adds to it."""

    node: str
    id: int | None
    body: str
    #: The commit it is opened on, if GitHub names one.
    commit: str | None
    #: Each comment it holds, as GitHub's `comments` of the review lists them.
    comments: tuple[Mapping[str, object], ...]


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


@click.command("canopy-post-github", context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def main(ctx: click.Context) -> None:
    """Post what the operator approved in canopy, word for word (DESIGN §29, §34).

    What to post is one JSON object on stdin; what was posted is JSON lines on stdout, the `end` line last.
    """
    hosts = ctx.find_object(Hosts) or Hosts()
    out = Out(sys.stdout)
    try:
        request = parse_request(read_input(sys.stdin))
        ref = request.pr if isinstance(request, Review) else request.issue
        client = client_for(ref.host, hosts.endpoint_of, hosts.token_of)
    except InputError as e:
        print(f"canopy-post-github: {e}", file=sys.stderr)  # noqa: T201
        ctx.exit(2)
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
        ctx.exit(2)
    except GitHubError as e:
        # Anything but an unknown submit failed before what it posted could be seen.
        if not out.ended and not isinstance(e, UnknownOutcomeError):
            out.line({"kind": "end", "submitted": False})
        print(f"canopy-post-github: {e}", file=sys.stderr)  # noqa: T201
        ctx.exit(1)


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
    commit, comments = _comments(request)
    body = request.get("body")
    if body is None and not replies and not comments:
        raise InputError("there is nothing to post: no body, no replies, and no comments")
    submit = request.get("submit", True)
    if not isinstance(submit, bool):
        raise InputError("submit must be true or false")
    return Review(
        pr=pr,
        delete_pending=pending,
        body=None if body is None else _text(body, "body"),
        replies=replies,
        submit=submit,
        commit=commit,
        comments=comments,
    )


def _comments(request: Mapping[str, object]) -> tuple[str | None, tuple[NewComment, ...]]:
    """The commit a review is opened on and the comments that start threads on it, if the request names them.

    Returns:
        The commit, or None, and the comments.

    Raises:
        InputError: The commit is not a full commit id, or a comment is not a file, a line, and a text; or comments
            come without a commit.
    """
    commit = request.get("commit")
    if commit is not None and not (isinstance(commit, str) and _COMMIT.fullmatch(commit)):
        raise InputError("commit must be a commit's full id")
    raw = request.get("comments", [])
    if not isinstance(raw, list) or len(raw) > MAX_COMMENTS:
        raise InputError(f"comments must be a list of at most {MAX_COMMENTS}")
    if raw and commit is None:
        raise InputError("comments need the commit they are on")
    comments: list[NewComment] = []
    for found in raw:
        entry = items([found])
        path = text(entry[0].get("path")) if entry else None
        line = number(entry[0].get("line")) if entry else None
        if not path or line is None or isinstance(entry[0].get("line"), str):
            raise InputError("each comment needs its file's path, a line, and its text")
        comments.append(NewComment(path=path, line=line, text=_text(entry[0].get("text"), "comment")))
    return commit, tuple(comments)


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
    """Post `review`'s drafts as one comment review, or stage them as a pending one, printing as the module says.

    A stage on a PR where the poster has a pending review already adds to that one (`_join`).

    Raises:
        InputError: A reply names a comment the PR has no thread for, or the pending review to delete is not one.
        GitHubError: GitHub refused a reaction, which opened no review; the poster's own pending review cannot take
            this one, and nothing was posted; or as `_submit` and `_join` raise it.
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
    replies = [(r.comment, found[r.comment][0], r.text) for r in review.replies if r.text is not None]
    opens = review.body is not None or bool(replies) or bool(review.comments)
    # Looked for before anything is added, so a review that cannot take this one is refused with nothing posted.
    own = _own_pending(client, pr, login) if opens else None
    if own is not None:
        _check_joinable(own, review)
    # First, since GitHub adds a reaction once however often it is asked: one added before a review that then fails
    # stays added, and sending again adds nothing more.
    for reply in review.replies:
        if reply.reaction is not None:
            _react(client, reply.comment, found[reply.comment][1], reply.reaction, out)
    if not opens:
        out.line({"kind": "end", "submitted": True})
        return
    joining = _Joining(replies=replies, thread_of={c: t for c, (t, _) in found.items() if isinstance(c, int)})
    if own is not None:
        _join(client, own, review, joining, out)
        return
    _submit(client, pr, pr_id, review, joining, login, out)


@dataclass(frozen=True)
class _Joining:
    """What a review adds as replies, and the thread each comment of the PR's is on, to know one already added."""

    #: Each reply: the comment answered, its thread's node id, and the text.
    replies: Sequence[tuple[int, str, str]]
    #: Each review comment of the PR's threads, by its id, to its thread's node id.
    thread_of: Mapping[int, str]


def _own_pending(client: Client, pr: Ref, login: str) -> Pending | None:
    """The poster's own pending review on `pr`, if it has one, read whole: GitHub keeps one a person.

    Returns:
        It, or None.

    Raises:
        GitHubError: GitHub refused to look, or the review was submitted or deleted while it was read.
    """
    variables = {"owner": pr.owner, "name": pr.name, "number": pr.number}
    found = obj(_repository(client, _PENDING, variables).get("pullRequest"), "pullRequest")
    for node in items(obj(found.get("reviews"), "reviews").get("nodes")):
        review = text(node.get("id"))
        if _author(node) == login and review:
            return _held(client, review, number(node.get("fullDatabaseId")))
    return None


def _held(client: Client, review: str, review_id: int | None) -> Pending:
    """Pending review `review`, whose id is `review_id`, with every comment it holds.

    Returns:
        It.

    Raises:
        GitHubError: It is no longer pending, it holds more comments than are read, or GitHub refused a page.
    """
    comments: list[Mapping[str, object]] = []
    after: str | None = None
    for _ in range(_MAX_HELD_PAGES):
        node = obj(client.query(_HELD, {"id": review, "after": after}).get("node"), "pending review")
        if node.get("state") != "PENDING":
            raise GitHubError(f"your pending review {review} was submitted or deleted meanwhile", certain=True)
        connection = obj(node.get("comments"), "comments")
        comments.extend(items(connection.get("nodes")))
        info = obj(connection.get("pageInfo"), "pageInfo")
        after = text(info.get("endCursor"))
        if info.get("hasNextPage") is not True or after is None:
            commit = node.get("commit")
            return Pending(
                node=review,
                id=review_id,
                body=text(node.get("body")) or "",
                commit=text(commit.get("oid")) if isinstance(commit, dict) else None,
                comments=tuple(comments),
            )
    raise GitHubError(f"your pending review {review} holds too many comments to check which are added", certain=True)


def _check_joinable(own: Pending, review: Review) -> None:
    """Refuse to add `review` to the poster's own pending review `own` when it cannot take it as it is.

    Raises:
        GitHubError: `review` submits, which would submit what `own` holds too; its comments sit on another commit
            than `own`; or the two bodies together are longer than GitHub takes. Nothing is added.
    """
    where = f"you have a pending review on {review.pr.url}"
    if review.submit:
        raise GitHubError(
            f"{where}, and GitHub keeps one pending review a person: submitting would submit what it holds too, so "
            "canopy added nothing. Submit or delete it on GitHub, or stage this instead, which adds to it",
            certain=True,
        )
    if review.comments and own.commit != review.commit:
        raise GitHubError(
            f"{where} on commit {own.commit or 'unknown'}, and these comments are on lines of {review.commit}, so "
            "canopy added nothing to it. Submit or delete it on GitHub, then stage this again",
            certain=True,
        )
    body = _joined_body(own.body, review.body)
    if body is not None and len(body) > MAX_TEXT:
        raise GitHubError(
            f"{where}, and its body with this one below it would be longer than GitHub's {MAX_TEXT} characters, so "
            "canopy added nothing to it",
            certain=True,
        )


def _joined_body(held: str, body: str | None) -> str | None:
    """The body of a joined review that holds `held`, with `body` added; None when it needs no change.

    `body` goes in as the review's own when it has none, and below `held`, after a blank line, when `held` does not
    already hold it, as an earlier stage that stopped part way may have left it: neither text is lost.

    Returns:
        The body to set, or None.
    """
    if body is None or _plain(body) in _plain(held):
        return None
    if not held.strip():
        return body
    return f"{held.rstrip()}\n\n{body}"


def _plain(words: str) -> str:
    return words.replace("\r\n", "\n").strip()


def _join(client: Client, own: Pending, review: Review, joining: _Joining, out: Out) -> None:
    """Add `review`'s replies, comments, and body to the poster's own pending review `own`, which stays pending.

    A reply or a comment `own` holds already, word for word on the same thread or line, is not added again: it is
    named as though it were. Nothing of `own` is removed, and `own` is never deleted.

    Raises:
        GitHubError: GitHub refused one, or may have; what `own` holds of the request is printed first, and `end`.
    """
    out.line({"kind": "pending", "review": own.node, "id": own.id, "joined": True})
    held = list(own.comments)
    posted: list[Mapping[str, object]] = []
    try:
        for answered, thread, words in joining.replies:
            same = _take(held, lambda c, t=thread, w=words: _reply_to(c, joining.thread_of) == t and _same(c, w))
            added = _named(same) if same is not None else _add_reply(client, own.node, thread, words)
            posted.append({"comment": answered, **added})
        for index, new in enumerate(review.comments, 1):
            same = _take(held, lambda c, n=new: _starts(c, n))
            added = _named(same) if same is not None else _thread(client, own.node, index, new)
            posted.append({"index": index, **added})
        body = _joined_body(own.body, review.body)
        if body is not None:
            client.query(_UPDATE, {"review": own.node, "body": body})
    except GitHubError:
        # The review is the operator's: what was added stays, and a later stage adds only what is missing.
        for line in posted:
            out.line({"kind": "comment", **line})
        out.line({"kind": "end", "submitted": False, "joined": True})
        raise
    for line in posted:
        out.line({"kind": "comment", **line})
    out.line({"kind": "end", "submitted": False, "staged": True, "joined": True})


def _take(
    held: list[Mapping[str, object]],
    matches: Callable[[Mapping[str, object]], bool],
) -> Mapping[str, object] | None:
    """Take the first of `held` that `matches` out of it, so two requests alike need two comments.

    Returns:
        It, or None.
    """
    for i, comment in enumerate(held):
        if matches(comment):
            return held.pop(i)
    return None


def _reply_to(comment: Mapping[str, object], thread_of: Mapping[int, str]) -> str | None:
    """The thread a pending review's `comment` answers, by its node id; None for one that starts a thread.

    Returns:
        The thread's node id, or None.
    """
    answered = comment.get("replyTo")
    found = number(answered.get("fullDatabaseId")) if isinstance(answered, dict) else None
    return None if found is None else thread_of.get(found)


def _same(comment: Mapping[str, object], words: str) -> bool:
    return _plain(text(comment.get("body")) or "") == _plain(words)


def _starts(comment: Mapping[str, object], new: NewComment) -> bool:
    """Whether a pending review's `comment` is `new`: a thread's start on its file and line, in its words.

    Returns:
        True when it is.
    """
    on = new.line in {number(comment.get("line")), number(comment.get("originalLine"))}
    return comment.get("replyTo") is None and comment.get("path") == new.path and on and _same(comment, new.text)


def _named(comment: Mapping[str, object]) -> dict[str, object]:
    return {"id": number(comment.get("fullDatabaseId")), "url": comment.get("url")}


def _author(node: Mapping[str, object]) -> str | None:
    author = node.get("author")
    return text(author.get("login")) if isinstance(author, dict) else None


def _submit(  # noqa: PLR0917  (what one review is posted from)
    client: Client,
    pr: Ref,
    pr_id: str,
    review: Review,
    joining: _Joining,
    login: str,
    out: Out,
) -> None:
    """Post `review`'s body and `joining`'s replies as one review.

    The review is opened on `review.commit`, if it names one, and its comments added after the replies. It is
    submitted as a comment, or, for `review.submit` false, left pending with the body as its own. A stage that GitHub
    refuses to open one for, since a pending review of the poster's turned up after it looked, joins that one.

    Raises:
        UnknownOutcomeError: The submit may have reached GitHub.
        GitHubError: GitHub refused before anything of it could be seen; the pending review is deleted, or named.
    """
    # A staged review keeps its body from the start, since the operator submits it on GitHub, not canopy.
    body = None if review.submit else review.body
    opening = {"pr": pr_id, "body": body, "commit": review.commit}
    try:
        added = obj(client.query(_ADD_REVIEW, opening).get("addPullRequestReview"), "addPullRequestReview")
        opened = obj(added.get("pullRequestReview"), "pullRequestReview")
        pending = _id(opened.get("id"), "pending review's id")
    except GitHubError as e:
        own = _own_pending(client, pr, login) if e.certain and _ONE_PENDING in str(e).lower() else None
        if own is not None:
            _check_joinable(own, review)
            _join(client, own, review, joining, out)
            return
        if not e.certain:
            # GitHub may have opened it, and the next post could open no other while it stands.
            _abandon_unseen(client, pr, login, body, out)
        raise
    out.line({"kind": "pending", "review": pending, "id": number(opened.get("fullDatabaseId"))})
    try:
        posted = _fill(client, pending, joining.replies, review.comments)
    except GitHubError:
        # Nobody else sees a pending review or its replies, so a reply that failed posted nothing.
        _abandon(client, pending, out)
        raise
    if not review.submit:
        for line in posted:
            out.line({"kind": "comment", **line})
        out.line({"kind": "end", "submitted": False, "staged": True})
        return
    try:
        submit = client.query(_SUBMIT, {"review": pending, "body": review.body})
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


def _fill(
    client: Client,
    pending: str,
    replies: Sequence[tuple[int, str, str]],
    comments: Sequence[NewComment],
) -> list[Mapping[str, object]]:
    """Add each reply and each comment to pending review `pending`, in order.

    Returns:
        A line for each, as `comment` prints it.

    Raises:
        GitHubError: GitHub refused one, or may have.
    """
    posted: list[Mapping[str, object]] = [
        {"comment": answered, **_add_reply(client, pending, thread, words)} for answered, thread, words in replies
    ]
    posted.extend({"index": index, **_thread(client, pending, index, new)} for index, new in enumerate(comments, 1))
    return posted


def _add_reply(client: Client, pending: str, thread: str, words: str) -> dict[str, object]:
    """Add `words` to pending review `pending` as a reply on thread `thread`.

    Returns:
        The new comment's id and URL.

    Raises:
        GitHubError: GitHub refused it, or may have.
    """
    variables = {"review": pending, "thread": thread, "body": words}
    data = obj(client.query(_REPLY, variables).get("addPullRequestReviewThreadReply"), "reply")
    comment = obj(data.get("comment"), "comment")
    return {"id": number(comment.get("fullDatabaseId")), "url": comment.get("url")}


def _thread(client: Client, pending: str, index: int, comment: NewComment) -> dict[str, object]:
    """Add `comment` to pending review `pending` as a thread of its own on its line.

    Returns:
        The new comment's id and URL.

    Raises:
        GitHubError: GitHub refused it, as for a line its diff of the PR does not show, naming the comment.
    """
    variables = {"review": pending, "path": comment.path, "line": comment.line, "body": comment.text}
    try:
        data = obj(client.query(_THREAD, variables).get("addPullRequestReviewThread"), "thread")
    except GitHubError as e:
        where = f"comment {index}, on {comment.path}:{comment.line}"
        raise GitHubError(f"GitHub refused {where}: {e}", certain=e.certain, types=e.types) from e
    nodes = items(obj(obj(data.get("thread"), "thread").get("comments"), "comments").get("nodes"))
    first: Mapping[str, object] = nodes[0] if nodes else {}
    return {"id": number(first.get("fullDatabaseId")), "url": first.get("url")}


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
    if on != pr_id or _author(found) != login:
        raise InputError(f"review {review_id} is not a review of this PR by {login}")
    if found.get("state") != "PENDING":
        raise InputError(f"review {review_id} was submitted, so what it held is posted")
    client.query(_DELETE, {"review": review_id})


def _abandon_unseen(client: Client, pr: Ref, login: str, body: str | None, out: Out) -> None:
    """Delete the poster's own pending review on `pr`, which GitHub may have opened, with `body`, without saying so.

    There was none when the post looked, so one found now is the post's, unless the operator opened one meanwhile: only
    one that holds no comment, and no body but `body`, is deleted.
    """
    variables = {"owner": pr.owner, "name": pr.name, "number": pr.number}
    try:
        found = obj(_repository(client, _PENDING, variables).get("pullRequest"), "pullRequest")
    except GitHubError:
        return
    for node in items(obj(found.get("reviews"), "reviews").get("nodes")):
        pending = text(node.get("id"))
        if _author(node) != login or not pending:
            continue
        comments = node.get("comments")
        empty = isinstance(comments, dict) and comments.get("totalCount") == 0
        if empty and (text(node.get("body")) or "") in {"", body or ""}:
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
