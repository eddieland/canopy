"""The Slack sink canopy ships (DESIGN §20), against a local HTTP server."""

import json
import os
import shutil
import threading
from collections.abc import Generator, Iterable, Mapping, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar, Protocol, override
from unittest import mock

import canopy_notify_slack as slack
import pytest
from click.testing import Result

from tests.canopy_notify_slack.helpers import token_file
from tests.conftest import invoke

MESSAGE: dict[str, Any] = {
    "version": 1,
    "sink": "slack",
    "repo": "/home/me/src/api",
    "sent_at": "2026-09-24T19:00:00Z",
    "attention": {
        "added": [
            {
                "ticket": "PROJ-3",
                "title": "Retry <@U1> checkout",
                "repo": None,
                "reason": "needs_reviewer",
                "detail": "<!channel> https://x.test/1",
                "since": "2026-09-24T18:00:00Z",
            },
        ],
        "resolved": [{"ticket": "PROJ-4", "title": None, "repo": "web", "reason": "ready_to_merge"}],
        "open": 4,
        "path": "/home/me/.canopy/attention.md",
    },
    "events": [
        {
            "id": 88,
            "kind": "run.ended",
            "ticket": "PROJ-12",
            "title": "Add retries",
            "run": 41,
            "run_kind": "implement",
            "status": "done",
            "pr": "https://x.test/pr/7",
            "prs": ["https://x.test/pr/7"],
            "summary": "<https://evil|click>",
            "question": None,
            "line": "< PROJ-12 run 41 implement ended done: <https://evil|click>",
        },
    ],
    "omitted": 0,
    "digest": None,
    "text": "canopy attention: 1 new, 1 resolved\n+ PROJ-3 needs_reviewer: x\nFull list: /home/me/attention.md\n",
}


def _sink(
    argv: Sequence[str],
    stdin: str = "",
    *,
    prefix: str = slack.SLACK_PREFIX,
    api_url: str = slack.SLACK_API_URL,
) -> Result:
    """Run the sink with `argv` on `stdin`, letting it post to a webhook under `prefix` or with a token to `api_url`."""
    return invoke(slack.main, argv, stdin=stdin, obj=slack.Slack(prefix, api_url))


# Slack


class _Hook(BaseHTTPRequestHandler):
    received: ClassVar[list[dict[str, Any]]] = []
    status: ClassVar[int] = 200

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        _Hook.received.append(json.loads(self.rfile.read(length)))
        self.send_response(_Hook.status)
        self.end_headers()
        self.wfile.write(b"ok" if _Hook.status == 200 else b"invalid_payload")

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@pytest.fixture
def hook() -> Generator[str]:
    """A local stand-in for Slack's incoming webhook. Yields its URL."""
    _Hook.received = []
    _Hook.status = 200
    server = HTTPServer(("127.0.0.1", 0), _Hook)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/services/T/B/x"
    server.shutdown()
    server.server_close()


def webhook_file(tmp_path: Path, url: str, mode: int = 0o600) -> Path:
    path = tmp_path / "slack-webhook"
    path.write_text(url + "\n")
    path.chmod(mode)
    return path


def test_the_slack_sink_posts_one_escaped_message(hook: str, tmp_path: Path) -> None:
    path = webhook_file(tmp_path, hook)
    assert _sink(["--webhook-file", str(path)], json.dumps(MESSAGE), prefix="http://127.0.0.1:").exit_code == 0
    [posted] = _Hook.received
    assert set(posted) == {"text", "blocks"}
    assert posted["blocks"] == slack.blocks(MESSAGE)
    assert posted["text"].splitlines() == [
        "*canopy* · api: 1 new, 1 resolved, 4 open, 1 event",
        # Each item and event as its block's first line shows it, not canopy's text line.
        ":bell: *PROJ-3* Retry &lt;@U1&gt; checkout · needs reviewer: &lt;!channel&gt; https://x.test/1",
        ":heavy_check_mark: ~PROJ-4 (web)~ ready to merge",
        ":white_check_mark: *PROJ-12* Add retries · implement run 41 ended *done*",
    ]


def test_slack_refusing_a_post_is_exit_1(hook: str, tmp_path: Path) -> None:
    _Hook.status = 400
    path = webhook_file(tmp_path, hook)
    sent = _sink(["--webhook-file", str(path)], json.dumps(MESSAGE), prefix="http://127.0.0.1:")
    assert sent.exit_code == 1
    assert "Slack refused the post: HTTP 400: invalid_payload" in sent.stderr


@pytest.mark.parametrize(
    ("url", "mode", "message"),
    [
        ("https://hooks.slack.com/services/T/B/x", 0o644, "is readable by others; run: chmod 600"),
        ("https://example.test/hook", 0o600, "must hold one URL starting https://hooks.slack.com/"),
        ("https://hooks.slack.com/a https://hooks.slack.com/b", 0o600, "must hold one URL"),
    ],
)
def test_the_webhook_file_is_checked(
    tmp_path: Path,
    url: str,
    mode: int,
    message: str,
) -> None:
    path = webhook_file(tmp_path, url, mode)
    sent = _sink(["--webhook-file", str(path)], json.dumps(MESSAGE))
    assert sent.exit_code == 2
    assert message in sent.stderr


def test_a_webhook_that_only_looks_like_the_prefix_is_refused(
    tmp_path: Path,
) -> None:
    # It starts with the prefix, but its host is evil.test: the part before `@` is a user name.
    path = webhook_file(tmp_path, "http://127.0.0.1:1@evil.test/hook")
    sent = _sink(["--webhook-file", str(path)], json.dumps(MESSAGE), prefix="http://127.0.0.1:")
    assert sent.exit_code == 2
    assert "must hold one URL starting http://127.0.0.1:" in sent.stderr


def test_a_fifo_webhook_file_is_refused_without_opening_it(tmp_path: Path) -> None:
    path = tmp_path / "slack-webhook"
    os.mkfifo(path, 0o600)
    sent = _sink(["--webhook-file", str(path)], json.dumps(MESSAGE))
    assert sent.exit_code == 2
    assert "is not a regular file" in sent.stderr


def test_a_long_slack_message_is_45_lines_with_its_header() -> None:
    events = [{"kind": "test", "text": f"event {n}"} for n in range(60)]
    text = slack.render({"repo": "/r/api", "events": events})
    lines = text.splitlines()
    assert len(lines) == 45
    assert lines[-1] == "_... and 17 more lines_"


def test_the_slack_sink_reads_its_default_file_and_needs_json(
    tmp_path: Path,
) -> None:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        assert slack.default_webhook_file() == tmp_path / "canopy" / "slack-webhook"
        sent = _sink([], json.dumps(MESSAGE))
        assert sent.exit_code == 2
        assert f"cannot read the webhook file {tmp_path / 'canopy' / 'slack-webhook'}" in sent.stderr
        (tmp_path / "canopy").mkdir()
        webhook_file(tmp_path / "canopy", "https://hooks.slack.com/services/T/B/x")
        sent = _sink([], "canopy attention: 1 new\n")
        assert sent.exit_code == 2
        assert 'set format = "json" for this sink' in sent.stderr


def test_a_digest_is_a_short_block() -> None:
    text = slack.render(
        {
            "repo": "/r/api",
            "attention": None,
            "events": [],
            "digest": {"lines": ["Digest since x: 2 ticks", "  nothing ran"]},
        },
    )
    assert text.splitlines() == ["*canopy* · api: digest", "", "*Digest*", "Digest since x: 2 ticks", "nothing ran"]


def _texts(blocks: Iterable[Mapping[str, Any]]) -> list[str]:
    """Each section's text and each context's elements, in order: what a reader sees, as Slack markup."""
    out: list[str] = []
    for block in blocks:
        if block["type"] == "section":
            out.append(block["text"]["text"])
            out += [f["text"] for f in block.get("fields", [])]
        elif block["type"] == "context":
            out += [e["text"] for e in block["elements"]]
    return out


def test_slack_marks_a_finding_the_operator_dismissed() -> None:
    attention: dict[str, Any] = {
        **MESSAGE["attention"],
        "added": [],
        "resolved": [{"ticket": "chore:deps", "title": None, "repo": None, "reason": "lodash", "dismissed": True}],
    }
    message: dict[str, Any] = {**MESSAGE, "attention": attention, "events": []}
    assert ":heavy_check_mark: ~chore:deps~ lodash (dismissed)" in slack.render(message).splitlines()
    assert "*Resolved*\n:heavy_check_mark: ~chore:deps~ lodash (dismissed)" in _texts(slack.blocks(message))


def test_slack_blocks_are_built_from_the_fields() -> None:
    blocks = slack.blocks(MESSAGE)
    # No header: a line in small type names the repository, so a busy channel is not a column of headings.
    # What needs you, the new item, before a divider and the rest.
    assert [b["type"] for b in blocks] == ["context", "section", "context", "divider", "section", "section"]
    assert _texts(blocks) == [
        "*canopy* · api · 1 new · 1 resolved · 4 open · 1 event",
        ":bell: *PROJ-3* Retry &lt;@U1&gt; checkout · needs reviewer\n&lt;!channel&gt; <https://x.test/1>",
        "open since <!date^1790272800^{date_short_pretty} {time}|2026-09-24T18:00:00Z>",
        "*Resolved*\n:heavy_check_mark: ~PROJ-4 (web)~ ready to merge",
        (
            ":white_check_mark: *PROJ-12* Add retries · implement run 41 ended *done*\n<https://x.test/pr/7>\n"
            "&lt;https://evil|click&gt;"
        ),
    ]


def test_slack_blocks_parse_nothing_in_journal_text() -> None:
    # Set `verbatim`, Slack would otherwise turn a bare @here or #channel into a mention or a link.
    detail = "@here #general <!channel> https://ok.test/?a=1&b=2 https://evil.test|ok.test"
    added = [{"ticket": "T-1", "reason": "r", "detail": detail}]
    blocks: list[dict[str, Any]] = slack.blocks({"repo": "/r/api", "attention": {"added": added}})
    mrkdwn = [e for b in blocks for e in ([b["text"]] if b["type"] == "section" else b.get("elements", []))]
    assert all(m["verbatim"] for m in mrkdwn)
    # A URL is a link that shows itself; one holding `|` would show a label instead, so it stays text.
    assert _texts(blocks)[1] == (
        ":bell: *T-1* · r\n@here #general &lt;!channel&gt; <https://ok.test/?a=1&amp;b=2> https://evil.test|ok.test"
    )


@pytest.mark.parametrize(
    ("summary", "linked"),
    [
        ("Opened https://x.test/pull/7: ready", "Opened <https://x.test/pull/7>: ready"),
        ("Opened PR (https://x.test/pull/7).", "Opened PR (<https://x.test/pull/7>)."),
        ("See [the PR](https://x.test/pull/7)", "See [the PR](<https://x.test/pull/7>)"),
        ('"https://x.test/q?a=1&b=2", then', '"<https://x.test/q?a=1&amp;b=2>", then'),
        ("https://x.test/wiki/Foo_(bar).", "<https://x.test/wiki/Foo_(bar)>."),
        ("<https://x.test/7>", "&lt;<https://x.test/7>&gt;"),
        # A URL holding `|` would show a label in its place, and a bare scheme is no URL: both stay text.
        ("(https://evil.test|ok.test)", "(https://evil.test|ok.test)"),
        ("Opened https://.", "Opened https://."),
    ],
)
def test_slack_keeps_the_punctuation_around_a_url_out_of_its_link(summary: str, linked: str) -> None:
    events = [{"kind": "run.ended", "ticket": "P-1", "run": 1, "run_kind": "implement", "status": "done"}]
    events[0]["summary"] = summary
    assert _texts(slack.blocks({"repo": "/r/api", "events": events}))[1].splitlines()[1] == linked


def test_slack_blocks_for_each_event_kind() -> None:
    events: list[dict[str, Any]] = [
        {
            "kind": "run.started",
            "ticket": "P-1",
            "title": "Fix the build",
            "run": 2,
            "run_kind": "fix_ci",
            "branch": "agent/P-1",
            "attempt": 1,
            "limit": 3,
        },
        {
            "kind": "run.ended",
            "ticket": "P-2",
            "run": 3,
            "run_kind": "implement",
            "status": "blocked",
            "prs": [],
            "question": "Which table?",
        },
        {"kind": "chore.ended", "chore": "deps", "run": 4, "status": "failed", "findings": 1, "summary": None},
        {
            "kind": "review.ended",
            "pr": "https://x.test/pr/9",
            "ticket": None,
            "run": 5,
            "status": "done",
            "verdict": "findings",
            "impact": "low",
            "findings": 2,
        },
        {"kind": "loop.failing", "count": 3, "status": "error", "tick": 9, "log": "/w/.canopy/canopy.log"},
        {"kind": "loop.recovered", "failed": 3},
        {"kind": "loop.sink_failing", "sink": "phone", "error": "exit 7"},
        {"kind": "loop.budget_reached", "month": "2026-10", "budget": 300, "percent": 80, "spent": 240.0},
        {
            "kind": "loop.budget_reached",
            "month": "2026-10",
            "budget": 300,
            "percent": 90,
            "spent": 270.0,
            "runs": 270.0,
            "outside": 0.0,
            "sessions_read_at": None,
        },
        {
            "kind": "loop.budget_reached",
            "month": "2026-10",
            "budget": 300,
            "percent": 100,
            "spent": 301.5,
            "projected": 410.25,
            "runs": 201.5,
            "outside": 100.0,
            "sessions_read_at": "2026-10-28T13:05:00.000Z",
        },
        {
            "kind": "loop.budget_reached",
            "month": "2026-11",
            "budget": 300,
            "percent": 80,
            "spent": 240.0,
            "runs": 200.0,
            "outside": 40.0,
            "sessions_read_at": "2026-10-28T13:05:00.000Z",
            "sessions_read": "failed",
        },
        {"kind": "test", "text": "canopy test message"},
        {"kind": "kind.from.a.newer.canopy", "line": "x <y>"},
    ]
    # What needs you first, in the order canopy sent it; a run starting is one line in small type.
    assert _texts(slack.blocks({"repo": "/r/api", "events": events}))[1:] == [
        ":raising_hand: *P-2* · implement run 3 ended *blocked*\n> *Question:* Which table?",
        ":rotating_light: *The loop is failing:* 3 ticks in a row ended other than ok",
        "latest tick 9 ended error · log `/w/.canopy/canopy.log`",
        ":warning: *Sink phone is failing:* 3 deliveries in a row",
        "`exit 7`",
        ":arrow_forward: *P-1* Fix the build · fix_ci run 2 started · attempt 1 of 3 · `agent/P-1`",
        ":x: *chore:deps* · run 4 ended *failed* · 1 finding",
        ":white_check_mark: review run 5 ended *done*: findings low · 2 findings\n<https://x.test/pr/9>",
        ":white_check_mark: *The loop recovered* after 3 failed ticks",
        ":moneybag: *Spend for 2026-10 reached 80% of its budget:* $240.00 of $300",
        ":moneybag: *Spend for 2026-10 reached 90% of its budget:* $270.00 of $300",
        "canopy's runs $270.00 · outside canopy not read yet",
        ":moneybag: *Spend for 2026-10 reached its budget:* $301.50 of $300; on pace for $410.25",
        (
            "canopy's runs $201.50 · outside canopy $100.00 · sessions read"
            " <!date^1793192700^{date_short_pretty} {time}|2026-10-28T13:05:00.000Z>"
        ),
        ":moneybag: *Spend for 2026-11 reached 80% of its budget:* $240.00 of $300",
        (
            "canopy's runs $200.00 · outside canopy $40.00 · the last read of sessions failed"
            " <!date^1793192700^{date_short_pretty} {time}|2026-10-28T13:05:00.000Z>"
        ),
        ":test_tube: canopy test message",
        "x &lt;y&gt;",
    ]


def test_what_needs_you_leads_the_message_and_its_notification() -> None:
    events: list[dict[str, Any]] = [
        _run("P-1", 1),
        {**_run("P-2", 2, "done"), "ui": "http://localhost:9000/runs/2"},
        _run("P-3", 3, "blocked"),
    ]
    resolved = [{"ticket": "P-4", "reason": "ci_red"}]
    message: dict[str, Any] = {"repo": "/r/api", "attention": {"resolved": resolved, "open": 0}, "events": events}
    blocks = slack.blocks(message)
    # The run waiting on you, then a divider, then the rest in the order canopy sent it: the run starting in small
    # type, its page linked after its line.
    assert [b["type"] for b in blocks] == ["context", "section", "divider", "section", "context", "section"]
    assert _texts(blocks)[1:] == [
        ":raising_hand: *P-3* · implement run 3 ended *blocked*",
        "*Resolved*\n:heavy_check_mark: ~P-4~ ci red",
        ":arrow_forward: *P-1* · implement run 1 started · attempt 1 of 3 · `agent/P-1`",
        ":white_check_mark: *P-2* · implement run 2 ended *done* · <http://localhost:9000/runs/2|open>",
    ]
    assert slack.render(message).splitlines()[1:3] == [
        ":raising_hand: *P-3* · implement run 3 ended *blocked*",
        ":heavy_check_mark: ~P-4~ ci red",
    ]


def test_slack_blocks_for_plans_follow_ups_and_tasks() -> None:
    events: list[dict[str, Any]] = [
        {"kind": "plan.proposed", "ticket": "P-1", "title": "Fix the build", "run": 2, "plan": 7},
        {"kind": "plan.approved", "ticket": "P-1", "run": 2, "plan": 8, "feedback": True, "reason": "One <file>"},
        {"kind": "follow_ups.filed", "ticket": "P-2", "run": 3, "follow_ups": {"P-9": "api", "P-10": None}, "count": 3},
        {
            "kind": "task.ended",
            "task": 4,
            "run": 5,
            "status": "blocked",
            "summary": None,
            "question": "Which branch?",
            "branch": "task/4",
            "head": "0123456789abcdef",
            "pr": "https://x.test/pr/3",
            "tickets": ["P-11"],
        },
        {"kind": "chore.ended", "chore": "deps", "run": 6, "status": "ok", "findings": 0, "summary": None},
    ]
    assert _texts(slack.blocks({"repo": "/r/api", "events": events}))[1:] == [
        ":clipboard: *P-1* Fix the build · plan 7 waits on your approval",
        "read it with `canopy show P-1`",
        (
            ":raising_hand: *task 4* · run 5 ended *blocked*\n<https://x.test/pr/3>\n> *Question:* Which branch?\n"
            "filed *P-11*"
        ),
        "`task/4` at `0123456789ab`",
        ":ballot_box_with_check: *P-1* · feedback plan 8 approved by its planner\n> *Why:* One &lt;file&gt;",
        ":seedling: *P-2* · run 3 filed 3 follow-ups\n*P-9* (api), *P-10*, 1 more",
        "label or `canopy start` each one you want worked",
        ":white_check_mark: *chore:deps* · run 6 ended *ok* · no findings",
    ]


def test_slack_blocks_for_a_flaky_check_kicked_or_left_to_the_operator() -> None:
    pr = "https://github.com/acme/api/pull/7"
    flaky: dict[str, Any] = {"kind": "ci.flaky", "ticket": "P-1", "title": "Fix the build", "run": 2, "prs": [pr]}
    events: list[dict[str, Any]] = [
        flaky | {"kicked": ["api"], "estimate": "The runner was lost <before> any test ran.", "note": None},
        flaky | {"run": 3, "kicked": [], "estimate": "Same again.", "note": "api: not kicked: out of kicks"},
        flaky | {"run": 4, "kicked": [], "estimate": "Lost.", "cause": "runner", "note": None},
        flaky | {"run": 5, "kicked": [], "estimate": "Hm.", "cause": "<guess>", "note": None},
    ]
    assert _texts(slack.blocks({"repo": "/r/api", "events": events}))[1:] == [
        (
            ":repeat: *P-1* Fix the build · run 2 left a failed check as flaky; canopy pushed `api` again to rerun it\n"
            f"<{pr}|acme/api#7>\n> *Why:* The runner was lost &lt;before&gt; any test ran."
        ),
        (
            ":grey_question: *P-1* Fix the build · run 3 left a failed check as flaky\n"
            f"<{pr}|acme/api#7>\n> *Why:* Same again."
        ),
        "rerun it, or `canopy reply` that it is real · api: not kicked: out of kicks",
        (
            ":grey_question: *P-1* Fix the build · run 4 left a failed check as flaky, likely the CI runner\n"
            f"<{pr}|acme/api#7>\n> *Why:* Lost."
        ),
        "rerun it, or `canopy reply` that it is real",
        f":grey_question: *P-1* Fix the build · run 5 left a failed check as flaky\n<{pr}|acme/api#7>\n> *Why:* Hm.",
        "rerun it, or `canopy reply` that it is real",
    ]


def test_slack_blocks_for_a_forced_push_lead_the_message() -> None:
    pr = "https://github.com/acme/api/pull/7"
    kicked: dict[str, Any] = {
        "kind": "ci.kicked",
        "ticket": "P-1",
        "title": "Fix the build",
        "run": 2,
        "repo": "api",
        "branch": "agent/P-1",
        "pr": pr,
        "from_head": "0123456789abcdef",
        "to_head": "fedcba9876543210",
        "kick": 1,
        "limit": 2,
    }
    blocks = slack.blocks({"repo": "/r/api", "events": [_run("P-2", 3), kicked]})
    assert _texts(blocks)[1:] == [
        (
            ":warning: *P-1* Fix the build · run 2: canopy force-pushed `agent/P-1` in `api` to rerun a check left as "
            f"flaky\n<{pr}|acme/api#7>"
        ),
        "`0123456789ab` → `fedcba987654` · kick 1 of 2",
        ":arrow_forward: *P-2* · implement run 3 started · attempt 1 of 3 · `agent/P-2`",
    ]


def test_a_slack_digest_is_fields() -> None:
    digest: dict[str, Any] = {
        "since": "2026-09-24T15:00:00Z",
        "ticks": {"ok": 23, "error": 1},
        "runs_started": {"implement": 2},
        "runs_ended": {},
        "done": [{"ticket": "P-1", "title": "Fix the build", "run": 1, "pr": "https://x.test/pr/1"}],
        "blocked": [{"ticket": "P-2", "run": 2}],
        "attention": {"open": 3, "by_reason": {"needs_reviewer": 3}, "oldest": "3h"},
        "running": 2,
        "spend": {"total": 1.5, "overseer": 0.25, "idle": 0.25, "dry_run": 0.5, "workers": 0.75, "plans": None},
        "lines": ["not used"],
    }
    assert _texts(slack.blocks({"repo": "/r/api", "digest": digest}))[1:] == [
        ":bar_chart: *Digest* since <!date^1790262000^{date_short_pretty} {time}|2026-09-24T15:00:00Z>",
        "*Ticks*\n24 (23 ok, 1 error)",
        "*Workers running*\n2",
        "*Runs started*\n2 implement",
        "*Runs ended*\nnone",
        "*Needs you*\n3 open, oldest 3h\n3 needs reviewer",
        "*Spent*\n*$1.50*\noverseer $0.25 (idle $0.25), workers $0.75, dry runs $0.50",
        ":white_check_mark: *P-1* Fix the build · <https://x.test/pr/1>\n:raising_hand: *P-2* · blocked",
    ]


@pytest.mark.parametrize(
    ("digest", "spent"),
    [
        ({"spend": {"total": None, "workers": None}}, ["*Spent*\nnone reported"]),
        ({"spend": {"total": 0.5, "tasks": 0.5}}, ["*Spent*\n*$0.50*\ntasks $0.50"]),
        ({}, []),  # a canopy from before digests carried spend
    ],
)
def test_a_slack_digest_says_what_was_spent_when_canopy_sends_it(digest: dict[str, Any], spent: list[str]) -> None:
    texts = _texts(slack.blocks({"repo": "/r/api", "digest": digest}))
    assert [t for t in texts if t.startswith("*Spent*")] == spent


def test_slack_blocks_stay_within_slacks_limit() -> None:
    events = [{"kind": "test", "text": f"event {n}"} for n in range(60)]
    blocks = slack.blocks({"repo": "/r/api", "events": events, "omitted": 3})
    assert len(blocks) == 50
    # The line naming the repository, 48 events; 12 events and the 3 canopy left out are counted.
    assert _texts(blocks)[-1] == "_… and 15 more: see `canopy status`_"


@pytest.mark.parametrize(
    ("pr", "shown"),
    [
        ("https://github.com/acme/api/pull/7", "<https://github.com/acme/api/pull/7|acme/api#7>"),
        (
            "https://github.com/acme/my.repo_2/pull/12/",
            "<https://github.com/acme/my.repo_2/pull/12/|acme/my.repo_2#12>",
        ),
        # Anything else shows its URL, so a label never says more than the address it opens.
        ("https://github.com.evil.test/acme/api/pull/7", "<https://github.com.evil.test/acme/api/pull/7>"),
        ("https://github.com/acme/api/pull/7/files", "<https://github.com/acme/api/pull/7/files>"),
        ("https://github.com/acme/api/pull/7?a=1&b=2", "<https://github.com/acme/api/pull/7?a=1&amp;b=2>"),
        ("http://github.com/acme/api/pull/7", "<http://github.com/acme/api/pull/7>"),
        ("https://gitlab.test/acme/api/-/merge_requests/7", "<https://gitlab.test/acme/api/-/merge_requests/7>"),
    ],
)
def test_a_github_pr_is_shown_by_the_name_its_url_spells(pr: str, shown: str) -> None:
    events = [{"kind": "run.ended", "ticket": "P-1", "run": 1, "run_kind": "implement", "status": "done", "prs": [pr]}]
    events.append({"kind": "review.ended", "pr": pr, "run": 2, "status": "done"})
    texts = _texts(slack.blocks({"repo": "/r/api", "events": events}))
    assert [t.splitlines()[1] for t in texts[1:]] == [shown, shown]


def test_a_message_too_long_for_its_asides_keeps_every_item() -> None:
    added = [{"ticket": f"P-{n}", "reason": "r", "since": "2026-09-24T18:00:00Z"} for n in range(30)]
    blocks = slack.blocks({"repo": "/r/api", "attention": {"added": added, "open": 30}})
    # Each item's aside, under it in 60 blocks, folds into its section's last line instead.
    assert [b["type"] for b in blocks] == ["context"] + ["section"] * 30
    assert _texts(blocks)[1] == (
        ":bell: *P-0* · r\nopen since <!date^1790272800^{date_short_pretty} {time}|2026-09-24T18:00:00Z>"
    )
    assert len(slack.blocks({"repo": "/r/api", "attention": {"added": added[:20], "open": 20}})) == 41


def test_the_text_of_a_message_with_one_item_leads_with_it() -> None:
    event = {"kind": "run.ended", "ticket": "P-1", "run": 1, "run_kind": "implement", "status": "failed"}
    # What a notification shows first is what happened, not a count.
    assert slack.render({"repo": "/r/api", "events": [event]}).splitlines() == [
        ":x: *P-1* · implement run 1 ended *failed*",
        "*canopy* · api",
    ]


def test_help_ends_before_stdin_is_read() -> None:
    sent = _sink(["--help"])
    assert sent.exit_code == 0
    assert "Usage: canopy-notify-slack [OPTIONS]" in sent.stdout


# Slack with a bot token


class _Api(BaseHTTPRequestHandler):
    received: ClassVar[list[tuple[str | None, dict[str, Any]]]] = []
    reply: ClassVar[dict[str, Any]] = {"ok": True}
    # The posts, counted from 1, refused as `not_in_channel`.
    refuse: ClassVar[set[int]] = set()
    #: What the next posts get instead of an answer, in turn: `cut`, made but its reply cut off; `limit`, a 429 that
    #: names no wait; or `redirect`, a 302 to a port nothing listens on.
    hiccups: ClassVar[list[str]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        _Api.received.append((self.headers["Authorization"], json.loads(self.rfile.read(length))))
        hiccup = _Api.hiccups.pop(0) if _Api.hiccups else None
        if hiccup in {"limit", "redirect"}:
            self.send_response(429 if hiccup == "limit" else 302)
            self.send_header("Location", "http://127.0.0.1:1/api/chat.postMessage")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        n = len(_Api.received)
        # Each post's `ts` says which it was, as the Web API names a message by its time.
        reply = {"ok": False, "error": "not_in_channel"} if n in _Api.refuse else {**_Api.reply, "ts": f"1790.{n:06d}"}
        body = json.dumps(reply).encode()
        # Like the Web API: 200 even when the post is refused.
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body[: len(body) // 2] if hiccup == "cut" else body)
        self.close_connection = True

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@pytest.fixture
def api() -> Generator[str]:
    """A local stand-in for Slack's `chat.postMessage`. Yields its URL."""
    _Api.received = []
    _Api.reply = {"ok": True}
    _Api.refuse = set()
    _Api.hiccups = []
    server = HTTPServer(("127.0.0.1", 0), _Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api/chat.postMessage"
    server.shutdown()
    server.server_close()


def test_the_slack_sink_posts_with_a_bot_token(api: str, tmp_path: Path) -> None:
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    assert _sink(argv, json.dumps(MESSAGE), api_url=api).exit_code == 0
    [(authorization, posted)] = _Api.received
    assert authorization == "Bearer xoxb-1-2-secret"
    assert set(posted) == {"channel", "text", "blocks"}
    assert posted["channel"] == "C0123ABCD"
    assert posted["text"].splitlines()[1] == (
        ":bell: *PROJ-3* Retry &lt;@U1&gt; checkout · needs reviewer: &lt;!channel&gt; https://x.test/1"
    )


def test_the_slack_sink_posts_with_a_name_and_an_icon(api: str, tmp_path: Path) -> None:
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    argv += ["--username", "canopy (api)", "--icon-emoji", ":wave::skin-tone-3:"]
    assert _sink(argv, json.dumps(MESSAGE), api_url=api).exit_code == 0
    [(_, posted)] = _Api.received
    assert set(posted) == {"channel", "text", "blocks", "username", "icon_emoji"}
    assert (posted["username"], posted["icon_emoji"]) == ("canopy (api)", ":wave::skin-tone-3:")


def test_the_token_file_defaults_to_the_config_directory(api: str, tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        (tmp_path / "canopy").mkdir()
        token_file(tmp_path / "canopy")
        assert _sink(["--channel", "#canopy"], json.dumps(MESSAGE), api_url=api).exit_code == 0
        assert _Api.received[0][1]["channel"] == "#canopy"


def test_a_long_successful_reply_is_exit_0(api: str, tmp_path: Path) -> None:
    # A real reply echoes the message, with its `bot_profile`, and runs past the 500 characters a failure prints.
    _Api.reply = {"ok": True, "channel": "C0123ABCD", "message": {"bot_profile": {"name": "canopy" * 100}}}
    assert len(json.dumps(_Api.reply)) > 500
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    sent = _sink(argv, json.dumps(MESSAGE), api_url=api)
    assert sent.exit_code == 0
    assert sent.stderr == ""


def test_a_long_refusal_prints_only_its_start(api: str, tmp_path: Path) -> None:
    _Api.reply = {"ok": False, "error": "not_in_channel", "detail": "x" * 1000}
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    sent = _sink(argv, json.dumps(MESSAGE), api_url=api)
    assert sent.exit_code == 1
    err = sent.stderr
    assert "not_in_channel" in err
    assert "x" * 1000 not in err


def test_a_post_whose_reply_is_cut_off_is_not_sent_again(api: str, tmp_path: Path) -> None:
    _Api.hiccups = ["cut"]
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    sent = _sink(argv, json.dumps(MESSAGE), api_url=api)
    assert sent.exit_code == 1
    assert "Slack refused the post: the connection to http://127.0.0.1:" in sent.stderr
    assert len(_Api.received) == 1, "a post Slack may have made is not made again"


def test_a_post_slacks_rate_limit_refused_is_sent_again(api: str, tmp_path: Path) -> None:
    _Api.hiccups = ["limit"]
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    with mock.patch.object(slack, "RETRY_PAUSES", (0.0, 0.0)):
        sent = _sink(argv, json.dumps(MESSAGE), api_url=api)
    assert sent.exit_code == 0, sent.stderr
    assert len(_Api.received) == 2


def test_a_redirect_is_refused_and_the_token_does_not_follow_it(api: str, tmp_path: Path) -> None:
    _Api.hiccups = ["redirect"]
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    sent = _sink(argv, json.dumps(MESSAGE), api_url=api)
    assert sent.exit_code == 1
    assert "Slack refused the post: HTTP 302" in sent.stderr
    assert len(_Api.received) == 1


def test_a_web_api_error_is_exit_1(api: str, tmp_path: Path) -> None:
    _Api.reply = {"ok": False, "error": "not_in_channel"}
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    sent = _sink(argv, json.dumps(MESSAGE), api_url=api)
    assert sent.exit_code == 1
    assert "Slack refused the post" in (err := sent.stderr)
    assert "not_in_channel" in err


@pytest.mark.parametrize(
    ("token", "mode", "channel", "message"),
    [
        ("xoxb-1-2-secret", 0o640, "C0123ABCD", "is readable by others; run: chmod 600"),
        ("https://hooks.slack.com/services/T/B/x", 0o600, "C0123ABCD", "must hold one Slack bot token starting xoxb-"),
        ("xoxp-1-2-secret", 0o600, "C0123ABCD", "must hold one Slack bot token"),
        ("xoxb-1 xoxb-2", 0o600, "C0123ABCD", "must hold one Slack bot token"),
        ("xoxb-1-2-sécret", 0o600, "C0123ABCD", "must hold one Slack bot token"),
        ("xoxb-1-2-secret", 0o600, "C01 <!channel>", "is not a Slack channel id or name"),
    ],
)
def test_the_token_file_and_channel_are_checked(
    tmp_path: Path,
    token: str,
    mode: int,
    channel: str,
    message: str,
) -> None:
    argv = ["--channel", channel, "--token-file", str(token_file(tmp_path, token, mode))]
    sent = _sink(argv, json.dumps(MESSAGE), api_url="http://127.0.0.1:1/")
    assert sent.exit_code == 2
    err = sent.stderr
    assert message in err
    assert "secret" not in err.replace(str(tmp_path), "")


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--username", "  "], "must be printable, not blank"),
        (["--username", "a\nb"], "must be printable, not blank"),
        (["--username", "x" * 81], "at most 80 characters"),
        (["--icon-emoji", "robot_face"], "is not an emoji code"),
        (["--icon-emoji", "https://x.test/i.png"], "is not an emoji code"),
    ],
)
def test_the_name_and_icon_are_checked(
    tmp_path: Path,
    flags: list[str],
    message: str,
) -> None:
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path)), *flags]
    sent = _sink(argv, json.dumps(MESSAGE), api_url="http://127.0.0.1:1/")
    assert sent.exit_code == 2
    assert message in sent.stderr


@pytest.mark.parametrize(
    "argv",
    [
        ["--token-file", "/x"],
        ["--channel", "C0123ABCD", "--webhook-file", "/x"],
        ["--username", "canopy"],
        ["--icon-emoji", ":robot_face:"],
        ["--threads"],
        ["--channel", "C0123ABCD", "--broadcast", "plan"],
    ],
)
def test_a_token_and_a_webhook_are_not_mixed(argv: list[str]) -> None:
    sent = _sink(argv)
    assert sent.exit_code == 2
    assert "Usage: canopy-notify-slack [OPTIONS]" in sent.stderr


# Slack with a bot token, in threads


def _delivery(sent_at: str, events: list[dict[str, Any]], added: list[dict[str, Any]] | None = None) -> str:
    attention: dict[str, Any] = {"added": added or [], "resolved": [], "open": len(added or []), "path": "/a.md"}
    return json.dumps({"repo": "/r/api", "sent_at": sent_at, "attention": attention, "events": events, "omitted": 0})


def _run(ticket: str, run: int, status: str | None = None) -> dict[str, Any]:
    if status is None:
        started = {"attempt": 1, "limit": 3, "branch": f"agent/{ticket}"}
        return {"id": run, "kind": "run.started", "ticket": ticket, "run": run, "run_kind": "implement", **started}
    return {"id": run, "kind": "run.ended", "ticket": ticket, "run": run, "run_kind": "implement", "status": status}


class _Threaded(Protocol):
    """Run the sink with `--threads` and any more `flags` on `delivery`, returning its exit code."""

    def __call__(self, delivery: str, *flags: str) -> Result: ...


@pytest.fixture
def threaded(api: str, tmp_path: Path) -> Generator[_Threaded]:
    """Run the sink with `--threads`, its state under `tmp_path`. Yields the call."""
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path)), "--threads"]

    def deliver(delivery: str, *flags: str) -> Result:
        return _sink([*argv, *flags], delivery, api_url=api)

    with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp_path / "state")}):
        yield deliver


def _posts() -> list[tuple[str | None, bool, list[str]]]:
    """Each post's thread, whether it is also shown in the channel, and its text, a header's after `# `, in order."""
    return [
        (
            p.get("thread_ts"),
            p.get("reply_broadcast", False),
            [f"# {b['text']['text']}" for b in p["blocks"] if b["type"] == "header"] + _texts(p["blocks"]),
        )
        for _, p in _Api.received
    ]


def _starts(subject: str, *more: str) -> list[str]:
    """What a post starting a thread on 2026-09-24 shows: what it is about, then the repository and the day."""
    return [f"# {subject}", "*canopy* · api · updates from Thu, Sep 24 in the thread", *more]


def test_threads_hold_tickets_and_reviews_for_a_day_chores_stay_out(threaded: _Threaded, tmp_path: Path) -> None:
    first = [
        _run("PROJ-1", 1),
        {"id": 2, "kind": "chore.ended", "chore": "deps", "run": 2, "status": "done", "findings": 0},
        {"id": 3, "kind": "loop.recovered", "failed": 3},
        {"id": 4, "kind": "review.ended", "pr": "https://x.test/pr/9", "ticket": "PROJ-1", "run": 4, "status": "done"},
    ]
    assert threaded(_delivery("2026-09-24T12:30:00Z", first)).exit_code == 0
    # The channel's own post first, with its header, the chore's run among it. Then each thread, in the order named:
    # a post of the same shape starts it, naming what it is about, and its first item is a reply under it.
    assert _posts() == [
        (
            None,
            False,
            [
                "*canopy* · api · 2 events",
                ":white_check_mark: *chore:deps* · run 2 ended *done* · no findings",
                ":white_check_mark: *The loop recovered* after 3 failed ticks",
            ],
        ),
        (None, False, _starts("PROJ-1")),
        (
            "1790.000002",
            False,
            [":arrow_forward: *PROJ-1* · implement run 1 started · attempt 1 of 3 · `agent/PROJ-1`"],
        ),
        (None, False, _starts("review of PROJ-1", "<https://x.test/pr/9>")),
        ("1790.000004", False, [":white_check_mark: *PROJ-1* · review run 4 ended *done*\n<https://x.test/pr/9>"]),
    ]

    _Api.received.clear()
    later = [
        _run("PROJ-1", 5, "blocked"),
        {"id": 6, "kind": "chore.ended", "chore": "deps", "run": 6, "status": "failed", "findings": 1},
        _run("PROJ-2", 7),
    ]
    added = [{"ticket": "chore:deps", "reason": "lodash", "detail": "CVE"}]
    assert threaded(_delivery("2026-09-24T12:31:00Z", later, added)).exit_code == 0
    # The same day: replies in each thread, none shown in the channel unasked, and PROJ-2's thread started. The
    # chore's finding and run go in the channel's post, which comes first.
    assert [(ts, shown) for ts, shown, _ in _posts()] == [
        (None, False),
        ("1790.000002", False),
        (None, False),
        ("1790.000003", False),
    ]
    assert ":bell: *chore:deps* · lodash\nCVE" in _posts()[0][2]
    assert ":x: *chore:deps* · run 6 ended *failed* · 1 finding" in _posts()[0][2]

    _Api.received.clear()
    assert threaded(_delivery("2026-09-26T12:30:00Z", [_run("PROJ-1", 8, "done")])).exit_code == 0
    # A new day starts a new thread, and keeps the old day's among the earlier, for a week.
    assert [(ts, shown) for ts, shown, _ in _posts()] == [(None, False), ("1790.000001", False)]
    state = json.loads((tmp_path / "state" / "canopy" / "slack-threads.json").read_text())
    assert state == {
        "version": 2,
        "scopes": {
            '["C0123ABCD", "/r/api"]': {
                "threads": {"PROJ-1": {"day": "2026-09-26", "ts": "1790.000001"}},
                "posted": [],
                "earlier": {
                    "PROJ-1": [{"day": "2026-09-24", "ts": "1790.000002"}],
                    "PROJ-2": [{"day": "2026-09-24", "ts": "1790.000003"}],
                    "review:https://x.test/pr/9": [{"day": "2026-09-24", "ts": "1790.000004"}],
                },
            },
        },
    }


@pytest.mark.parametrize(
    ("flags", "shown"),
    [
        ([], [False, False, False]),
        (["--broadcast", "blocked"], [True, False, False]),
        (["--broadcast", "attention", "--broadcast", "plan"], [False, True, True]),
    ],
)
def test_a_reply_is_shown_in_the_channel_only_for_what_broadcast_names(
    threaded: _Threaded,
    flags: list[str],
    shown: list[bool],
) -> None:
    started = [_run("PROJ-1", 1), _run("PROJ-2", 2), _run("PROJ-3", 3)]
    assert threaded(_delivery("2026-09-24T12:30:00Z", started), *flags).exit_code == 0
    _Api.received.clear()
    later = [
        _run("PROJ-1", 4, "blocked"),
        {"id": 5, "kind": "plan.proposed", "ticket": "PROJ-2", "run": 2, "plan": 1},
    ]
    added = [{"ticket": "PROJ-3", "reason": "ci_red", "detail": "lint"}]
    assert threaded(_delivery("2026-09-24T12:31:00Z", later, added), *flags).exit_code == 0
    assert {ts: on for ts, on, _ in _posts()} == dict(
        zip(["1790.000001", "1790.000003", "1790.000005"], shown, strict=True),
    )


def test_a_threads_first_item_is_a_reply_like_the_rest(threaded: _Threaded) -> None:
    blocked = {**_run("PROJ-1", 1, "blocked"), "title": "Retry <!channel>\ncheckout"}
    assert threaded(_delivery("2026-09-24T12:30:00Z", [blocked]), "--broadcast", "blocked").exit_code == 0
    # The starter names the ticket by its title, on one line; the run is a reply, shown in the channel as asked.
    assert _posts() == [
        (None, False, _starts("PROJ-1 · Retry <!channel> checkout")),
        (
            "1790.000001",
            True,
            [":raising_hand: *PROJ-1* Retry &lt;!channel&gt; checkout · implement run 1 ended *blocked*"],
        ),
    ]
    starter = _Api.received[0][1]
    assert starter["blocks"][0]["text"]["type"] == "plain_text"
    assert starter["text"] == "PROJ-1 · Retry &lt;!channel&gt; checkout"


def test_a_threaded_delivery_refused_partway_posts_the_rest_on_retry(threaded: _Threaded) -> None:
    delivery = _delivery("2026-09-24T12:30:00Z", [_run("PROJ-1", 1), _run("PROJ-2", 2), _run("PROJ-3", 3)])
    # PROJ-2's thread is started, and its first reply refused.
    _Api.refuse = {4}
    assert threaded(delivery).exit_code == 1
    _Api.refuse = set()
    assert threaded(delivery).exit_code == 0
    # PROJ-1 was posted once; PROJ-2's reply, refused, went in the thread already started, and PROJ-3, never tried,
    # was posted on the retry.
    assert [(ts, texts[0].split("*")[1] if ts else texts[0]) for ts, _, texts in _posts()] == [
        (None, "# PROJ-1"),
        ("1790.000001", "PROJ-1"),
        (None, "# PROJ-2"),
        ("1790.000003", "PROJ-2"),
        ("1790.000003", "PROJ-2"),
        (None, "# PROJ-3"),
        ("1790.000006", "PROJ-3"),
    ]
    assert threaded(delivery).exit_code == 0
    # Once a delivery posts whole, the same items are new again: canopy sends an item once, in the threads started.
    assert [ts for ts, _, _ in _posts()[7:]] == ["1790.000001", "1790.000003", "1790.000006"]


def test_a_threads_file_that_is_not_the_sinks_starts_over(threaded: _Threaded, tmp_path: Path) -> None:
    path = tmp_path / "state" / "canopy" / "slack-threads.json"
    path.parent.mkdir(parents=True)
    scope = '["C0123ABCD", "/r/api"]'
    path.write_text(json.dumps({"scopes": {scope: {"threads": {"PROJ-1": {"day": "2026-09-24", "ts": "<!channel>"}}}}}))
    assert threaded(_delivery("2026-09-24T12:30:00Z", [_run("PROJ-1", 1)])).exit_code == 0
    assert [ts for ts, _, _ in _posts()] == [None, "1790.000001"]
    assert json.loads(path.read_text())["scopes"][scope]["threads"] == {
        "PROJ-1": {"day": "2026-09-24", "ts": "1790.000001"},
    }
    path.write_text("not json")
    assert threaded(_delivery("2026-09-24T12:31:00Z", [_run("PROJ-1", 2)])).exit_code == 0
    assert [ts for ts, _, _ in _posts()] == [None, "1790.000001", None, "1790.000003"]


def test_a_threads_file_that_cannot_be_used_refuses_before_posting(
    threaded: _Threaded,
    tmp_path: Path,
) -> None:
    path = tmp_path / "state" / "canopy" / "slack-threads.json"
    path.parent.mkdir(parents=True)
    os.mkfifo(path, 0o600)
    sent = threaded(_delivery("2026-09-24T12:30:00Z", [_run("PROJ-1", 1)]))
    assert sent.exit_code == 2
    assert "is not a regular file" in sent.stderr
    shutil.rmtree(tmp_path / "state")
    # Its directory cannot be made: a file stands where it would be.
    (tmp_path / "state").write_text("")
    sent = threaded(_delivery("2026-09-24T12:30:00Z", [_run("PROJ-1", 1)]))
    assert sent.exit_code == 2
    assert "the threads file" in sent.stderr
    assert _Api.received == []


def test_a_save_keeps_the_scopes_of_other_channels_and_repositories(tmp_path: Path) -> None:
    path = tmp_path / "slack-threads.json"
    mine = slack.Threads.load(path, "C1", "/r/api")
    # Another sink, on another channel, saves after this one loaded and before it saves.
    theirs = slack.Threads.load(path, "C2", "/r/api")
    theirs.threads["PROJ-9"] = ("2026-09-24", "1790.000009")
    theirs.posted.add("f" * 64)
    theirs.save()
    mine.threads["PROJ-1"] = ("2026-09-24", "1790.000001")
    mine.save()
    assert slack.Threads.load(path, "C2", "/r/api") == theirs
    assert slack.Threads.load(path, "C1", "/r/api").threads == {"PROJ-1": ("2026-09-24", "1790.000001")}
    # The other scope's fingerprints are not this one's to skip.
    assert slack.Threads.load(path, "C1", "/r/api").posted == set()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["slack-threads.json", "slack-threads.json.lock"]


def test_finishing_keeps_earlier_days_threads_for_a_week(tmp_path: Path) -> None:
    threads = slack.Threads.load(tmp_path / "slack-threads.json", "C1", "/r/api")
    threads.threads = {"OLD": ("2026-09-23", "1.1"), "NOW": ("2026-09-24", "1.2"), "LATER": ("2026-09-25", "1.3")}
    threads.earlier = {"NOW": [("2026-09-17", "1.0"), ("2026-09-18", "1.01")]}
    threads.posted = {"f" * 64}
    threads.finish("2026-09-24")
    assert threads.threads == {"NOW": ("2026-09-24", "1.2"), "LATER": ("2026-09-25", "1.3")}
    # A thread started before the day is an earlier one now, and an earlier one past the week is forgotten.
    assert threads.earlier == {"OLD": [("2026-09-23", "1.1")], "NOW": [("2026-09-18", "1.01")]}
    assert threads.posted == set()
    assert slack.Threads.load(tmp_path / "slack-threads.json", "C1", "/r/api") == threads


def test_a_new_days_thread_keeps_the_one_it_replaces(tmp_path: Path) -> None:
    threads = slack.Threads.load(tmp_path / "slack-threads.json", "C1", "/r/api")
    threads.start("PROJ-1", "2026-09-24", "1.1")
    threads.start("PROJ-1", "2026-09-25", "1.2")
    assert threads.threads == {"PROJ-1": ("2026-09-25", "1.2")}
    assert threads.earlier == {"PROJ-1": [("2026-09-24", "1.1")]}
    assert threads.recent("2026-09-25", 1) == {"PROJ-1": [("2026-09-25", "1.2")]}
    assert threads.recent("2026-09-25", 2) == {"PROJ-1": [("2026-09-24", "1.1"), ("2026-09-25", "1.2")]}


def test_a_version_1_threads_file_reads_with_no_earlier_threads(tmp_path: Path) -> None:
    path = tmp_path / "slack-threads.json"
    scope = '["C1", "/r/api"]'
    thread = {"PROJ-1": {"day": "2026-09-24", "ts": "1.1"}, "BAD": {"day": "Tuesday", "ts": "1.2"}}
    path.write_text(json.dumps({"version": 1, "scopes": {scope: {"threads": thread, "posted": []}}}))
    threads = slack.Threads.load(path, "C1", "/r/api")
    assert (threads.threads, threads.earlier) == ({"PROJ-1": ("2026-09-24", "1.1")}, {})


def test_slack_links_each_item_and_event_to_its_page_in_the_web_ui() -> None:
    ui = "http://localhost:9000/canopy/"
    query, escaped = "pr?url=https%3A%2F%2Fx.test&a=1", "pr?url=https%3A%2F%2Fx.test&amp;a=1"
    added = [{"ticket": "P-1", "reason": "needs_reviewer", "ui": f"{ui}tickets/P-1"}]
    events = [
        {"kind": "test", "text": "canopy test message", "ui": None},
        {"kind": "loop.recovered", "failed": 3, "ui": f"{ui}pull-requests/{query}"},
        {
            "kind": "run.ended",
            "ticket": "P-2",
            "run": 3,
            "run_kind": "implement",
            "status": "done",
            "ui": f"{ui}runs/3",
        },
    ]
    message: dict[str, Any] = {"repo": "/r/api", "ui": ui, "attention": {"added": added, "open": 1}, "events": events}
    assert _texts(slack.blocks(message))[:5] == [
        f"*canopy* · api · 1 new · 0 resolved · 1 open · 3 events · <{ui}|open>",
        f":bell: *P-1* · needs reviewer · <{ui}tickets/P-1|open>",
        ":test_tube: canopy test message",
        # `&` is escaped in a link, as in any of Slack's text.
        f":white_check_mark: *The loop recovered* after 3 failed ticks · <{ui}pull-requests/{escaped}|open>",
        f":white_check_mark: *P-2* · implement run 3 ended *done* · <{ui}runs/3|open>",
    ]
    # The fallback text for Slack's notifications links nothing.
    assert "open>" not in slack.render(message)


@pytest.mark.parametrize(
    "page",
    [
        "javascript:alert(1)",
        "http://localhost/x|label",
        "http://localhost/<!channel>",
        "http://localhost/a b",
        "ftp://localhost/",
        "http://localhost/" + "x" * 2000,
        42,
    ],
)
def test_a_page_that_is_not_a_plain_url_is_not_linked(page: object) -> None:
    added = [{"ticket": "P-1", "reason": "r", "ui": page}]
    assert _texts(slack.blocks({"repo": "/r/api", "attention": {"added": added}}))[1] == ":bell: *P-1* · r"


def test_a_reply_from_slack_is_acknowledged_in_its_ticket_thread_and_a_refusal_under_the_message(
    threaded: _Threaded,
) -> None:
    events = [
        {"id": 1, "kind": "reply.recorded", "ticket": "PROJ-7", "message": 4, "ts": "1790.000050", "body": "go on"},
        {
            "id": 2,
            "kind": "reply.refused",
            "ticket": "PROJ-404",
            "ts": "1790.000051",
            "guard": "unknown",
            "reason": "canopy has no record of PROJ-404",
        },
    ]
    assert threaded(_delivery("2026-09-24T12:30:00Z", events)).exit_code == 0
    # PROJ-7 had no thread: one is started for the acknowledgement. The refusal goes under the operator's own message,
    # starting nothing: the key it names may be no ticket at all.
    assert _posts() == [
        (None, False, _starts("PROJ-7")),
        ("1790.000001", False, [":speech_balloon: Your reply from Slack is on *PROJ-7*\n> *Reply:* go on"]),
        (
            "1790.000051",
            False,
            [
                ":no_entry_sign: canopy took nothing from this reply on *PROJ-404*: canopy has no record of PROJ-404",
                "(unknown)",
            ],
        ),
    ]
