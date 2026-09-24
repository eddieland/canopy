"""The `canopy` command line, built with click (D025)."""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import override

import click

from canopy import attention, config, db, init, logs, procs, resources, tick
from canopy.context import Context, db_path

KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
REASON_RE = re.compile(r"[a-z][a-z0-9_]*")
CURSOR_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}")
PHASES = (
    "ready",
    "running",
    "pushed_no_pr",
    "ci_running",
    "ci_red",
    "changes_requested",
    "green_unreviewed",
    "approved",
    "merged",
    "needs_human",
    "human_replied",
)
KINDS = ("implement", "fix-ci", "resume")
DECIDE_ACTIONS = ("wait", "skip", "done")
MAX_TEXT = 2000


class CliError(click.ClickException):
    """A refusal or failure, reported on stderr, exit 1. Misuse is a click.UsageError instead, exit 2."""


def valid_key(value: str) -> bool:
    """Keys reach branch names, lease holders, paths, and argv (DESIGN §17)."""
    return KEY_RE.fullmatch(value) is not None


def truncate(value: str) -> str:
    """Bound free text the overseer writes to the journal."""
    return value if len(value) <= MAX_TEXT else value[: MAX_TEXT - 3] + "..."


class PatternType(click.ParamType[str, object]):
    """A string that must match a pattern: ticket keys and attention reasons."""

    def __init__(self, name: str, pattern: re.Pattern[str], what: str) -> None:
        """Name the type for help text, and say what `pattern` validates for error messages."""
        self.name = name
        self.pattern = pattern
        self.what = what

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        if not isinstance(value, str) or not self.pattern.fullmatch(value):
            self.fail(f"invalid {self.what} {value!r}: must match {self.pattern.pattern}", param, ctx)
        return value


class CursorType(click.ParamType[tuple[str, str], object]):
    """A `--cursor NAME=ID` pair; the id is later rendered into prompts, so it is kept short and plain."""

    name = "NAME=ID"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> tuple[str, str]:
        cursor_name, sep, cursor_id = str(value).partition("=")
        if not sep or cursor_name not in db.CURSOR_COLUMNS:
            self.fail(f"cursor must be NAME=ID with NAME one of {', '.join(db.CURSOR_COLUMNS)}", param, ctx)
        if not CURSOR_VALUE_RE.fullmatch(cursor_id):
            self.fail(f"invalid cursor id {cursor_id!r}", param, ctx)
        return cursor_name, cursor_id


class TextType(click.ParamType[str, object]):
    """Free text the overseer writes into the journal: stripped, non-empty, bounded."""

    name = "TEXT"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        text = str(value).strip()
        if not text:
            self.fail("must not be empty", param, ctx)
        return truncate(text)


TICKET_KEY = PatternType("KEY", KEY_RE, "ticket key")
REASON = PatternType("REASON", REASON_RE, "reason")


@dataclass(frozen=True)
class Obj:
    """What `main` hands every command through click's context."""

    runner: procs.Runner


def main(argv: Sequence[str] | None = None, runner: procs.Runner | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name. Defaults to `sys.argv[1:]`.
        runner: Runs external processes. Tests may pass a fake; defaults to the real one.

    Returns:
        The process exit code.
    """
    obj = Obj(runner or procs.SubprocessRunner())
    args = list(argv) if argv is not None else sys.argv[1:]
    try:
        result = cli.main(args=args, prog_name="canopy", standalone_mode=False, obj=obj)
    except click.ClickException as e:
        e.show()
        return e.exit_code
    except click.Abort:
        click.echo("Aborted!", err=True)
        return 1
    except (config.ConfigError, db.MigrationError) as e:
        click.echo(f"canopy: {e}", err=True)
        return 2
    return result if isinstance(result, int) else 0


@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="canopy", prog_name="canopy", message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Unattended, local agent loop driven by your issue tracker."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _open(click_ctx: click.Context, *, migrate: bool = True) -> Context:
    """Load config and open the journal. The connection closes when the command finishes."""
    obj = click_ctx.find_object(Obj)
    if obj is None:
        raise RuntimeError("canopy commands run through canopy.cli.main")
    repo_root = config.find_repo_root(Path.cwd())
    cfg = config.load(repo_root)
    # Logs and overseer output live here; they are for the operator only (TRUST_MODEL T2).
    cfg.paths.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    logs.configure(cfg.paths.state_dir)
    conn = db.connect(db_path(cfg))
    click_ctx.call_on_close(conn.close)
    if migrate:
        # The tick migrates under its lock; everything else migrates on open, which is a no-op inside a tick.
        db.migrate(conn, resources.migrations_dir())
    return Context(config=cfg, repo_root=repo_root, conn=conn, runner=obj.runner)


def _optional_tick(ctx: Context) -> sqlite3.Row | None:
    """Return the tick this command runs inside, named by CANOPY_TICK_ID, or None outside a tick."""
    raw = os.environ.get(tick.TICK_ID_ENV)
    if not raw:
        return None
    row = db.get_tick(ctx.conn, int(raw)) if raw.isdigit() else None
    if row is None or row["status"] != "running":
        raise CliError(f"{tick.TICK_ID_ENV}={raw} does not name a running tick")
    return row


def _require_tick(ctx: Context) -> sqlite3.Row:
    """Return the tick this command runs inside; refuse outside a tick."""
    row = _optional_tick(ctx)
    if row is None:
        raise CliError(f"no tick is running ({tick.TICK_ID_ENV} is not set); this command runs inside a tick")
    return row


# Commands


@cli.command("init")
@click.option("--provider", help="Tracker provider for a new canopy.toml (jira, github, linear, ...).")
def cmd_init(provider: str | None) -> int:
    """Set up canopy for this repository and this user."""
    repo_root = config.find_repo_root(Path.cwd())
    if provider is None and not (repo_root / config.REPO_FILE_NAME).exists():
        if not sys.stdin.isatty():
            raise click.UsageError("the repository has no canopy.toml; pass --provider (jira, github, linear, ...)")
        answer: str = click.prompt("Tracker provider for this repository (jira, github, linear, ...)")
        provider = answer.strip().lower()
    if provider is not None and not init.valid_provider(provider):
        raise click.UsageError(f"invalid provider {provider!r}: use a short lowercase name such as jira or github")

    user_file = config.user_config_path()
    report = init.run(repo_root, user_file, provider)
    for path in report.written:
        click.echo(f"wrote {path}")
    for path in report.kept:
        click.echo(f"kept  {path}")
    if report.label is not None:
        click.echo(f"\nYour queue label is {report.label!r}. Add it to a ticket to hand the ticket to canopy.")
    if (repo_root / config.REPO_FILE_NAME) in report.written:
        click.echo(f"Edit tracker.query in {repo_root / config.REPO_FILE_NAME} before the first tick.")
    try:
        prefix = config.load(repo_root, user_file).trust.branch_prefix
    except config.ConfigError:
        prefix = "agent/"
    click.echo()
    click.echo(init.BRANCH_PROTECTION.format(prefix=prefix), nl=False)
    return 0


@cli.command("tick")
@click.option("--dry-run", is_flag=True, help="Run the overseer, but dispatch nothing.")
@click.pass_context
def cmd_tick(click_ctx: click.Context, *, dry_run: bool) -> int:
    """Run one tick of the loop."""
    if not dry_run:
        raise click.UsageError("canopy tick runs only with --dry-run until dispatch is implemented (ROADMAP M2)")
    ctx = _open(click_ctx, migrate=False)
    outcome = tick.run(ctx, dry_run=True)
    label = f"tick {outcome.tick_id}" if outcome.tick_id is not None else "tick"
    click.echo(f"{label}: {outcome.status}: {outcome.summary}")
    return 0 if outcome.status in ("ok", "lock_busy") else 1


@cli.command("status")
@click.pass_context
def cmd_status(click_ctx: click.Context) -> int:
    """Print the attention list and running workers."""
    ctx = _open(click_ctx)
    last = db.last_tick(ctx.conn)
    if last is None:
        click.echo("No ticks yet.")
    else:
        dry = " (dry run)" if last["dry_run"] else ""
        click.echo(f"Last tick: {last['id']} {last['status']}{dry}, started {_age(last['started_at'])} ago")
        if last["summary"]:
            click.echo(f"  {last['summary']}")

    items = attention.current(ctx.conn)
    click.echo(f"\nAttention ({len(items)}):")
    for group in sorted({i.reason for i in items}):
        click.echo(f"  {group}")
        for item in (i for i in items if i.reason == group):
            click.echo(f"    {item.ticket_key}  {_age(item.since)}  {item.detail}")
    if not items:
        click.echo("  nothing needs you")

    running = db.running_runs(ctx.conn)
    click.echo(f"\nRunning workers ({len(running)}/{ctx.config.capacity.max_workers}):")
    for r in running:
        click.echo(f"  {r['ticket_key']}  {r['kind']}  {_age(r['started_at'])}  {r['slot_path']}")
    if not running:
        click.echo("  none")
    return 0


@cli.command("dispatch")
@click.argument("key", type=TICKET_KEY)
@click.option("--kind", required=True, type=click.Choice(KINDS))
@click.option("--base", metavar="BRANCH", help="Start from this branch instead of the default.")
@click.option("--context", "context_file", type=click.Path(path_type=Path), help="File with context for the worker.")
@click.pass_context
def cmd_dispatch(click_ctx: click.Context, key: str, kind: str, base: str | None, context_file: Path | None) -> int:
    """Start a worker on a ticket (overseer only)."""
    ctx = _open(click_ctx)
    current = _require_tick(ctx)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    extras = [f"base={base}" if base else "", f"context={context_file}" if context_file else ""]
    detail = "; ".join(e for e in extras if e)
    if current["dry_run"]:
        rationale = "dry run: not dispatched" + (f" ({detail})" if detail else "")
        db.record_decision(ctx.conn, current["id"], key, f"dispatch:{kind}", rationale)
        logs.for_tick(current["id"]).info("dry-run dispatch recorded", extra={"ticket": key, "kind": kind})
        click.echo(f"dry run: recorded dispatch {kind} for {key}; nothing was started")
        return 0
    db.record_decision(ctx.conn, current["id"], key, "refused:not_implemented", "dispatch arrives in ROADMAP M2")
    raise CliError("dispatch is not implemented yet (ROADMAP M2); the refusal was recorded")


@cli.command("decide")
# click has no optional positional before a required one, so `[KEY] ACTION` is parsed by hand.
@click.argument("words", nargs=-1, required=True, metavar="[KEY] ACTION")
@click.option("--rationale", required=True, type=TextType())
@click.pass_context
def cmd_decide(click_ctx: click.Context, words: tuple[str, ...], rationale: str) -> int:
    """Record a decision (overseer only).

    ACTION is wait, skip, or done. KEY may be omitted only for a tick-wide skip.
    """
    if len(words) > 2:  # noqa: PLR2004
        raise click.UsageError(f"expected [KEY] ACTION, got {len(words)} arguments", click_ctx)
    key, action = (None, words[0]) if len(words) == 1 else words
    if action not in DECIDE_ACTIONS:
        raise click.UsageError(f"invalid action {action!r}: choose from {', '.join(DECIDE_ACTIONS)}", click_ctx)
    if key is not None and not valid_key(key):
        raise click.UsageError(f"invalid ticket key {key!r}: must match {KEY_RE.pattern}", click_ctx)
    if key is None and action != "skip":
        raise click.UsageError(f"{action!r} needs a ticket key; only a tick-wide 'skip' may omit it", click_ctx)
    ctx = _open(click_ctx)
    current = _require_tick(ctx)
    if key is not None:
        db.touch_ticket(ctx.conn, key, ctx.repo)
    db.record_decision(ctx.conn, current["id"], key, action, rationale)
    click.echo(f"recorded {action} for {key or 'this tick'}")
    return 0


@cli.command("attention")
@click.argument("key", type=TICKET_KEY)
@click.argument("reason", type=REASON)
@click.option("--detail", required=True, type=TextType())
@click.pass_context
def cmd_attention(click_ctx: click.Context, key: str, reason: str, detail: str) -> int:
    """Record an attention item (overseer only)."""
    ctx = _open(click_ctx)
    current = _require_tick(ctx)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    db.record_decision(ctx.conn, current["id"], key, f"{attention.ACTION_PREFIX}{reason}", detail)
    click.echo(f"recorded attention {reason} for {key}")
    return 0


@cli.group("ticket")
def ticket_group() -> None:
    """Update the journal's view of a ticket (overseer only)."""


@ticket_group.command("set")
@click.argument("key", type=TICKET_KEY)
@click.option("--phase", type=click.Choice(PHASES))
@click.option("--cursor", "cursor_pairs", type=CursorType(), multiple=True)
@click.option("--done", is_flag=True)
@click.pass_context
def cmd_ticket_set(
    click_ctx: click.Context,
    *,
    key: str,
    phase: str | None,
    cursor_pairs: tuple[tuple[str, str], ...],
    done: bool,
) -> int:
    """Record a ticket's phase, cursors, or done flag."""
    ctx = _open(click_ctx)
    current = _optional_tick(ctx)
    cursors = dict(cursor_pairs)
    # A dry run must not advance cursors: the first live tick would then miss everything the dry runs saw.
    skipped = bool(cursors) and current is not None and bool(current["dry_run"])
    db.set_ticket(ctx.conn, key, ctx.repo, phase=phase, cursors={} if skipped else cursors, done=done)
    note = "; dry run, cursors not advanced" if skipped else ""
    click.echo(f"updated {key}{note}")
    return 0


def _age(timestamp: str) -> str:
    then = datetime.fromisoformat(timestamp)
    seconds = max(0, int((datetime.now(UTC) - then).total_seconds()))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"
