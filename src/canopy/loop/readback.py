"""canopy's read-back of the journal as text: a tick's decisions, a run, and a chore (DESIGN §27).

`canopy decisions` and `canopy show run:ID` and `chore:NAME` print these, and an agent reads them through tools of the
same names, `canopy_reports_decisions`, `show-run`, and `show-chore`, which `canopy _mcp --reports` serves beside the
reports in `core.reports`. Both build a request here and call its function, so a tool and its command take the same
bounds and say the same text. None of them writes. A ticket's page is not among them: it holds the ticket's
conversation, which only the operator reads whole.

What agents and the tracker wrote, a run's messages and a chore's findings, is printed with every character that hides
text named, as the commands print it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from pydantic import AfterValidator, Field, StrictInt, StrictStr

from canopy.core import (
    cards,
    checklist_answers,
    chore_result,
    chore_view,
    config,
    contract,
    conversation,
    db,
    reports,
    review_diff,
    run_changes,
    run_inbox,
)
from canopy.core.vocab import Decider, RunStatus
from canopy.infra.text import one_line
from canopy.loop import attention
from canopy.loop.render import chore_line, named, prs_of, result_of, spent

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from canopy.core import records
    from canopy.core.context import Context


#: How many characters of a commit a range names.
_SHORT = 12


def _chore_name(value: str) -> str:
    if not config.CHORE_NAME_RE.fullmatch(value):
        raise ValueError(f"invalid chore name {value!r}: must match {config.CHORE_NAME_RE.pattern}")
    return value


class Decisions(reports.Request):
    """`decisions`: one tick's decisions, of one ticket if asked; the latest tick's unless one is named."""

    #: The tick, by its id; the latest when left out.
    tick: Annotated[
        StrictInt | None,
        Field(ge=1, description="The tick, by its id; the latest tick when left out."),
    ] = None
    #: Only this ticket's decisions.
    ticket: Annotated[
        Annotated[StrictStr, AfterValidator(reports.ticket_key)] | None,
        Field(max_length=100, description="Only the decisions about this ticket, by its key."),
    ] = None


class ShowRun(reports.Request):
    """`show-run`: one worker or plan run, its slots, PRs, cost, and messages."""

    #: The run, by its id.
    run: Annotated[StrictInt, Field(ge=1, description="The run, by its id: `run:ID` names it elsewhere.")]


class ShowChore(reports.Request):
    """`show-chore`: one chore's state, its latest run, its open findings, and the operator's notes to it."""

    #: The chore, by its name.
    name: Annotated[
        StrictStr,
        AfterValidator(_chore_name),
        Field(description="The chore, by its name: `chore:NAME` names it elsewhere."),
    ]


def read_decisions(ctx: Context, request: Decisions) -> str:
    """Print a tick's decisions, as `canopy decisions` prints them.

    Returns:
        The tick's line and its decisions, or a line saying there is no tick yet.

    Raises:
        reports.Refused: The tick named is not in the journal.
    """
    row = db.last_tick(ctx.conn) if request.tick is None else db.get_tick(ctx.conn, request.tick)
    if row is None:
        if request.tick is not None:
            raise reports.Refused(f"no tick {request.tick}")
        return "No ticks yet."
    dry = " (dry run)" if row.dry_run else ""
    started = f"started {row.started_at} ({attention.age(row.started_at)} ago)"
    ran_on = f" on canopy {row.canopy_version}" if row.canopy_version else ""
    lines = [f"Tick {row.id}: {row.status}{dry}, {started}{ran_on}"]
    if row.summary:
        lines.append(f"  {row.summary}")
    if row.session_id or row.cost_usd is not None:
        session = f"session {row.session_id}" if row.session_id else "no session reported"
        lines.append(f"  overseer {session}{spent(row)}")
    output = ctx.state_dir / "ticks" / f"{row.id}.log"
    if output.exists():
        lines.append(f"  overseer output: {output}")
    rows = db.decisions_for_tick(ctx.conn, row.id)
    if request.ticket is not None:
        rows = [decision for decision in rows if decision.ticket_key == request.ticket]
    lines.append(f"\nDecisions ({len(rows)}):")
    keys = [attention.decided_about(d) for d in rows]
    key_width = max((len(k) for k in keys), default=0)
    action_width = max((len(d.action) for d in rows), default=0)
    for key, d in zip(keys, rows, strict=True):
        rationale = " ".join(d.rationale.split())
        # Who made it (TRUST_MODEL T5): the overseer's are most, so only the harness's are marked (DESIGN §37).
        by = "[harness] " if d.decider is Decider.HARNESS else ""
        lines.append(f"  {key:<{key_width}}  {d.action:<{action_width}}  {by}{rationale}")
    if not rows:
        lines.append(f"  none for ticket {request.ticket}" if request.ticket is not None else "  none")
    return "\n".join(lines)


def read_run(ctx: Context, request: ShowRun, *, operator: bool = False) -> str:
    """Print a run, as `canopy show run:ID` prints it, with what is the operator's alone when `operator` says so.

    A run's progress is the operator's alone (DESIGN §41), and so are its commits' subjects, a worker's text no agent
    is given (§45): the report a chore's agent reads leaves them out.

    Returns:
        The run's lines and its messages.

    Raises:
        reports.Refused: The run is not in the journal.
    """
    run_id = request.run
    run = db.get_run(ctx.conn, run_id)
    if run is None:
        raise reports.Refused(f"no run {run_id}")
    private = ", private" if run["private"] else ""
    lines = [
        f"run:{run_id}: {run['kind']} of {named(run['ticket_key'], run['ticket_title'])}{private}, {run['status']}",
        f"  started {run['started_at']}" + (f", ended {run['ended_at']}" if run["ended_at"] else ""),
    ]
    if run["branch"]:
        lines.append(f"  branch {run['branch']}")
    lines.extend(f"  {s.repo}  slot {s.slot_path}, from {s.base_branch}" for s in db.run_slots(ctx.conn, run_id))
    result = result_of(run)
    lines.extend(f"  PR {pr}" for pr in prs_of(result))
    said = one_line(str(result.get("harness") or ""))
    if said:
        lines.append(f"  harness: {said}")
    session = f"session {run['session_id']}" if run["session_id"] else "no session reported"
    lines.extend([f"  {session}{spent(run)}", f"  log {run['log_path']}"])
    pushed = checklist_answers.pushes_of(ctx.conn, run_id)
    answered = checklist_lines(checklist_answers.of_run(ctx.conn, run_id), pushed, log_path=str(run["log_path"]))
    if answered:
        lines.extend(["\nChecklist:", *(f"  {line}" for line in answered)])
    changed = change_lines(
        run_changes.of_run(ctx.conn, run_id),
        log_path=str(run["log_path"]),
        commits=run_changes.commits_of(ctx.conn, run_id) if operator else None,
    )
    if changed:
        lines.extend(["\nChanged:", *(f"  {line}" for line in changed)])
    # Its agent's progress, while it runs and its last once it ends (DESIGN §41).
    running = run["status"] == RunStatus.RUNNING
    standing = cards.of(run)
    if operator and (standing.card is not None or running):
        lines.extend(
            cards.lines(
                standing,
                started_at=str(run["started_at"]),
                running=running,
                timeout_minutes=ctx.config.runtime.worker_timeout_minutes,
                ref=f"run:{run_id}",
            ),
        )
    # The operator's messages to it while it ran, and when its agent fetched each (DESIGN §44): the operator's alone.
    sent = run_inbox.sent_to(ctx.conn, "runs", run_id) if operator else []
    if sent:
        lines.extend([f"\nYour messages to it ({len(sent)}):", *run_inbox.show_lines(sent, running=running)])
    messages = db.run_messages(ctx.conn, run_id)
    if messages:
        lines.append("\nMessages:")
    for m in messages:
        lines.extend(message_lines(m))
    return "\n".join(lines)


def checklist_lines(
    answers: Sequence[records.ChecklistAnswer],
    pushes: Sequence[records.ChecklistPush] = (),
    *,
    log_path: str = "",
) -> list[str]:
    """What a run answered of its repositories' checklists (DESIGN §42), an item a line; none for a run given no list.

    `canopy show run:ID` prints them under a heading, and `canopy show task:N` under each of its runs. A `held` item's
    reason is the worker's text, printed under it, indented, and made printable as a message is. Then each push the run
    made after being shown a list, with where its diff is kept beside the run's log, `log_path`.

    Returns:
        The lines, unindented, each item's repository, id, and answer, then each push's repository and commits.
    """
    lines: list[str] = []
    for a in answers:
        lines.append(f"{a.repo}  {a.item}  {a.answer}")
        lines.extend(f"  {line}" for line in conversation.printable(a.reason or "").splitlines())
    for p in pushes:
        diff = checklist_answers.diff_path(log_path, p.repo, p.shown_sha)
        lines.append(f"{p.repo}  pushed {p.shown_sha[:12]}..{p.pushed_sha[:12]} after the list, diff {diff}")
    return lines


def change_lines(
    changes: Sequence[records.RunChange],
    *,
    log_path: str,
    commits: Mapping[str, Sequence[records.RunCommit]] | None = None,
) -> list[str]:
    """What a run changed in each repository (DESIGN §45): its range in short commits, and where its diffs are kept.

    `canopy show run:ID` prints them under a heading, and `canopy show task:N` under each of its runs. A range is from
    the commit the run started from to the one it left on origin, or, for a slot it left unpushed, to the last commit it
    made there, marked as not on origin. A diff that was not kept is said to be missing, with why; one kept and since
    removed with the run's other files (§26) is said to be removed. Then the range's commits, by repository in
    `commits`, oldest first, each with the marks it lacks and whether canopy's own push put it on origin; their count
    alone when `commits` is None, as for an agent, which is given no worker's subject (§45).

    Returns:
        The lines, unindented: a repository's range, then a line for each diff kept, then why one was not, then its
        commits.
    """
    lines: list[str] = []
    for c in changes:
        if c.start_sha is None:
            lines.append(f"{c.repo}  nothing read: {one_line(c.missing or '')}")
            continue
        start = c.start_sha[:_SHORT]
        head = c.unpushed_sha or c.end_sha
        span = f"{start}..{head[:_SHORT]}" if head is not None else f"from {start}, no branch on origin"
        base = ", from its base" if c.start_on_base else ""
        fork = f", merge base {c.merge_base_sha[:_SHORT]}" if c.merge_base_sha is not None else ""
        left = "; not on origin: the run left it unpushed" if c.unpushed_sha is not None else ""
        lines.append(f"{c.repo}  {span}{base}{fork}{left}")
        if c.change_kept:
            lines.append(f"  its change {_kept(run_changes.change_path(log_path, c.repo))}")
        if c.branch_kept:
            lines.append(f"  against its base {_kept(review_diff.run_path_for(log_path, c.repo))}")
        if c.missing is not None:
            lines.append(f"  not kept: {one_line(c.missing)}")
        lines.extend(commit_lines(c, commits.get(c.repo, ()) if commits is not None else None))
    return lines


def commit_lines(change: records.RunChange, commits: Sequence[records.RunCommit] | None) -> list[str]:
    """The commits a run recorded in one repository's range (DESIGN §45), oldest first, under a count.

    Each is its short commit and its subject, the branch's text, cut to a line, then what canopy's marks say of it in
    brackets: the trailers or prefix it lacks (TRUST_MODEL T5), a co-author trailer not canopy's, and whether canopy's
    own push, not the worker, put it on origin. `commits` None prints the count alone.

    Returns:
        The lines, each indented by two spaces; none for a range whose commits were not read.
    """
    if change.commit_count is None:
        return []
    if commits is None:
        return [f"  commits ({change.commit_count})"]
    older = change.commit_count - len(commits)
    more = f", the oldest {older} not recorded" if older > 0 else ""
    lines = [f"  commits ({change.commit_count}{more}){':' if commits else ''}"]
    for commit in commits:
        marks = [
            *(["no canopy trailer"] if commit.canopy_trailer is False else []),
            *(["no prefix"] if commit.prefixed is False else []),
            *(["another co-author"] if commit.runtime_trailer else []),
            *(["pushed by canopy"] if commit.harness_pushed else []),
        ]
        noted = f"  [{', '.join(marks)}]" if marks else ""
        lines.append(f"    {commit.sha[:_SHORT]}  {one_line(commit.subject)}{noted}")
    return lines


def read_chore(ctx: Context, request: ShowChore) -> str:
    """Print a chore, as `canopy show chore:NAME` prints it.

    Returns:
        The chore's state, its latest run, its open findings, and the operator's notes its next run reads.

    Raises:
        reports.Refused: No chore of that name is configured.
    """
    name = request.name
    found = [s for s in chore_view.states(ctx.conn, ctx.config, ctx.workspace) if s.name == name]
    if not found:
        raise reports.Refused(f"no chore {name!r} is configured for this workspace")
    [state] = found
    lines = [f"chore:{name}: {chore_line(state, datetime.now(UTC))}"]
    latest = state.latest_ended
    if latest is not None:
        said = one_line(contract.stored_note(result_of(latest)))
        lines.append(f"  latest run {latest.id} {latest.status}" + (f": {said}" if said else ""))
        session = f"session {latest.session_id}" if latest.session_id else "no session reported"
        lines.extend([f"  {session}{spent(latest)}", f"  log {latest.log_path}"])
    findings = state.findings()
    more = state.more_findings()
    lines.append(f"\nOpen findings ({len(findings)}):")
    for f in findings:
        link = f"  {f.finding.link}" if f.finding.link else ""
        mark = "  (dismissed)" if f.dismissed else ""
        lines.append(f"  {f.finding.id}  {attention.age(f.since)}  {one_line(f.finding.title)}{link}{mark}")
    if more:
        lines.append(f"  {chore_result.more_text(more)}")
    elif not findings:
        lines.append("  none")
    notes = db.messages_of(ctx.conn, conversation.CHORE, name, conversation.CHORE_NOTES)
    if notes:
        lines.append(f"\nYour notes its next run reads ({len(notes)}):")
    for m in notes:
        lines.extend(message_lines(m))
    return "\n".join(lines)


def message_lines(m: records.Message) -> list[str]:
    """One message as `canopy show` prints it: a line naming it, then its text, indented, every hidden character named.

    Returns:
        Its lines.
    """
    return [_message_head(m), *(f"    {line}" for line in conversation.printable(m.body).splitlines())]


def _message_head(m: records.Message) -> str:
    who = {"worker": "worker", "operator": "you", "tracker": "tracker"}.get(m.source, m.source)
    if m.comment_id is not None:
        # A tracker or artifact comment a source observed, the operator's own on a private ticket among them, or one
        # the overseer mirrored before M37 (§22, §38).
        cut = ", truncated" if m.truncated else ""
        whose = "your" if m.source == "operator" else who
        return (
            f"  #{m.id}  {attention.age(m.at)} ago  {whose} comment {m.comment_id} by {m.author}, "
            f"written {m.commented_at}{cut}"
        )
    about = f" (run:{m.run_id})" if m.run_id else ""
    if m.answers:
        about += f" answering {m.answers}"
    via = f" via {m.channel}" if m.source == "operator" else ""
    return f"  #{m.id}  {attention.age(m.at)} ago  {who} {m.kind}{about}{via}"


def _kept(path: Path) -> str:
    """Return a kept diff's path, said to be removed once garbage collection removed it (DESIGN §26)."""
    return f"{path}" if path.is_file() else f"{path}, since removed"
