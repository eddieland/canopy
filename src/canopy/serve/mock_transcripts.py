"""The mock journal's run transcripts (DESIGN §22), for `python -m canopy.serve --mock`.

Runs 39 and 40, tick 2, chore run 2, reviews 3 and 4, and task run 1 left their sessions' events in their logs, as
`--format json` prints them, for their transcripts, and the running runs 41 and 43 the events their workers printed so
far (§8). Beside each of runs 39's, tick 2's, chore run 2's, and review 4's logs is what canopy gave its runtime.
"""

from __future__ import annotations

import itertools
import json
from datetime import timedelta
from typing import TYPE_CHECKING, NamedTuple

from canopy.infra import logs
from canopy.serve import mock_reviews
from canopy.serve.mock_chores import LODASH

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from pathlib import Path

#: The running runs, whose logs hold their workers' stdout so far.
RUNNING_LOGS = ("41", "43")

_SEARCH_BOX = """\
1\timport { useState } from 'react'
2\t
3\texport function SearchBox({ onSearch }: { onSearch: (q: string) => void }) {
4\t    const [query, setQuery] = useState('')
5\t    return <input value={query} onChange={(e) => { setQuery(e.target.value); onSearch(e.target.value) }} />
6\t}
"""

# Shortened from what canopy renders, keeping its shape.
_PROMPT_39 = """\
# canopy worker: implement

You are working ticket ABC-099 in slot 3. Each repository listed below is checked out with a detached HEAD, at
`agent/ABC-099-search` as it was pushed, or at that repository's base branch if nothing was pushed there yet. This is
attempt 1 of 3.

## Repositories

- web: /home/op/acme/.treehouse/web-3f9c2a1b/3/web, base `main`

## Task

Read the ticket through the tracker MCP. The tracker is jira. Implement the ticket. Follow the repository's AGENTS.md
and conventions. Before each push, run the checks the repository's contributors run before opening a PR, as its
AGENTS.md, contributing guide, Makefile, or CI workflows name them: formatting, lint, and type checks, and the tests it
asks for. Fix what they find, and push when they pass. A check that fails without your change too, or cannot run here,
is not yours to fix: say which and why in your summary.

## Messages from the operator

None.

## Result

End with one line of JSON: {"status": "done" | "failed" | "blocked", "summary": "...", "prs": {"<repo>": "<url>"}}
"""
_PROMPT_TICK_2 = """\
## State

{
  "tick_id": 2,
  "dry_run": false,
  "tickets": [
    {"key": "ABC-101", "phase": "implementing", "run": 41, "attempt": 1},
    {"key": "ABC-104", "phase": "implementing", "run": 43, "attempt": 1}
  ],
  "prs": [{"url": "https://github.com/acme/web/pull/88", "ticket": "ABC-099", "checks": "pending"}],
  "attention": []
}
"""
_PROMPT_CHORE_2 = """\
# canopy chore: deps

Audit each repository's dependencies against the published advisories. Report each advisory that touches a lockfile
as a finding.

## Repositories

- web: /home/op/acme/web
- mobile: /home/op/acme/mobile

## Notes from the operator

None.
"""
_PROMPT_REVIEW_4 = """\
# canopy reviewer

You are reviewing one pull request at one commit. You did not write it and you have no transcript of whoever did.
This is review 2 of at most 2 of this PR.

- PR: https://github.com/acme/web/pull/88
- Commit: `9b2f4c61`. Review this commit, not whatever the PR's head is by the time you read it.
- Checkout: `checkout` is the repository at that commit. Read anything in it you need.
- Ticket: ABC-099.

## Context from the overseer

The first review found a stale response could replace a newer one; check the abort.
"""
# Run 40's setup command, as `_run` writes it before the worker starts (DESIGN §8), and its runtime's stderr.
_SETUP_40 = """\
--- setup web stdout ---
Lockfile is up to date, resolution step is skipped
Packages: +412
Done in 6.2s
--- setup web stderr ---
 WARN  deprecated inflight@1.0.6
"""
_RUN_STDERR_40 = """\
ERROR 2026-10-08T09:41:12 +3m12s service=session error=rate limited: retry after 30s
"""
_TICK_STDERR = """\
INFO  2026-10-08T11:00:00 +210ms service=default version=1.19.0 args=["run","--format","json"] opencode
WARN  2026-10-08T11:00:01 +1043ms service=mcp key=jira error=timed out after 1000ms listing prompts
"""


class _Session(NamedTuple):
    """An agent session whose events a transcript holds."""

    #: The session's id, as the runtime names it.
    id: str
    #: The mock's clock, which each event's minutes count from.
    t0: datetime


def write(state_dir: Path, t0: datetime) -> None:
    """Write the events of runs 39 to 43's, tick 2's, chore run 2's, reviews 3 and 4's, and task run 1's sessions."""
    # The worktree run 39 worked in, as the operator's machine names it: the same on every start, for screenshots.
    web = "/home/op/acme/.treehouse/web-3f9c2a1b/3/web"
    s39, s40, s41, s43 = (_Session(s, t0) for s in ("ses_mock39", "ses_mock40", "ses_mock41", "ses_mock43"))
    s2, c2 = _Session("ses_tick2", t0), _Session("ses_chore2", t0)
    r3, r4 = _Session("ses_review3", t0), _Session("ses_review4", t0)
    run_39 = [
        _start(s39, -90),
        _text(s39, -89.9, "I'll read the ticket, then the search box."),
        _tool(
            s39,
            -89.8,
            "jira_get_issue",
            {
                "status": "completed",
                "input": {"issue_key": "ABC-099"},
                "output": '{"key": "ABC-099", "summary": "Search fires a request per keystroke", "status": "To Do"}',
                "title": "",
            },
        ),
        _tool(
            s39,
            -89.5,
            "read",
            {
                "status": "completed",
                "input": {"filePath": f"{web}/src/search/SearchBox.tsx"},
                "output": _SEARCH_BOX,
                "title": "src/search/SearchBox.tsx",
            },
        ),
        _tool(
            s39,
            -89.4,
            "read",
            {
                "status": "error",
                "input": {"filePath": f"{web}/src/search/useSearch.ts"},
                "error": f"File not found: {web}/src/search/useSearch.ts",
            },
        ),
        _step(s39, -89.3, 0.82, sent=24_600),
        _start(s39, -89.2),
        _text(s39, -80, "There is no search hook yet. I'll add one that debounces and aborts the stale request."),
        _tool(
            s39,
            -79,
            "write",
            {
                "status": "completed",
                "input": {"filePath": f"{web}/src/search/useSearch.ts", "content": "export function useSearch() {}"},
                "output": "Wrote file successfully.",
                "title": "src/search/useSearch.ts",
            },
        ),
        _done(
            s39,
            -70,
            "Run the search tests",
            "npm test -- search",
            "PASS src/search/SearchBox.test.tsx\n  ✓ debounces input (310 ms)\n  ✓ cancels a stale request (12 ms)\n\n"
            f"Tests: 2 passed, 2 total\n\n{_coverage()}",
            seconds=14,
        ),
        _step(s39, -69.9, 0.97, sent=25_900),
        _start(s39, -69.8),
        _done(
            s39,
            -63,
            "Push the branch",
            "git push origin HEAD:refs/heads/agent/ABC-099-search",
            "To github.com:acme/web.git\n * [new branch]      HEAD -> agent/ABC-099-search\n",
            seconds=3,
        ),
        _tool(
            s39,
            -62,
            "github_create_pull_request",
            {
                "status": "completed",
                "input": {
                    "owner": "acme",
                    "repo": "web",
                    "title": "ABC-099: debounce search and cancel stale requests",
                    "head": "agent/ABC-099-search",
                    "base": "main",
                },
                "output": '{"number": 88, "url": "https://github.com/acme/web/pull/88"}',
                "title": "",
            },
        ),
        _text(
            s39,
            -61.1,
            '{"status": "done", "summary": "Search now debounces input and cancels stale requests.", '
            '"prs": {"web": "https://github.com/acme/web/pull/88"}}',
        ),
        _step(s39, -61, 0.52, reason="stop", sent=30_200),
    ]
    run_40 = [
        _start(s40, -74.1),
        _text(s40, -74, "Reading the failing job's log first."),
        _done(s40, -73, "Find the failing job", "gh run list --branch agent/ABC-100-flaky-test", "", seconds=2),
        _step(s40, -72.5, 0.18),
        _start(s40, -72.4),
        _event("error", s40, -70.1, error={"name": "APIError", "data": {"message": "Rate limited: retry after 60s"}}),
    ]
    # The running runs print as they go (DESIGN §8): what each has done so far, its cost the seeded run's.
    w41, w43 = "/home/op/acme/.treehouse/web-3f9c2a1b/1/web", "/home/op/acme/.treehouse/web-3f9c2a1b/2/web"
    run_41 = [
        _start(s41, 0.5),
        _text(s41, 0.6, "I'll read the login form first, then its tests."),
        _tool(
            s41,
            1,
            "read",
            {
                "status": "completed",
                "input": {"filePath": f"{w41}/src/login/LoginForm.tsx"},
                "output": "export function LoginForm() {}",
                "title": "src/login/LoginForm.tsx",
            },
        ),
        _step(s41, 1.1, 0.2),
        _start(s41, 1.2),
        _done(s41, 27, "Run the login tests", "npm test -- login", "Tests: 4 passed, 4 total\n", seconds=12),
        _step(s41, 27.1, 0.22),
    ]
    run_43 = [
        _start(s43, 5.5),
        _text(s43, 5.6, "The retry test fails on mobile only. Reading the workflow both repositories run."),
        _done(s43, 29, "Read the CI workflow", f"cat {w43}/.github/workflows/ci.yml", "name: ci\n", seconds=1),
        _step(s43, 29.1, 0.12),
    ]
    chore_2 = [
        _start(c2, -240),
        _text(c2, -239.9, "Checking each repository's lockfile against the advisories."),
        _done(
            c2,
            -238,
            "Audit web's dependencies",
            "npm audit --omit=dev",
            "lodash  <=4.17.20\nSeverity: high\nPrototype Pollution - https://github.com/advisories/GHSA-35jh-r3h4-6jhm"
            "\nfix available via `npm audit fix`\n\n1 high severity vulnerability\n",
            seconds=6,
        ),
        _done(c2, -236, "Audit mobile's dependencies", "npm audit --omit=dev", "found 0 vulnerabilities\n", seconds=5),
        _step(c2, -235.9, 0.14),
        _start(c2, -235.8),
        _text(
            c2,
            -233.1,
            json.dumps({"status": "ok", "summary": "One advisory touches web's lockfile.", "findings": [LODASH]}),
        ),
        _step(c2, -233, 0.12, reason="stop"),
    ]
    tick_2 = [
        _start(s2, -60.1),
        _text(s2, -60, "Reading the journal's state first."),
        _done(s2, -59.9, "Read the loop's state", "canopy state", "## Tickets\n- ABC-101 implementing (run 41)\n"),
        _tool(
            s2,
            -59.8,
            "github_pull_request_read",
            {
                "status": "completed",
                "input": {"method": "get_status", "owner": "acme", "repo": "web", "pullNumber": 88},
                "output": '{"state": "pending", "statuses": [{"context": "ci/build", "state": "success"}]}',
                "title": "",
            },
        ),
        # canopy prints a refusal on stderr and exits 1; the runtime still reports the call completed.
        _done(
            s2,
            -59.7,
            "Dispatch ABC-104",
            "canopy dispatch ABC-104 --label canopy --kind implement --repo web",
            "Error: dispatch refused (running): run 43 is still working ABC-104; the refusal was recorded\n",
        ),
        _done(
            s2,
            -59.5,
            "Record the decision on ABC-101",
            "canopy decide ABC-101 wait 'run 41 is implementing it.'",
            "recorded decision 8\n",
        ),
        _text(s2, -59.1, '{"status": "ok", "summary": "mock tick"}'),
        _step(s2, -59, 0.31, reason="stop"),
    ]
    # Review 4 read the diff and the files it touches, then reported what its page shows (mock_reviews).
    review_4 = [
        _start(r4, -57.9),
        _text(r4, -57.8, "I'll read the diff against main, then each file it touches in full."),
        _done(
            r4,
            -57.7,
            "Diff against the base",
            "git diff --stat main...HEAD",
            " src/search/SearchBox.tsx |  4 +++-\n src/search/useSearch.ts  | 21 +++++++++++++++++++++\n",
        ),
        _tool(
            r4,
            -57.5,
            "read",
            {
                "status": "completed",
                "input": {"filePath": "checkout/src/search/useSearch.ts"},
                # The new file is the diff's last hunk, its lines without their `+`.
                "output": "\n".join(line[1:] for line in mock_reviews.DIFF_88.splitlines()[-21:]),
                "title": "src/search/useSearch.ts",
            },
        ),
        _step(r4, -57.4, 0.09, sent=18_200),
        _start(r4, -57.3),
        _text(r4, -57, "The abort is right. `setLoading(false)` only runs on success, so an error leaves it on."),
        _done(r4, -56.6, "Find the other timings", "grep -rn '_MS =' src/config.ts", "export const TOAST_MS = 4000\n"),
        _step(r4, -56.5, 0.11, sent=21_400),
        _start(r4, -56.4),
        _text(r4, -56.1, mock_reviews.LATEST.model_dump_json()),
        _step(r4, -56, 0.04, reason="stop", sent=22_900),
    ]
    # Review 3 ended on a file it could not read, and never printed a result: `unknown`, as its row says.
    review_3 = [
        _start(r3, -69.9),
        _text(r3, -69.8, "Reading the billing client the PR moves to v2."),
        _tool(
            r3,
            -69.5,
            "read",
            {
                "status": "error",
                "input": {"filePath": "checkout/src/billing/client.ts"},
                "error": "File not found: checkout/src/billing/client.ts",
            },
        ),
        _text(r3, -69.2, "The client moved, and the diff does not say where. I'll stop here."),
        _step(r3, -69.1, 0.02, reason="stop", sent=9_400),
    ]
    # The running chore run's log exists, as `canopy chores run` opens it, and holds no events yet.
    none: list[str] = []
    written = (
        ("runs", "39", run_39),
        ("runs", "40", run_40),
        ("runs", "41", run_41),
        ("runs", "43", run_43),
        ("ticks", "2", tick_2),
        ("chore-runs/deps", "2", chore_2),
        ("chore-runs/build-health", "4", none),
        ("reviews", "3", review_3),
        ("reviews", "4", review_4),
        ("task-runs", "1", _task_run_1(t0)),
    )
    for directory, name, lines in written:
        (state_dir / directory).mkdir(mode=0o700, parents=True, exist_ok=True)
        stdout = "\n".join(lines)
        if not lines:
            text = ""
        elif directory == "runs" and name in RUNNING_LOGS:
            # A running worker's stdout so far: no stderr or exit until it ends.
            text = f"--- worker stdout ---\n{stdout}\n"
        elif directory == "runs" and name == "40":
            # What only its output shows: its setup command's, and the runtime's own lines on stderr.
            worker = f"--- worker stdout ---\n{stdout}\n--- worker stderr ---\n{_RUN_STDERR_40}--- worker exit 1 ---\n"
            text = _SETUP_40 + worker
        elif directory in {"runs", "task-runs"}:
            text = f"--- worker stdout ---\n{stdout}\n--- worker stderr ---\n\n--- worker exit 0 ---\n"
        elif directory == "reviews":
            text = f"--- reviewer stdout ---\n{stdout}\n--- reviewer stderr ---\n\n--- reviewer exit 0 ---\n"
        elif directory.startswith("chore-runs/"):
            text = f"--- chore stdout ---\n{stdout}\n--- chore stderr ---\n\n--- chore exit 0 ---\n"
        else:
            # What OpenCode printed on stderr, which only the tick's output shows.
            text = f"{stdout}\n--- stderr ---\n{_TICK_STDERR}"
        logs.write_private(state_dir / directory / f"{name}.log", text)
    # What canopy gave each runtime, kept beside its log: the first model call's input (DESIGN §22).
    prompts = (
        ("runs", "39", _PROMPT_39),
        ("ticks", "2", _PROMPT_TICK_2),
        ("chore-runs/deps", "2", _PROMPT_CHORE_2),
        ("reviews", "4", _PROMPT_REVIEW_4),
    )
    for directory, name, text in prompts:
        logs.write_private(state_dir / directory / f"{name}.prompt", text)


def _task_run_1(t0: datetime) -> list[str]:
    """Task 1's run (mock_tasks): it measured the checkout bundle, cut it over three model calls, and pushed.

    Its calls cost what its row says, $2.12, and the last sent its peak context, as the run's page shows them.

    Returns:
        The session's events, as its log holds them.
    """
    t1 = _Session("ses_task1", t0)
    web = "/home/op/acme/.treehouse/web-3f9c2a1b/4/web"
    build = f"cd {web} && npx vite build --mode production 2>&1 | grep checkout"
    return [
        _start(t1, -418),
        _text(t1, -417.9, "I'll measure the checkout bundle first, so each cut has a number against it."),
        _done(
            t1,
            -416,
            "Measure the checkout bundle",
            build,
            "dist/assets/checkout-4f1c9a.js  934.12 kB │ gzip: 291.40 kB\n",
            seconds=74,
        ),
        _done(
            t1,
            -414,
            "Find what the bundle pulls in",
            "npx source-map-explorer dist/assets/checkout-*.js --json | jq -r '.results[0].files | keys[]'",
            "node_modules/moment/locale\nnode_modules/@acme/pay-sdk\nnode_modules/lodash\nsrc/checkout\n",
            seconds=9,
        ),
        _step(t1, -413.9, 0.52, sent=41_000),
        _start(t1, -413.8),
        _text(t1, -413.5, "moment's locales, the payment SDK, and lodash whole: the three the task names."),
        _edit(t1, -400, f"{web}/src/checkout/DatePicker.tsx"),
        _edit(t1, -396, f"{web}/src/checkout/AddressStep.tsx"),
        _done(t1, -390, "Run the checkout tests", "npm test -- src/checkout", "Tests: 48 passed\n", seconds=41),
        _step(t1, -389.9, 0.71, sent=78_000),
        _start(t1, -389.8),
        _done(
            t1,
            -386,
            "Measure the checkout bundle again",
            build,
            "dist/assets/checkout-a07e3d.js  612.48 kB │ gzip: 190.02 kB\n",
            seconds=71,
        ),
        _done(
            t1,
            -383,
            "Push the branch",
            "git push origin HEAD:agent/task/1",
            "To github.com:acme/web.git\n * [new branch]      HEAD -> agent/task/1\n",
            seconds=3,
        ),
        _text(t1, -380.2, "Cut the checkout bundle from 934 kB to 612 kB; filed two tickets for what is left."),
        _step(t1, -380.1, 0.89, reason="stop", sent=127_200),
    ]


def _edit(session: _Session, minutes: float, path: str) -> str:
    """An edit call that applied.

    Returns:
        The `tool_use` event as one line of JSON.
    """
    state = {"status": "completed", "input": {"filePath": path}, "output": "Edit applied successfully.", "title": path}
    return _tool(session, minutes, "edit", state)


def _start(session: _Session, minutes: float) -> str:
    return _event("step_start", session, minutes, part={"type": "step-start"})


def _event(kind: str, session: _Session, minutes: float, **fields: object) -> str:
    """One event as `opencode run --format json` prints it, `minutes` after T0.

    Returns:
        The event as one line of JSON.
    """
    ms = int((session.t0 + timedelta(minutes=minutes)).timestamp() * 1000)
    return json.dumps({"type": kind, "timestamp": ms, "sessionID": session.id, **fields})


def _text(session: _Session, minutes: float, text: str) -> str:
    return _event("text", session, minutes, part={"type": "text", "text": text})


def _tool(session: _Session, minutes: float, tool: str, state: Mapping[str, object], seconds: float = 1) -> str:
    ms = int((session.t0 + timedelta(minutes=minutes)).timestamp() * 1000)
    metadata: dict[str, object] = {}
    timed = {**state, "metadata": metadata, "time": {"start": ms - int(seconds * 1000), "end": ms}}
    return _event(
        "tool_use",
        session,
        minutes,
        part={"type": "tool", "callID": f"call_{ms}", "tool": tool, "state": timed},
    )


def _step(session: _Session, minutes: float, cost: float, reason: str = "tool-calls", sent: int | None = None) -> str:
    # Most of what a call sends is read back from the provider's cache, after the first. `sent` is the call's context,
    # for a session whose context grows as a real one does; without it, a share of the cost.
    sent = int(cost * 30_000) if sent is None else sent
    tokens = {
        "input": sent // 4,
        "output": int(cost * 3_000),
        "reasoning": int(cost * 1_000),
        "cache": {"read": sent - sent // 4 - 512, "write": 512},
    }
    return _event(
        "step_finish",
        session,
        minutes,
        part={"type": "step-finish", "reason": reason, "cost": cost, "tokens": tokens},
    )


def _done(session: _Session, minutes: float, title: str, command: str, output: str, *, seconds: float = 1) -> str:
    """A bash call that completed.

    Returns:
        The `tool_use` event as one line of JSON.
    """
    state = {"status": "completed", "input": {"command": command, "description": title}, "output": output}
    return _tool(session, minutes, "bash", {**state, "title": title}, seconds)


def _coverage() -> str:
    """The table Jest prints after a run's tests when it collects coverage: a line per file, a long tool result.

    Returns:
        The table, as printed.
    """
    dirs = ("api", "components", "hooks", "lib", "pages", "routes", "search", "store", "styles", "utils")
    names = ("client", "format", "index", "keys", "list", "menu", "panel", "query", "table", "toast", "types", "view")
    rule = f"{'-' * 36}|---------|----------|---------|---------|-------------------"
    lines = [rule, f"{'File':<36}| % Stmts | % Branch | % Funcs | % Lines | Uncovered Line #s", rule]
    for i, (folder, name) in enumerate(itertools.product(dirs, names)):
        uncovered = (i * 37) % 41
        covered = 100 - uncovered
        missed = f"{12 + i % 30}-{40 + i % 50}" if uncovered else ""
        row = f"{covered:>8.2f} | {covered - i % 9:>8.2f} | {covered - i % 5:>7.2f} | {covered:>7.2f}"
        lines.append(f"{f'src/{folder}/{name}.ts':<36}|{row} | {missed}")
    return "\n".join([*lines, rule, ""])
