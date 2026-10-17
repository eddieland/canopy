"""The web UI over the operator's own journal (DESIGN §22, ROADMAP M20): its channel writes through the CLI's guards,
its pages read what `canopy show` and `canopy status` print, and `canopy loop` serves it from a thread."""

import dataclasses
import json
import socket  # noqa: TID251  (a test asks the OS for a free port; canopy itself opens no socket)
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest

from canopy.cli.main import main
from canopy.core import agent_output, config, conversation, db, pause
from canopy.core.context import Context
from canopy.core.vocab import RunStatus, StartStatus, TickStatus
from canopy.infra import resources
from canopy.loop import repeat, reread, tick_now, web
from canopy.reviews import grants
from canopy.runs import policy
from canopy.serve import live, secret, views
from canopy.serve.schema import LoopUpdated
from tests.canopy.helpers import KEY, FakeTime, canopy, console, context, in_run, overseer_does, present, running_run
from tests.canopy.web_helpers import ORIGIN, refused, signed_in_client
from tests.conftest import SHARED_TOML, CanopyEnv, user_toml


def test_a_path_shown_from_the_workspace_root_joins_metas_root_back_to_the_journals(ctx: Context) -> None:
    # The UI copies a path whole by joining what a page shows to /meta's root: the two must agree.
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    db.touch_ticket(ctx.conn, KEY, ctx.repo)
    slot = ctx.workspace.root / ".treehouse" / "repo-3f9c2a1b" / "1" / "repo"
    run_id = db.insert_run(
        ctx.conn,
        tick_id=tick_id,
        key=KEY,
        kind="implement",
        branch=f"agent/{KEY}-work",
        slots=[
            db.RunSlot(repo="repo", slot_path=slot, lease_id="lease-1", lease_holder="canopy:x", base_branch="main")
        ],
        runs_dir=ctx.state_dir / "runs",
        private=False,
    )
    db.finish_tick(ctx.conn, tick_id, TickStatus.OK, "test")
    stored = present(db.get_run(ctx.conn, run_id))

    c, _ = signed_in_client(ctx)
    root = Path(c.get("/api/meta").json()["workspace_root"])
    run = c.get(f"/api/runs/{run_id}").json()
    assert root.is_absolute()
    assert not Path(run["log_path"]).is_absolute()
    assert root / run["log_path"] == Path(stored["log_path"])
    assert [root / w for w in run["worktrees"]] == [slot]


def test_a_runs_spend_is_its_new_tokens_and_its_peak_context(ctx: Context) -> None:
    run_id = running_run(ctx, KEY, private=False)
    usage = agent_output.Usage(0.5, input=9000, output=1000, reasoning=0, cache_read=40_000, cache_write=0)
    db.set_run_report(ctx.conn, "runs", run_id, "ses_w1", dataclasses.replace(usage, peak_context=26_000))

    c, _ = signed_in_client(ctx)
    run = c.get(f"/api/runs/{run_id}").json()
    assert (run["cost_usd"], run["new_tokens"], run["peak_context"]) == (0.5, 10_000, 26_000)  # no cache reads

    db.set_run_report(ctx.conn, "runs", run_id, "ses_w1", usage)  # as a run recorded before the peak was kept
    run = c.get(f"/api/runs/{run_id}").json()
    assert (run["new_tokens"], run["peak_context"]) == (10_000, None)


def test_a_ticks_spend_is_its_overseers_new_tokens_and_peak_context(ctx: Context) -> None:
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    c, _ = signed_in_client(ctx)
    tick = c.get("/api/ticks").json()[0]
    assert (tick["new_tokens"], tick["peak_context"]) == (None, None)  # nothing reported while it runs

    usage = agent_output.Usage(0.25, input=3000, output=400, reasoning=100, cache_read=20_000, cache_write=500)
    db.set_tick_report(ctx.conn, tick_id, "ses_o1", dataclasses.replace(usage, peak_context=12_000))
    db.finish_tick(ctx.conn, tick_id, TickStatus.OK, "test")
    tick = c.get("/api/ticks").json()[0]
    assert (tick["cost_usd"], tick["new_tokens"], tick["peak_context"]) == (0.25, 4000, 12_000)  # no cache reads
    detail = c.get(f"/api/ticks/{tick_id}").json()["tick"]
    assert (detail["new_tokens"], detail["peak_context"]) == (4000, 12_000)


def test_meta_carries_each_repositorys_branch_url_when_set(canopy_env: CanopyEnv, ctx: Context) -> None:
    c, _ = signed_in_client(ctx)
    assert c.get("/api/meta").json()["branch_urls"] == {}

    template = "https://github.com/acme/repo/tree/{branch}"
    shared = canopy_env.shared_file.read_text()
    canopy_env.write_shared(shared.replace("[tracker]", f'branch_url = "{template}"\n\n[tracker]', 1))
    other = context(canopy_env)
    try:
        c, _ = signed_in_client(other)
        assert c.get("/api/meta").json()["branch_urls"] == {"repo": template}
    finally:
        other.conn.close()


def test_meta_carries_the_trackers_ticket_url_when_set(canopy_env: CanopyEnv, ctx: Context) -> None:
    c, _ = signed_in_client(ctx)
    assert c.get("/api/meta").json()["ticket_url"] is None

    template = "https://jira.example/browse/{key}"
    canopy_env.append_shared(f'ticket_url = "{template}"\n')
    other = context(canopy_env)
    try:
        c, _ = signed_in_client(other)
        assert c.get("/api/meta").json()["ticket_url"] == template
    finally:
        other.conn.close()


def test_the_web_channel_starts_stops_and_replies_through_the_cli_guards(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)

    assert refused(
        c.post(f"/api/tickets/{KEY}/replies", json={"body": "hi", "submission": "form-0001"}, headers=headers)
    ) == (f"unknown: canopy has no record of {KEY}: start it, or label it and let a tick see it, before replying")
    assert refused(c.post(f"/api/tickets/{KEY}/stop", json={"now": False}, headers=headers)).startswith("not_started")
    assert refused(c.post("/api/tickets/run:4/start", headers=headers)).startswith("unsupported")
    assert refused(c.post("/api/tickets/a%20b/start", headers=headers)).startswith("bad_ref")

    started = c.post(f"/api/tickets/{KEY}/start", headers=headers)
    assert started.json() == {"already": False, "running_run": None, "running_private": None}
    record = present(conversation.start_of(ctx.conn, KEY))
    assert (record.status, record.channel) == (StartStatus.STARTED, "web")
    assert c.post(f"/api/tickets/{KEY}/start", headers=headers).json()["already"] is True

    too_long = {"body": "x" * (conversation.MAX_OPERATOR + 1), "submission": "form-0002"}
    assert refused(c.post(f"/api/tickets/{KEY}/replies", json=too_long, headers=headers)).startswith("bad_body")
    assert refused(
        c.post(f"/api/tickets/{KEY}/replies", json={"body": "  ", "submission": "form-0002"}, headers=headers)
    ).startswith("bad_body")
    assert (
        c.post(f"/api/tickets/{KEY}/replies", json={"body": "x", "submission": "a b"}, headers=headers).status_code
        == 422
    )

    body = {"body": "  Blue, to match the header.  ", "submission": "form-0003"}
    first = c.post(f"/api/tickets/{KEY}/replies", json=body, headers=headers).json()
    again = c.post(f"/api/tickets/{KEY}/replies", json=body, headers=headers).json()
    assert first["new"] is True
    assert again == {**first, "new": False}
    [message] = db.messages_of(ctx.conn, conversation.TICKET, KEY, 10)
    assert (message["source"], message["kind"], message["channel"]) == ("operator", "reply", "web")
    assert (message["body"], message["submission"]) == ("Blue, to match the header.", "web:form-0003")

    stopped = c.post(f"/api/tickets/{KEY}/stop", json={"now": False}, headers=headers).json()
    assert stopped == {"already": False, "running_run": None, "ended": False}
    record = present(conversation.start_of(ctx.conn, KEY))
    assert (record.status, record.channel) == (StartStatus.STOPPED, "web")


def test_stop_now_from_the_web_ends_the_run_as_canopy_stop_now_does(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post(f"/api/tickets/{KEY}/start", headers=headers).status_code == 200
    run_id = running_run(ctx, KEY)

    graceful = c.post(f"/api/tickets/{KEY}/stop", json={"now": False}, headers=headers).json()
    assert graceful == {"already": False, "running_run": run_id, "ended": False}
    run = present(db.get_run(ctx.conn, run_id))
    assert run["status"] == "running"

    now = c.post(f"/api/tickets/{KEY}/stop", json={"now": True}, headers=headers).json()
    assert now == {"already": True, "running_run": run_id, "ended": True}
    run = present(db.get_run(ctx.conn, run_id))
    assert run["status"] == "stopped"
    assert "canopy stop --now" in str(run["result_json"])


def test_forget_from_the_web_needs_the_key_typed_and_then_forgets_as_canopy_forget_does(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    pr = "https://example.test/pr/1"
    assert refused(c.post(f"/api/tickets/{KEY}/forget", json={"confirm": KEY}, headers=headers)).startswith("unknown")
    run_id = running_run(ctx, KEY)
    db.set_unit(ctx.conn, KEY, ctx.repo, "repo", pr_url=pr, phase="in_review")
    ctx.conn.execute("UPDATE tickets SET branch = ? WHERE key = ?", (f"agent/{KEY}-work", KEY))
    ctx.conn.commit()

    # The challenge is checked before anything is read: a wrong or missing key forgets nothing.
    assert refused(c.post(f"/api/tickets/{KEY}/forget", json={"confirm": "PROJ-2"}, headers=headers)) == (
        f"not_confirmed: type {KEY} to confirm forgetting its work"
    )
    assert c.post(f"/api/tickets/{KEY}/forget", json={}, headers=headers).status_code == 422
    # The CLI's guards hold: a run still works it.
    assert refused(c.post(f"/api/tickets/{KEY}/forget", json={"confirm": KEY}, headers=headers)).startswith("running")
    assert db.units(ctx.conn, KEY)

    ctx.conn.execute("UPDATE runs SET status = 'done', ended_at = started_at WHERE id = ?", (run_id,))
    ctx.conn.commit()
    forgot = c.post(f"/api/tickets/{KEY}/forget", json={"confirm": KEY}, headers=headers)
    assert forgot.json() == {"branch": f"agent/{KEY}-work", "prs": [pr]}
    ticket = present(db.get_ticket(ctx.conn, KEY))
    assert (ticket.branch, ticket.phase, ticket.forgotten_run_id) == (None, None, run_id)
    assert db.units(ctx.conn, KEY) == []
    assert db.get_run(ctx.conn, run_id) is not None


def ended_run(ctx: Context, key: str, kind: str) -> int:
    """A `kind` run of `key` in the workspace's repository, ended `failed`: it counts toward the unit's limit."""
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    slot = db.RunSlot("repo", Path("/pool/1"), f"lease-{key}", f"canopy:{key}", "main")
    run_id = db.insert_run(
        ctx.conn,
        tick_id=tick_id,
        key=key,
        kind=kind,
        branch=f"agent/{key}-work",
        slots=[slot],
        runs_dir=ctx.state_dir / "runs",
    )
    ctx.conn.execute("UPDATE runs SET status = 'failed', ended_at = started_at WHERE id = ?", (run_id,))
    db.finish_tick(ctx.conn, tick_id, TickStatus.OK, "test")
    return run_id


def test_grant_from_the_web_raises_a_units_limit_as_canopy_grant_does(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)

    def grant(body: dict[str, str]) -> httpx2.Response:
        return c.post(f"/api/tickets/{KEY}/grants", json=body, headers=headers)

    assert refused(grant({"kind": "implement"})).startswith("unknown: canopy has no record of PROJ-1")
    for _ in range(2):
        ended_run(ctx, KEY, "implement")
    implement = {"kind": "implement", "repo": "repo", "pr_url": None, "runs": 2, "granted": 0, "limit": 2}
    assert c.get(f"/api/tickets/{KEY}").json()["limits"] == [
        implement,
        {"kind": "fix-ci", "repo": "repo", "pr_url": None, "runs": 0, "granted": 0, "limit": 2},
        {"kind": "resume", "repo": "repo", "pr_url": None, "runs": 0, "granted": 0, "limit": 3},
    ]

    # The CLI's guards hold, and a split's limit is only config's to raise.
    assert refused(grant({"kind": "implement", "repo": "other"})) == "unknown_repo: PROJ-1 has had no runs in other"
    assert grant({"kind": "split"}).status_code == 422
    assert c.post(f"/api/tickets/{KEY}/grants", json={"kind": "implement"}, headers={"origin": ORIGIN}).status_code == (
        403
    )
    assert policy.grants(ctx.conn) == {}

    # One more run, every earlier one still counted; the ticket's page shows the new limit.
    assert grant({"kind": "implement"}).json() == {"kind": "implement", "repo": "repo", "runs": 2, "limit": 3}
    assert policy.grants(ctx.conn) == {(KEY, "repo"): {"implement": 1}}
    assert c.get(f"/api/tickets/{KEY}").json()["limits"][0] == {**implement, "granted": 1, "limit": 3}


def test_grant_from_the_web_raises_a_prs_review_limit_as_canopy_grant_review_does(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    pr = "https://github.com/acme/repo/pull/7"

    def grant(url: str) -> httpx2.Response:
        return c.post("/api/pull-request/grants", params={"url": url}, headers=headers)

    assert refused(grant(pr)).startswith("unknown: canopy has not reviewed")
    assert refused(grant("https://github.com/acme/repo/issues/7")).startswith("bad_ref")
    assert refused(grant(KEY)).startswith("bad_ref")

    ended_run(ctx, KEY, "implement")
    db.set_unit(ctx.conn, KEY, ctx.repo, "repo", pr_url=pr, phase="in_review")
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    db.insert_review_run(
        ctx.conn,
        tick_id=tick_id,
        pr_url=pr,
        sha="a" * 40,
        ticket=KEY,
        repo="repo",
        purpose="own",
        logs_dir=ctx.state_dir / "reviews",
    )
    db.finish_tick(ctx.conn, tick_id, TickStatus.OK, "test")
    review = {"kind": "review", "repo": "repo", "pr_url": pr, "runs": 1, "granted": 0, "limit": 3}
    assert c.get("/api/pull-request", params={"url": pr}).json()["review_limit"] == review

    assert grant(pr).json() == {"kind": "review", "repo": None, "runs": 1, "limit": 4}
    assert grants.granted(ctx.conn, pr) == 1
    assert c.get("/api/pull-request", params={"url": pr}).json()["review_limit"] == {**review, "granted": 1, "limit": 4}
    # The ticket's page shows the review limit of its unit's PR after its units' attempt limits.
    assert c.get(f"/api/tickets/{KEY}").json()["limits"][-1] == {**review, "granted": 1, "limit": 4}


def test_an_item_about_a_pr_no_ticket_owns_names_the_pr(ctx: Context) -> None:
    c, _ = signed_in_client(ctx)
    pr = "https://github.com/acme/repo/pull/7"
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    db.record_decision(ctx.conn, tick_id, None, "attention:review_limit", "at its limit", pr=pr)
    db.finish_tick(ctx.conn, tick_id, TickStatus.OK, "test")
    [item] = c.get("/api/attention").json()
    assert (item["pr"], item["ticket_key"], item["ticket_title"], item["subject"]) == (pr, None, None, f"pr:{pr}")


def test_the_web_channel_pauses_and_resumes_the_loop_as_canopy_pause_and_resume_do(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.get("/api/loop").json() == {"paused": None, "notice": None, "memory": None}
    # A write without the session's token is refused, as every other write is.
    assert c.post("/api/loop/pause", headers={"origin": ORIGIN}).status_code == 403
    assert pause.paused(ctx.conn) is None

    paused = c.post("/api/loop/pause", headers=headers).json()
    assert paused["already"] is False
    assert paused["loop"]["paused"]["channel"] == "web"
    held = present(pause.paused(ctx.conn))
    assert held.channel == "web"
    again = c.post("/api/loop/pause", headers=headers).json()
    assert again == {**paused, "already": True}
    assert c.get("/api/loop").json() == paused["loop"]

    assert c.post("/api/loop/resume", headers=headers).json() == {
        "already": False,
        "loop": {"paused": None, "notice": None, "memory": None},
    }
    assert pause.paused(ctx.conn) is None
    assert c.post("/api/loop/resume", headers=headers).json()["already"] is True


def test_a_web_reload_reads_the_config_and_asks_the_loop_to_read_it_again(ctx: Context, canopy_env: CanopyEnv) -> None:
    reload = reread.Reload()
    c, headers = signed_in_client(ctx, reload)
    assert c.post("/api/loop/reload").status_code == 403  # a write: it needs the session's token
    assert not reload.requested

    unchanged = c.post("/api/loop/reload", headers=headers)
    assert unchanged.json() == {"changed": [], "restart": [], "after_tick": False}
    assert reload.requested

    reload.requested, reload.ticking = False, True
    canopy_env.write_user(user_toml() + "\n[capacity]\nmax_workers = 7\n\n[serve]\nport = 8766\n")
    found = c.post("/api/loop/reload", headers=headers).json()
    assert found == {"changed": ["capacity.max_workers", "serve.port"], "restart": ["serve.port"], "after_tick": True}
    assert reload.requested

    reload.requested = False
    canopy_env.write_user(user_toml() + "\n[capacity]\nmax_workers = 'many'\n")
    assert refused(c.post("/api/loop/reload", headers=headers)).startswith("config_invalid: ")
    assert "capacity.max_workers" in refused(c.post("/api/loop/reload", headers=headers))
    assert not reload.requested  # the loop is not asked to read a config that does not load


def test_a_web_tick_now_asks_the_loop_for_a_tick(ctx: Context) -> None:
    reload, asked = reread.Reload(), tick_now.TickNow()
    c, headers = signed_in_client(ctx, reload, asked)
    assert c.post("/api/loop/tick").status_code == 403  # a write: it needs the session's token
    assert not asked.requested

    assert c.post("/api/loop/tick", headers=headers).json() == {"after_tick": False}
    assert asked.take()
    assert not asked.take()  # one request ends one wait

    reload.ticking = True
    assert c.post("/api/loop/tick", headers=headers).json() == {"after_tick": True}
    assert asked.requested  # kept for the wait after the running tick


def test_the_stream_sends_the_pause_when_it_changes(ctx: Context) -> None:
    backend = web.backend(ctx, reread.Reload(), tick_now.TickNow())
    sent = live._Sent()  # noqa: SLF001  (the stream's own record of what it sent)
    first = [e.root for e in sent.changes(backend, ctx)]
    assert LoopUpdated(paused=None) in first
    assert sent.changes(backend, ctx) == []
    pause.pause(ctx.conn, channel="cli")
    [event] = [e.root for e in sent.changes(backend, ctx)]
    assert isinstance(event, LoopUpdated)
    assert event.paused is not None
    assert event.paused.channel == "cli"


def test_a_web_pause_holds_the_loops_wait_until_the_web_resumes_it(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    c, headers = signed_in_client(ctx)
    time_ = FakeTime()

    def browser() -> None:
        if len(time_.slept) == 1:
            assert c.post("/api/loop/pause", headers=headers).status_code == 200
        elif len(time_.slept) == 300:  # 150 seconds in, past the one-minute wait's deadline
            assert c.post("/api/loop/resume", headers=headers).status_code == 200

    time_.on_sleep = browser
    with overseer_does():
        statuses = repeat.run(
            ctx,
            dry_run=True,
            interval_minutes=1,
            max_ticks=2,
            console=console()[0],
            stop=repeat.Stop(),
            sleep=time_.sleep,
            clock=time_.clock,
        )
    assert statuses == {"ok": 2}
    assert sum(time_.slept) == 150


def test_the_pages_read_what_canopy_show_and_status_print(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post(f"/api/tickets/{KEY}/start", headers=headers).status_code == 200
    run_id = running_run(ctx, KEY)
    db.set_ticket(ctx.conn, KEY, ctx.repo, title="Pick a color")
    run = present(db.get_run(ctx.conn, run_id))
    result = {"status": "blocked", "summary": "half done\x1b[2J", "question": "Red <b>or</b> blue?"}
    assert conversation.close_run(ctx.conn, ctx.config, run, RunStatus.BLOCKED, json.dumps(result))
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    db.record_decision(ctx.conn, tick_id, KEY, "attention:needs_reviewer", "https://example.test/pr/9")
    db.finish_tick(ctx.conn, tick_id, TickStatus.OK, "test")

    [item] = c.get("/api/attention").json()
    assert (item["ticket_key"], item["ticket_title"], item["reason"], item["detail"]) == (
        KEY,
        "Pick a color",
        "needs_reviewer",
        "https://example.test/pr/9",
    )

    [listed] = c.get("/api/runs").json()
    assert (listed["id"], listed["state"], listed["private"]) == (run_id, "blocked", True)
    assert listed["summary"] == "half done [2J"  # control characters dropped
    assert listed["ticket_title"] == "Pick a color"

    assert [(t["key"], t["title"]) for t in c.get("/api/tickets").json()] == [(KEY, "Pick a color")]
    detail = c.get(f"/api/tickets/{KEY}").json()
    question = detail["messages"][-1]
    assert (question["kind"], question["body"]) == ("question", "Red <b>or</b> blue?")
    assert detail["ticket"]["awaiting"] == question["id"]
    assert detail["ticket"]["private"] is True
    assert [r["status"] for r in detail["runs"]] == ["blocked"]
    assert c.get("/api/tickets/PROJ-404").status_code == 404

    reply = {"body": "Blue.", "submission": "form-0004"}
    assert c.post(f"/api/tickets/{KEY}/replies", json=reply, headers=headers).json()["answers"] == question["id"]
    assert c.get(f"/api/tickets/{KEY}").json()["ticket"]["awaiting"] is None


def test_summaries_and_rationales_keep_their_line_breaks(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post(f"/api/tickets/{KEY}/start", headers=headers).status_code == 200
    run = present(db.get_run(ctx.conn, running_run(ctx, KEY)))
    result = {"status": "done", "summary": "Done:\r\n- one\x1b  \n- two\n\n"}
    assert conversation.close_run(ctx.conn, ctx.config, run, RunStatus.DONE, json.dumps(result))
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    db.record_decision(ctx.conn, tick_id, KEY, "wait", "Checks running:\n  - lint")
    db.finish_tick(ctx.conn, tick_id, TickStatus.OK, "\nOne wait.\nNothing else.\n")

    [listed] = c.get("/api/runs").json()
    assert listed["summary"] == "Done:\n- one\n- two"  # control characters dropped, trailing space cut
    detail = c.get(f"/api/ticks/{tick_id}").json()
    assert detail["tick"]["summary"] == "One wait.\nNothing else."
    assert [d["rationale"] for d in detail["decisions"]] == ["Checks running:\n  - lint"]


def test_spend_is_what_the_runs_and_ticks_that_started_in_the_last_day_30_days_and_ever_cost(ctx: Context) -> None:
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    backend = dataclasses.replace(web.backend(ctx, reread.Reload(), tick_now.TickNow()), clock=lambda: now)
    nothing = views.spend(backend, ctx)
    assert (nothing.day.cost_usd, nothing.month.cost_usd, nothing.total_usd) == (None, None, None)  # nothing yet

    def started(table: str, row_id: int, hours_ago: float, cost: float | None) -> None:
        at = db.format_time(now - timedelta(hours=hours_ago))
        ctx.conn.execute(f"UPDATE {table} SET started_at = ?, cost_usd = ? WHERE id = ?", (at, cost, row_id))  # noqa: S608

    started("runs", running_run(ctx, KEY), 2, 1.25)
    started("runs", running_run(ctx, "PROJ-2"), 25, 9.0)  # before the day, within the 30 days
    started("runs", running_run(ctx, "PROJ-3"), 1, None)  # reported nothing
    started("runs", running_run(ctx, "PROJ-4"), 30 * 24 + 1, 40.0)  # before both
    started("ticks", db.start_tick(ctx.conn, dry_run=False), 23.5, 0.5)

    spend = views.spend(backend, ctx)
    day, month = spend.day, spend.month
    assert (day.hours, day.since, day.cost_usd) == (24, now - timedelta(hours=24), pytest.approx(1.75))
    assert (month.hours, month.since, month.cost_usd) == (720, now - timedelta(days=30), pytest.approx(10.75))
    assert spend.total_usd == pytest.approx(50.75)  # everything, the run before both windows included


def test_a_tickets_cost_is_every_run_of_it_and_every_review_naming_it(ctx: Context) -> None:
    c, _ = signed_in_client(ctx)
    first = running_run(ctx, KEY)
    assert c.get(f"/api/tickets/{KEY}").json()["cost"] == {"runs": 1, "reviews": 0, "priced": 0, "cost_usd": None}

    second = running_run(ctx, KEY)
    running_run(ctx, "PROJ-2")  # another ticket's
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    review = db.insert_review_run(
        ctx.conn,
        tick_id=tick_id,
        pr_url="https://github.com/acme/web/pull/1",
        sha="a" * 40,
        ticket=KEY,
        repo=None,
        purpose="own",
        logs_dir=ctx.workspace.root,
    )
    for table, row_id, cost in (("runs", first, 1.25), ("runs", second, None), ("review_runs", review, 0.5)):
        ctx.conn.execute(f"UPDATE {table} SET cost_usd = ? WHERE id = ?", (cost, row_id))  # noqa: S608
    ctx.conn.execute("UPDATE ticks SET cost_usd = 3.0 WHERE id = ?", (tick_id,))  # the overseer's is the workspace's

    cost = c.get(f"/api/tickets/{KEY}").json()["cost"]
    assert cost == {"runs": 2, "reviews": 1, "priced": 2, "cost_usd": pytest.approx(1.75)}


def test_the_last_tick_is_the_latest_row_with_its_status_and_cost(ctx: Context) -> None:
    c, _ = signed_in_client(ctx)
    assert c.get("/api/tick").json() == {"tick": None, "acknowledged": None}
    db.start_tick(ctx.conn, dry_run=False)
    later = db.start_tick(ctx.conn, dry_run=True)
    db.finish_tick(ctx.conn, later, TickStatus.OK, "nothing to do\x1b[2J")
    ctx.conn.execute("UPDATE ticks SET cost_usd = 0.25 WHERE id = ?", (later,))

    tick = c.get("/api/tick").json()["tick"]
    assert (tick["id"], tick["status"], tick["dry_run"], tick["cost_usd"]) == (later, "ok", True, 0.25)
    assert tick["summary"] == "nothing to do [2J"  # control characters dropped
    assert tick["ended_at"] is not None


def test_a_message_is_acknowledged_by_the_latest_ok_tick_that_read_it(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post(f"/api/tickets/{KEY}/start", headers=headers).status_code == 200
    first = db.start_tick(ctx.conn, dry_run=False)
    db.set_tick_read(ctx.conn, first)
    db.finish_tick(ctx.conn, first, TickStatus.OK, "read nothing")
    assert c.get("/api/tick").json()["acknowledged"] == 0

    reply = {"body": "blue", "submission": "form-ack-1"}
    replied = c.post(f"/api/tickets/{KEY}/replies", json=reply, headers=headers).json()["message_id"]
    # A tick that read the reply but did not close `ok` acknowledges nothing: the attention list is still the last's.
    failed = db.start_tick(ctx.conn, dry_run=False)
    db.set_tick_read(ctx.conn, failed)
    db.finish_tick(ctx.conn, failed, TickStatus.OVERSEER_FAILED, "exit 1")
    last = c.get("/api/tick").json()
    assert (last["tick"]["id"], last["acknowledged"]) == (failed, 0)

    read = db.start_tick(ctx.conn, dry_run=False)
    db.set_tick_read(ctx.conn, read)
    assert c.get("/api/tick").json()["acknowledged"] == 0  # still running
    db.finish_tick(ctx.conn, read, TickStatus.OK, "resumed")
    assert c.get("/api/tick").json()["acknowledged"] == replied


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def serve_on(env: CanopyEnv, port: int, extra: str = "") -> None:
    env.write_user(user_toml() + f"\n[serve]\nport = {port}\n{extra}")


def wait_until_up(url: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            httpx2.get(url, timeout=1)
        except httpx2.TransportError:
            time.sleep(0.05)
        else:
            return
    raise AssertionError(f"nothing answered at {url}")


def test_the_loop_serves_the_ui_and_a_web_reply_ends_its_wait(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    port = free_port()
    serve_on(canopy_env, port)
    secret.create(secret.path(), rotate=False)
    key = secret.read(secret.path())
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    conversation.start(ctx.conn, ctx.config, conversation.parse_ref(KEY), repo=ctx.repo, channel="cli")
    base = f"http://127.0.0.1:{port}"
    time_ = FakeTime()
    seen: list[dict[str, object]] = []

    def reply_from_the_browser() -> None:
        if seen:
            return
        wait_until_up(f"{base}/api/session")
        with httpx2.Client(base_url=base, timeout=10) as browser:
            assert browser.get("/api/tickets").status_code == 401
            token = browser.post("/api/session", json={"secret": key}).json()["token"]
            seen.extend(browser.get("/api/tickets").json())
            response = browser.post(
                f"/api/tickets/{KEY}/replies",
                json={"body": "Go ahead.", "submission": "form-loop-1"},
                headers={"x-canopy-token": token, "origin": base},
            )
            assert response.status_code == 200, response.text

    time_.on_sleep = reply_from_the_browser
    term, out = console()
    with overseer_does(canopy("decide", KEY, "wait", "--rationale", "waiting on the operator")):
        statuses = repeat.run(
            ctx,
            dry_run=True,
            interval_minutes=15,
            max_ticks=2,
            console=term,
            stop=repeat.Stop(),
            serve=True,
            sleep=time_.sleep,
            clock=time_.clock,
        )

    assert statuses == {"ok": 2}
    assert [t["key"] for t in seen] == [KEY]
    # The reply, from the server's thread, woke the wait as `canopy reply` does: a minute in, not fifteen.
    assert sum(time_.slept) == pytest.approx(60)  # loop.min_gap_minutes, by default
    text = out.getvalue()
    assert f"web UI      {base}/" in text
    # Stopping the loop stopped the server.
    with pytest.raises(httpx2.TransportError):
        httpx2.get(f"{base}/api/session", timeout=1)


def test_a_reload_from_the_ui_reaches_the_loop_and_what_the_ui_serves(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    port = free_port()
    serve_on(canopy_env, port)
    secret.create(secret.path(), rotate=False)
    key = secret.read(secret.path())
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    base = f"http://127.0.0.1:{port}"
    time_ = FakeTime()
    ticket_urls: list[object] = []
    reloads: list[dict[str, object]] = []
    url = "https://example.test/browse/{key}"

    def reload_from_the_browser() -> None:
        if len(ticket_urls) == 2:
            return
        wait_until_up(f"{base}/api/session")
        with httpx2.Client(base_url=base, timeout=10) as browser:
            token = browser.post("/api/session", json={"secret": key}).json()["token"]
            ticket_urls.append(browser.get("/api/meta").json()["ticket_url"])
            if not reloads:
                canopy_env.write_shared(SHARED_TOML + f'ticket_url = "{url}"\n')
                response = browser.post("/api/loop/reload", headers={"x-canopy-token": token, "origin": base})
                assert response.status_code == 200, response.text
                reloads.append(response.json())

    time_.on_sleep = reload_from_the_browser
    term, out = console()
    with overseer_does():
        statuses = repeat.run(
            ctx,
            dry_run=True,
            interval_minutes=15,
            max_ticks=2,
            console=term,
            stop=repeat.Stop(),
            serve=True,
            sleep=time_.sleep,
            clock=time_.clock,
        )

    assert statuses == {"ok": 2}
    assert reloads == [{"changed": ["tracker.ticket_url"], "restart": [], "after_tick": False}]
    # The wait's next step applied it, and the server served it from the next request on.
    assert ticket_urls == [None, url]
    assert "config reloaded  tracker.ticket_url changed" in out.getvalue()


def test_without_a_secret_the_loop_serves_nothing_and_says_how_to_make_one(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    port = free_port()
    serve_on(canopy_env, port)
    term, out = console()
    with overseer_does():
        statuses = repeat.run(
            context(canopy_env),
            dry_run=True,
            interval_minutes=1,
            max_ticks=1,
            console=term,
            stop=repeat.Stop(),
            serve=True,
        )
    assert statuses == {"ok": 1}
    assert "not served: there is no listener secret at" in out.getvalue()
    assert "canopy secret" in out.getvalue()


@pytest.mark.parametrize(
    ("args", "extra", "serves"),
    [([], "", True), (["--no-serve"], "", False), ([], "enabled = false", False)],
)
def test_the_loop_serves_unless_told_not_to(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    extra: str,
    *,
    serves: bool,
) -> None:
    serve_on(canopy_env, free_port(), extra)
    with overseer_does():
        assert main(["loop", "--dry-run", "--ticks", "1", *args]) == 0
    # No secret: a loop that would serve says so; one told not to says nothing about it.
    assert ("not served" in capsys.readouterr().out) is serves


def test_canopy_secret_makes_one_prints_it_and_rotates_only_when_asked(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["secret"]) == 0
    first = capsys.readouterr()
    value = first.out.strip()
    assert secret.read(secret.path()) == value
    assert f"wrote {secret.path()}" in first.err
    assert main(["secret"]) == 0
    assert capsys.readouterr().out.strip() == value
    assert main(["secret", "--rotate"]) == 0
    assert capsys.readouterr().out.strip() != value
    with in_run(3):
        assert main(["secret"]) == 1
    assert "inside_run" in capsys.readouterr().err


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "8.8.8.8", "canopy.example"])  # noqa: S104
def test_serve_bind_must_be_loopback_or_private(canopy_env: CanopyEnv, bind: str) -> None:
    canopy_env.write_user(user_toml() + f'\n[serve]\nbind = "{bind}"\n')
    with pytest.raises(config.ConfigError, match=r"serve\.bind"):
        config.load(canopy_env.root, canopy_env.user_file)


def test_serve_is_user_only(canopy_env: CanopyEnv) -> None:
    canopy_env.append_shared('\n[serve]\nbind = "10.0.0.5"\n')
    with pytest.raises(config.ConfigError, match="is private"):
        config.load(canopy_env.root, canopy_env.user_file)


def test_a_private_bind_loads(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(user_toml() + '\n[serve]\nbind = "10.0.0.5"\nbase_path = "/canopy"\n')
    loaded = config.load(canopy_env.root, canopy_env.user_file).serve
    assert (loaded.enabled, loaded.bind, loaded.port, loaded.base_path) == (True, "10.0.0.5", 8765, "/canopy")


def test_a_web_reply_is_the_same_submission_only_with_the_same_id(ctx: Context) -> None:
    ref = conversation.parse_ref(KEY)
    conversation.start(ctx.conn, ctx.config, ref, repo=ctx.repo, channel="web")
    one = conversation.reply(ctx.conn, ref, "yes", channel="web", submission="form-aaaa")
    two = conversation.reply(ctx.conn, ref, "yes", channel="web", submission="form-bbbb")
    assert one.new
    assert two.new
    with pytest.raises(conversation.Refused, match="bad_submission"):
        conversation.reply(ctx.conn, ref, "yes", channel="web", submission="short")
