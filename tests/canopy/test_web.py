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
from fastapi.testclient import TestClient

from canopy.cli.main import main
from canopy.core import config, conversation, db
from canopy.core.context import Context
from canopy.infra import resources
from canopy.loop import repeat, web
from canopy.serve import secret, views
from canopy.serve.app import create_app
from canopy.serve.auth import Sessions
from canopy.serve.options import ServeOptions
from tests.canopy.test_loop import FakeTime, console, context, overseer_does
from tests.conftest import CanopyEnv, user_toml

KEY = "PROJ-1"
SECRET = "w" * 43
ORIGIN = "http://127.0.0.1:8765"


@pytest.fixture
def ctx(canopy_env: CanopyEnv) -> Context:
    found = context(canopy_env)
    db.migrate(found.conn, resources.migrations_dir())
    return found


def signed_in_client(ctx: Context) -> tuple[TestClient, dict[str, str]]:
    """A browser signed in to a server over `ctx`'s journal, as the loop builds it, and the headers a write needs."""
    options = ServeOptions(port=8765)
    sessions = Sessions(SECRET, port=options.port, base_path="", hosts=options.hosts)
    c = TestClient(create_app(options, web.backend(ctx), sessions), base_url=ORIGIN)
    token = c.post("/api/session", json={"secret": SECRET}).json()["token"]
    return c, {"x-canopy-token": token, "origin": ORIGIN}


def refused(response: httpx2.Response) -> str:
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    return f"{detail['guard']}: {detail['reason']}"


def running_run(ctx: Context, key: str, *, private: bool = True) -> int:
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    run_id = db.insert_run(
        ctx.conn,
        tick_id=tick_id,
        key=key,
        kind="implement",
        branch=f"agent/{key}-work",
        slots=[],
        runs_dir=ctx.state_dir / "runs",
        private=private,
    )
    db.finish_tick(ctx.conn, tick_id, "ok", "test")
    return run_id


def test_meta_carries_the_trackers_ticket_url_when_set(canopy_env: CanopyEnv, ctx: Context) -> None:
    c, _ = signed_in_client(ctx)
    assert c.get("/api/meta").json()["ticket_url"] is None

    template = "https://jira.example/browse/{key}"
    canopy_env.write_shared(canopy_env.shared_file.read_text() + f'ticket_url = "{template}"\n')
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
    record = conversation.start_of(ctx.conn, KEY)
    assert record is not None
    assert (record["status"], record["channel"]) == ("started", "web")
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
    record = conversation.start_of(ctx.conn, KEY)
    assert record is not None
    assert (record["status"], record["channel"]) == ("stopped", "web")


def test_stop_now_from_the_web_ends_the_run_as_canopy_stop_now_does(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post(f"/api/tickets/{KEY}/start", headers=headers).status_code == 200
    run_id = running_run(ctx, KEY)

    graceful = c.post(f"/api/tickets/{KEY}/stop", json={"now": False}, headers=headers).json()
    assert graceful == {"already": False, "running_run": run_id, "ended": False}
    run = db.get_run(ctx.conn, run_id)
    assert run is not None
    assert run["status"] == "running"

    now = c.post(f"/api/tickets/{KEY}/stop", json={"now": True}, headers=headers).json()
    assert now == {"already": True, "running_run": run_id, "ended": True}
    run = db.get_run(ctx.conn, run_id)
    assert run is not None
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
    ticket = db.get_ticket(ctx.conn, KEY)
    assert ticket is not None
    assert (ticket["branch"], ticket["phase"], ticket["forgotten_run_id"]) == (None, None, run_id)
    assert db.units(ctx.conn, KEY) == []
    assert db.get_run(ctx.conn, run_id) is not None


def test_the_pages_read_what_canopy_show_and_status_print(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    assert c.post(f"/api/tickets/{KEY}/start", headers=headers).status_code == 200
    run_id = running_run(ctx, KEY)
    run = db.get_run(ctx.conn, run_id)
    assert run is not None
    result = {"status": "blocked", "summary": "half done\x1b[2J", "question": "Red <b>or</b> blue?"}
    assert conversation.close_run(ctx.conn, ctx.config, run, "blocked", json.dumps(result))
    tick_id = db.start_tick(ctx.conn, dry_run=False)
    db.record_decision(ctx.conn, tick_id, "PROJ-9", "attention:needs_reviewer", "https://example.test/pr/9")
    db.finish_tick(ctx.conn, tick_id, "ok", "test")

    [item] = c.get("/api/attention").json()
    assert (item["ticket_key"], item["reason"], item["detail"]) == (
        "PROJ-9",
        "needs_reviewer",
        "https://example.test/pr/9",
    )

    [listed] = c.get("/api/runs").json()
    assert (listed["id"], listed["state"], listed["private"]) == (run_id, "blocked", True)
    assert listed["summary"] == "half done [2J"  # control characters dropped

    assert [t["key"] for t in c.get("/api/tickets").json()] == [KEY]
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


def test_spend_is_what_the_runs_and_ticks_that_started_in_the_last_day_cost(ctx: Context) -> None:
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    backend = dataclasses.replace(web.backend(ctx), clock=lambda: now)
    assert views.spend(backend, ctx).cost_usd is None  # nothing reported yet

    def started(table: str, row_id: int, hours_ago: float, cost: float | None) -> None:
        at = db.format_time(now - timedelta(hours=hours_ago))
        ctx.conn.execute(f"UPDATE {table} SET started_at = ?, cost_usd = ? WHERE id = ?", (at, cost, row_id))  # noqa: S608

    started("runs", running_run(ctx, KEY), 2, 1.25)
    started("runs", running_run(ctx, "PROJ-2"), 25, 9.0)  # before the window
    started("runs", running_run(ctx, "PROJ-3"), 1, None)  # reported nothing
    started("ticks", db.start_tick(ctx.conn, dry_run=False), 23.5, 0.5)

    spend = views.spend(backend, ctx)
    assert (spend.hours, spend.since, spend.cost_usd) == (24, now - timedelta(hours=24), pytest.approx(1.75))


def test_the_last_tick_is_the_latest_row_with_its_status_and_cost(ctx: Context) -> None:
    c, _ = signed_in_client(ctx)
    assert c.get("/api/tick").json() == {"tick": None, "acknowledged": None}
    db.start_tick(ctx.conn, dry_run=False)
    later = db.start_tick(ctx.conn, dry_run=True)
    db.finish_tick(ctx.conn, later, "ok", "nothing to do\x1b[2J")
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
    db.finish_tick(ctx.conn, first, "ok", "read nothing")
    assert c.get("/api/tick").json()["acknowledged"] == 0

    reply = {"body": "blue", "submission": "form-ack-1"}
    replied = c.post(f"/api/tickets/{KEY}/replies", json=reply, headers=headers).json()["message_id"]
    # A tick that read the reply but did not close `ok` acknowledges nothing: the attention list is still the last's.
    failed = db.start_tick(ctx.conn, dry_run=False)
    db.set_tick_read(ctx.conn, failed)
    db.finish_tick(ctx.conn, failed, "overseer_failed", "exit 1")
    last = c.get("/api/tick").json()
    assert (last["tick"]["id"], last["acknowledged"]) == (failed, 0)

    read = db.start_tick(ctx.conn, dry_run=False)
    db.set_tick_read(ctx.conn, read)
    assert c.get("/api/tick").json()["acknowledged"] == 0  # still running
    db.finish_tick(ctx.conn, read, "ok", "resumed")
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
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = free_port()
    serve_on(canopy_env, port)
    secret.create(secret.path(), rotate=False)
    key = secret.read(secret.path())
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    conversation.start(ctx.conn, ctx.config, conversation.parse_ref(KEY), repo=ctx.repo, channel="cli")
    overseer_does(monkeypatch)
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
    assert sum(time_.slept) == pytest.approx(repeat.WAKE_MIN_SECONDS)
    text = out.getvalue()
    assert f"web UI      {base}/" in text
    # Stopping the loop stopped the server.
    with pytest.raises(httpx2.TransportError):
        httpx2.get(f"{base}/api/session", timeout=1)


def test_without_a_secret_the_loop_serves_nothing_and_says_how_to_make_one(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = free_port()
    serve_on(canopy_env, port)
    overseer_does(monkeypatch)
    term, out = console()
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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    extra: str,
    *,
    serves: bool,
) -> None:
    serve_on(canopy_env, free_port(), extra)
    overseer_does(monkeypatch)
    assert main(["loop", "--dry-run", "--ticks", "1", *args]) == 0
    # No secret: a loop that would serve says so; one told not to says nothing about it.
    assert ("not served" in capsys.readouterr().out) is serves


def test_canopy_secret_makes_one_prints_it_and_rotates_only_when_asked(
    canopy_env: CanopyEnv, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    monkeypatch.setenv("CANOPY_RUN_ID", "3")
    assert main(["secret"]) == 1
    assert "inside_run" in capsys.readouterr().err


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "8.8.8.8", "canopy.example"])  # noqa: S104
def test_serve_bind_must_be_loopback_or_private(canopy_env: CanopyEnv, bind: str) -> None:
    canopy_env.write_user(user_toml() + f'\n[serve]\nbind = "{bind}"\n')
    with pytest.raises(config.ConfigError, match=r"serve\.bind"):
        config.load(canopy_env.root, canopy_env.user_file)


def test_serve_is_user_only(canopy_env: CanopyEnv) -> None:
    canopy_env.write_shared(canopy_env.shared_file.read_text() + '\n[serve]\nbind = "10.0.0.5"\n')
    with pytest.raises(config.ConfigError, match="user-only"):
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
