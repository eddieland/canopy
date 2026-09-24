"""The `canopy` command line."""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from canopy import attention, config, db, init, logs, procs, resources, tick
from canopy.context import Context, db_path

KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
REASON_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CURSOR_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$")
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


class CliError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def ticket_key(value: str) -> str:
    """argparse type for ticket keys. Keys reach branch names, lease holders, paths, and argv (DESIGN §17)."""
    if not KEY_RE.match(value):
        raise argparse.ArgumentTypeError(f"invalid ticket key {value!r}: must match {KEY_RE.pattern}")
    return value


def cursor(value: str) -> tuple[str, str]:
    name, sep, cursor_id = value.partition("=")
    if not sep or name not in db.CURSOR_COLUMNS:
        raise argparse.ArgumentTypeError(f"cursor must be NAME=ID with NAME one of {', '.join(db.CURSOR_COLUMNS)}")
    if not CURSOR_VALUE_RE.match(cursor_id):
        raise argparse.ArgumentTypeError(f"invalid cursor id {cursor_id!r}")
    return name, cursor_id


def reason(value: str) -> str:
    if not REASON_RE.match(value):
        raise argparse.ArgumentTypeError(f"invalid reason {value!r}: must match {REASON_RE.pattern}")
    return value


def text(value: str) -> str:
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("must not be empty")
    return value if len(value) <= MAX_TEXT else value[: MAX_TEXT - 3] + "..."


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="canopy",
        description="Unattended, local agent loop driven by your issue tracker.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('canopy')}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("init", help="set up canopy for this repository and this user")
    p.add_argument("--provider", help="tracker provider for a new canopy.toml (jira, github, linear, ...)")

    p = sub.add_parser("tick", help="run one tick of the loop")
    p.add_argument("--dry-run", action="store_true", help="run the overseer, but dispatch nothing")

    sub.add_parser("status", help="print the attention list and running workers")

    p = sub.add_parser("dispatch", help="start a worker on a ticket (overseer only)")
    p.add_argument("key", type=ticket_key, metavar="KEY")
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--base", metavar="BRANCH", help="start from this branch instead of the default")
    p.add_argument("--context", type=Path, metavar="FILE", help="file with context for the worker")

    p = sub.add_parser("decide", help="record a decision (overseer only)")
    p.add_argument("key", type=ticket_key, nargs="?", metavar="KEY", help="omit only for a tick-wide skip")
    p.add_argument("action", choices=DECIDE_ACTIONS, metavar="ACTION", help=" | ".join(DECIDE_ACTIONS))
    p.add_argument("--rationale", required=True, type=text)

    p = sub.add_parser("attention", help="record an attention item (overseer only)")
    p.add_argument("key", type=ticket_key, metavar="KEY")
    p.add_argument("reason", type=reason, metavar="REASON")
    p.add_argument("--detail", required=True, type=text)

    p = sub.add_parser("ticket", help="update the journal's view of a ticket (overseer only)")
    ticket_sub = p.add_subparsers(dest="ticket_command", metavar="SUBCOMMAND", required=True)
    s = ticket_sub.add_parser("set", help="record phase, cursors, or done")
    s.add_argument("key", type=ticket_key, metavar="KEY")
    s.add_argument("--phase", choices=PHASES)
    s.add_argument("--cursor", type=cursor, action="append", default=[], metavar="NAME=ID")
    s.add_argument("--done", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, runner: procs.Runner | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name. Defaults to `sys.argv[1:]`.
        runner: Runs external processes. Tests may pass a fake; defaults to the real one.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return _dispatch_command(args, runner or procs.SubprocessRunner())
    except CliError as e:
        print(f"canopy: {e}", file=sys.stderr)
        return e.code
    except (config.ConfigError, db.MigrationError) as e:
        print(f"canopy: {e}", file=sys.stderr)
        return 2


def _dispatch_command(args: argparse.Namespace, runner: procs.Runner) -> int:
    command: str = args.command
    if command == "init":
        return cmd_init(args)
    ctx = _open(runner)
    try:
        if command == "tick":
            return cmd_tick(ctx, args)
        # The tick migrates under its lock; everything else migrates on open, which is a no-op inside a tick.
        db.migrate(ctx.conn, resources.migrations_dir())
        handlers = {
            "status": cmd_status,
            "dispatch": cmd_dispatch,
            "decide": cmd_decide,
            "attention": cmd_attention,
            "ticket": cmd_ticket_set,
        }
        return handlers[command](ctx, args)
    finally:
        ctx.conn.close()


def _open(runner: procs.Runner) -> Context:
    repo_root = config.find_repo_root(Path.cwd())
    cfg = config.load(repo_root)
    # Logs and overseer output live here; they are for the operator only (TRUST_MODEL T2).
    cfg.paths.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    logs.configure(cfg.paths.state_dir)
    return Context(config=cfg, repo_root=repo_root, conn=db.connect(db_path(cfg)), runner=runner)


def _current_tick(ctx: Context, *, required: bool = True) -> sqlite3.Row | None:
    """The tick this command runs inside, named by CANOPY_TICK_ID, which the tick sets for the overseer."""
    raw = os.environ.get(tick.TICK_ID_ENV)
    if not raw:
        if required:
            raise CliError(f"no tick is running ({tick.TICK_ID_ENV} is not set); this command runs inside a tick")
        return None
    row = db.get_tick(ctx.conn, int(raw)) if raw.isdigit() else None
    if row is None or row["status"] != "running":
        raise CliError(f"{tick.TICK_ID_ENV}={raw} does not name a running tick")
    return row


# Commands


def cmd_init(args: argparse.Namespace) -> int:
    repo_root = config.find_repo_root(Path.cwd())
    provider: str | None = args.provider
    if provider is None and not (repo_root / config.REPO_FILE_NAME).exists():
        if not sys.stdin.isatty():
            raise CliError("the repository has no canopy.toml; pass --provider (jira, github, linear, ...)", 2)
        provider = input("Tracker provider for this repository (jira, github, linear, ...): ").strip().lower()
    if provider is not None and not init.PROVIDER_RE.match(provider):
        raise CliError(f"invalid provider {provider!r}: use a short lowercase name such as jira or github", 2)

    user_file = config.user_config_path()
    report = init.run(repo_root, user_file, provider)
    for path in report.written:
        print(f"wrote {path}")
    for path in report.kept:
        print(f"kept  {path}")
    if report.label is not None:
        print(f"\nYour queue label is {report.label!r}. Add it to a ticket to hand the ticket to canopy.")
    if (repo_root / config.REPO_FILE_NAME) in report.written:
        print(f"Edit tracker.query in {repo_root / config.REPO_FILE_NAME} before the first tick.")
    try:
        prefix = config.load(repo_root, user_file).trust.branch_prefix
    except config.ConfigError:
        prefix = "agent/"
    print()
    print(init.BRANCH_PROTECTION.format(prefix=prefix), end="")
    return 0


def cmd_tick(ctx: Context, args: argparse.Namespace) -> int:
    if not args.dry_run:
        raise CliError("canopy tick runs only with --dry-run until dispatch is implemented (ROADMAP M2)", 2)
    outcome = tick.run(ctx, dry_run=True)
    label = f"tick {outcome.tick_id}" if outcome.tick_id is not None else "tick"
    print(f"{label}: {outcome.status}: {outcome.summary}")
    return 0 if outcome.status in ("ok", "lock_busy") else 1


def cmd_status(ctx: Context, args: argparse.Namespace) -> int:
    last = db.last_tick(ctx.conn)
    if last is None:
        print("No ticks yet.")
    else:
        dry = " (dry run)" if last["dry_run"] else ""
        print(f"Last tick: {last['id']} {last['status']}{dry}, started {_age(last['started_at'])} ago")
        if last["summary"]:
            print(f"  {last['summary']}")

    items = attention.current(ctx.conn)
    print(f"\nAttention ({len(items)}):")
    for group in sorted({i.reason for i in items}):
        print(f"  {group}")
        for item in (i for i in items if i.reason == group):
            print(f"    {item.ticket_key}  {_age(item.since)}  {item.detail}")
    if not items:
        print("  nothing needs you")

    running = db.running_runs(ctx.conn)
    print(f"\nRunning workers ({len(running)}/{ctx.config.max_workers}):")
    for r in running:
        print(f"  {r['ticket_key']}  {r['kind']}  {_age(r['started_at'])}  {r['slot_path']}")
    if not running:
        print("  none")
    return 0


def cmd_dispatch(ctx: Context, args: argparse.Namespace) -> int:
    current = _current_tick(ctx)
    assert current is not None
    key: str = args.key
    kind: str = args.kind
    db.touch_ticket(ctx.conn, key, ctx.repo)
    extras = [f"base={args.base}" if args.base else "", f"context={args.context}" if args.context else ""]
    detail = "; ".join(e for e in extras if e)
    if current["dry_run"]:
        rationale = "dry run: not dispatched" + (f" ({detail})" if detail else "")
        db.record_decision(ctx.conn, current["id"], key, f"dispatch:{kind}", rationale)
        logs.for_tick(current["id"]).info("dry-run dispatch recorded", extra={"ticket": key, "kind": kind})
        print(f"dry run: recorded dispatch {kind} for {key}; nothing was started")
        return 0
    db.record_decision(ctx.conn, current["id"], key, "refused:not_implemented", "dispatch arrives in ROADMAP M2")
    raise CliError("dispatch is not implemented yet (ROADMAP M2); the refusal was recorded")


def cmd_decide(ctx: Context, args: argparse.Namespace) -> int:
    current = _current_tick(ctx)
    assert current is not None
    key: str | None = args.key
    action: str = args.action
    if key is None and action != "skip":
        raise CliError(f"{action!r} needs a ticket key; only a tick-wide 'skip' may omit it", 2)
    if key is not None:
        db.touch_ticket(ctx.conn, key, ctx.repo)
    db.record_decision(ctx.conn, current["id"], key, action, args.rationale)
    print(f"recorded {action} for {key or 'this tick'}")
    return 0


def cmd_attention(ctx: Context, args: argparse.Namespace) -> int:
    current = _current_tick(ctx)
    assert current is not None
    key: str = args.key
    db.touch_ticket(ctx.conn, key, ctx.repo)
    db.record_decision(ctx.conn, current["id"], key, f"{attention.ACTION_PREFIX}{args.reason}", args.detail)
    print(f"recorded attention {args.reason} for {key}")
    return 0


def cmd_ticket_set(ctx: Context, args: argparse.Namespace) -> int:
    current = _current_tick(ctx, required=False)
    cursors = dict(args.cursor)
    # A dry run must not advance cursors: the first live tick would then miss everything the dry runs saw.
    skipped = bool(cursors) and current is not None and bool(current["dry_run"])
    db.set_ticket(ctx.conn, args.key, ctx.repo, phase=args.phase, cursors={} if skipped else cursors, done=args.done)
    note = "; dry run, cursors not advanced" if skipped else ""
    print(f"updated {args.key}{note}")
    return 0


def _age(timestamp: str) -> str:
    then = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    seconds = max(0, int((datetime.now(UTC) - then).total_seconds()))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"
