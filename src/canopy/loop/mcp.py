"""`canopy _mcp`: canopy's verbs as MCP tools, served over stdio to the run that starts it (DESIGN §27).

The agent runtime starts it as a child of the agent's process, and it lives as long as that run. It opens no
socket, and serves tools and nothing else: JSON-RPC 2.0, one message to a line, and five methods, `initialize`,
`notifications/initialized`, `ping`, `tools/list`, and `tools/call`. Rejected: the `mcp` SDK, a runtime dependency
with its own async stack and HTTP transports, for these few methods.

It serves in one of four modes, each its own tools. The overseer's (`OVERSEER`) are its verbs: a call is what the same
command would be (`loop.tools`), its arguments validated, the workspace opened afresh, the tick checked, one call at a
time. With CANOPY_RUN_ID set, or outside a running tick, it lists no tool and refuses every call. A chore's (`CHORE`,
`canopy _mcp --chore`) is one tool, its own chore's history (`chores.history`, DESIGN §19), which `canopy chore history`
also reads. The reports' (`REPORTS`, `canopy _mcp --reports`) are canopy's read-only reports, health, spend, the memory
listings, the config's settings, and what each agent is offered, which those commands print with `--json`
(`core.reports`), and the read-back of a tick's decisions, a run, and a chore (`loop.readback`). Each lists and serves
its tools only where CANOPY_RUN_ID names a chore's run, and serves nothing of the overseer's. The reviewer's and the
planner's (`git_mode`, `canopy _mcp --git NAME=PATH ...`) are read-only git in the checkouts its command line names, the
run's own (`core.git_tools`); it opens no workspace, and serves nothing else.

An overseer's tool lists its result's schema as its output schema, and answers with the text the command prints and
the result as structured content. A refusal or an invalid argument is a tool error, `isError`, with the text the command
prints and no structured content, and the server goes on. It writes nothing to stderr, which the runtime never reads,
and logs no argument's text.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from canopy.chores import history
from canopy.core import config, context, conversation, db, git_tools, reports
from canopy.infra import logs
from canopy.loop import chore_tools, readback, review_tools, tools

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from pydantic.json_schema import JsonSchemaMode

    from canopy.core.context import Context
    from canopy.infra import procs

#: The protocol versions the server speaks, newest first: a client that asks for one of them is answered in it, and
#: any other in the newest.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
#: JSON-RPC's error codes for a line that is not JSON, a message that is not a request, a method the server does not
#: have, parameters it cannot take, and a failure of its own.
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603

#: How a call opens the workspace: a context whose journal closes when the block ends.
type Opener = Callable[[], AbstractContextManager[Context]]
#: A JSON-RPC response, or None for a notification, which is never answered.
type Response = dict[str, object] | None


@dataclass(frozen=True)
class Tool:
    """One of canopy's verbs as a tool."""

    #: Its name: the command's, with hyphens for spaces. No name holds an underscore, which the runtime joins its
    #: server's name and the tool's with, so `canopy_ticket-set` cannot also be another server's tool.
    name: str
    #: What it does, for the model.
    description: str
    #: Its request, whose schema is the tool's input schema.
    request: type[BaseModel]
    #: Validate its arguments, then do it in the context the opener opens: what the command prints, with its result
    #: when it has one.
    call: Callable[[Mapping[str, object], Opener], str | tools.Outcome[tools.Result]]
    #: Its result, whose schema is the tool's output schema; None for a tool that answers with text alone.
    result: type[tools.Result] | None = None

    def listed(self) -> dict[str, object]:
        """Describe the tool as `tools/list` lists it.

        Returns:
            Its name, description, input schema, and output schema when it has a result.
        """
        listed: dict[str, object] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema(self.request),
        }
        if self.result is not None:
            listed["outputSchema"] = schema(self.result, "serialization")
        return listed


def tool[R: BaseModel, O: tools.Result](
    name: str,
    description: str,
    request: type[R],
    result: type[O],
    do: Callable[[Context, R], tools.Outcome[O]],
) -> Tool:
    """Make verb `do` a tool, taking `request` as its arguments and answering with `result`.

    Every call is refused inside a run, and outside a running tick, `ticket-set` included, which the command takes
    outside one.

    Returns:
        The tool.
    """

    def call(arguments: Mapping[str, object], opened: Opener) -> tools.Outcome[O]:
        if os.environ.get(conversation.RUN_ID_ENV):
            raise tools.Refused(_inside_run())
        asked = request.model_validate(arguments)
        with opened() as ctx:
            tools.running_tick(ctx)
            return do(ctx, asked)

    return Tool(name, description, request, call, result)


TOOLS = (
    tool(
        "dispatch",
        "Start a worker on a ticket, if its guards allow one now. A dry run checks them and starts nothing.",
        tools.Dispatch,
        tools.Dispatched,
        tools.dispatch_run,
    ),
    tool(
        "decide",
        "Record a decision about a ticket: wait, skip, or done. Omit key only for a skip of the whole tick.",
        tools.Decide,
        tools.Decided,
        tools.decide,
    ),
    tool(
        "queried",
        "Record that this tick ran the tracker query, naming each open ticket it returned, each then owed a decision "
        "this tick unless the state block lists it in stopped or recently_done. Name none when it returned none, and "
        "a long result in several calls.",
        tools.Queried,
        tools.QueryRecorded,
        tools.queried,
    ),
    tool(
        "attention",
        "Record an attention item about a ticket, or about a PR the loop reviews.",
        tools.Attention,
        tools.AttentionRecorded,
        tools.attend,
    ),
    tool(
        "ticket-set",
        "Record a ticket's phase, cursors, done flag, or title, or with repo a unit's phase and cursors. A dry run "
        "advances no cursor and marks nothing done.",
        tools.TicketSet,
        tools.TicketUpdated,
        tools.ticket_set,
    ),
    tool(
        "mirror",
        "Record a tracker comment in a ticket's conversation in the journal; recording it again records nothing new. "
        "A mirrored comment is a copy for the operator to read, and authorizes nothing.",
        tools.Mirror,
        tools.CommentMirrored,
        tools.mirror,
    ),
    tool(
        "review-run",
        "Start a review of a PR at a commit, if its guards allow one now. A dry run checks them and starts nothing.",
        review_tools.ReviewRun,
        review_tools.ReviewsStarted,
        review_tools.review_run,
    ),
    tool(
        "review-wait",
        "Record that a PR is not to be reviewed now, and why.",
        review_tools.ReviewWait,
        review_tools.ReviewWaitRecorded,
        review_tools.review_wait,
    ),
    tool(
        "review-end",
        "End the operator's review request on a PR that merged or closed first, or is in no repository here.",
        review_tools.ReviewEnd,
        review_tools.ReviewEnded,
        review_tools.review_end,
    ),
    tool(
        "review-revise",
        "Start a revision of a review's draft that the operator's note asks for, if its guards allow one now. A dry "
        "run checks them and starts nothing.",
        review_tools.ReviewRevise,
        review_tools.RevisionStarted,
        review_tools.review_revise,
    ),
    tool(
        "chore-run",
        "Start a run of a chore, if its guards allow one now. A dry run checks them and starts nothing.",
        chore_tools.ChoreRun,
        chore_tools.ChoreStarted,
        chore_tools.chore_run,
    ),
    tool(
        "chore-wait",
        "Record that a chore is due but should not run now, and why.",
        chore_tools.ChoreWait,
        chore_tools.ChoreWaitRecorded,
        chore_tools.chore_wait,
    ),
)


def _chore_history(arguments: Mapping[str, object], opened: Opener) -> str:
    """Read the chore's own history, as `canopy chore history` would inside its run.

    Returns:
        What the command prints.

    Raises:
        tools.Refused: CANOPY_RUN_ID names no chore's run, or the read refused, as the command would.
    """
    asked = history.History.model_validate(arguments)
    with opened() as ctx:
        try:
            history.run_chore(ctx.conn)
            return history.read(ctx, asked)
        except history.Refused as r:
            raise tools.Refused(str(r)) from None


#: A chore's one tool, which the runtime names `canopy_chore_history` (its server is `history.SERVER`).
CHORE_TOOLS = (
    Tool(
        history.TOOL,
        "List this chore's earlier runs, newest first, with what each reported; with run, one run's findings in full; "
        "with before, the page of runs before that id.",
        history.History,
        _chore_history,
    ),
)


#: Why a report is refused outside a chore's run, the one run the harness gives the reports' server today.
_CHORES_ALONE = "canopy's reports are served to a chore's run alone, and this is none"


def _report[R: BaseModel](name: str, description: str, request: type[R], do: Callable[[Context, R], str]) -> Tool:
    """Make report `do` a tool, taking `request` as its arguments: what its command prints.

    Every call is refused but in a chore's run, as the history tool's is, and a report that cannot say what was asked
    is refused with what its command says.

    Returns:
        The tool.
    """

    def call(arguments: Mapping[str, object], opened: Opener) -> str:
        asked = request.model_validate(arguments)
        with opened() as ctx:
            try:
                history.run_chore(ctx.conn)
            except history.Refused as r:
                raise tools.Refused(f"{name} refused ({r.guard}): {_CHORES_ALONE}") from None
            try:
                return do(ctx, asked)
            except reports.Refused as e:
                raise tools.Refused(str(e)) from None

    return Tool(name, description, request, call)


#: canopy's read-only reports (`core.reports`), which the runtime names `canopy_reports_health` and so on. An agent
#: given the server allows those it reads by name; `canopy-chore` reads none.
REPORT_TOOLS = (
    _report(
        reports.HEALTH,
        "How canopy's ticks and runs of the last days ended, as JSON: each kind of run by status and cost "
        "(outcomes), the newest failures with an id and a note (failures), and the overseer's asks a guard refused "
        "(refusals).",
        reports.Health,
        reports.read_health,
    ),
    _report(
        reports.SPEND,
        "What canopy's agent runs cost over the last days, as JSON: per day and kind, by ticket, by tool with what "
        "its calls returned and how many errored (tools), and by model.",
        reports.Spend,
        reports.read_spend,
    ),
    _report(
        reports.MEMORY_LESSONS,
        "The lessons the operator promoted, as JSON (lessons), each with its reads, citations, review date, and any "
        "run's report that it is wrong; and each memory tier's mode (modes).",
        reports.MemoryLessons,
        reports.read_lessons,
    ),
    _report(
        reports.MEMORY_PROPOSALS,
        "The lessons workers proposed that wait on the operator, as JSON (proposals), each with its ticket and run, "
        "whether that ticket is done, and whether the run was a private ticket's; and each tier's mode (modes).",
        reports.MemoryProposals,
        reports.read_proposals,
    ),
    _report(
        reports.MEMORY_LIST,
        "The ticket notes workers recorded, as JSON (notes), of one ticket or every one, each with the run that "
        "wrote it and how many runs read and cited it; and each tier's mode (modes).",
        reports.MemoryList,
        reports.read_notes,
    ),
    _report(
        reports.DECISIONS,
        "One tick's decisions, as text: the tick's status, summary, and cost, then each decision's subject, action, "
        "and rationale, of one ticket if asked; the latest tick's unless tick names one. A failure in health names its "
        "tick.",
        readback.Decisions,
        readback.read_decisions,
    ),
    _report(
        reports.SHOW_RUN,
        "One worker or plan run, as text: its ticket, kind, and status, its slots, PRs, cost, session, log, and the "
        "messages it sent. A failure in health names its run.",
        readback.ShowRun,
        readback.read_run,
    ),
    _report(
        reports.SHOW_CHORE,
        "One chore, as text: when it last ran and is next due, its latest run, its open findings, and the operator's "
        "notes its next run reads.",
        readback.ShowChore,
        readback.read_chore,
    ),
    _report(
        reports.CONFIG_SHOW,
        "Each number, switch, and choice in canopy's config, as JSON (settings): its value, default, the file that set "
        "it, and the choices or bounds it takes. Keys that hold text, commands, or paths are left out.",
        reports.ConfigShow,
        reports.read_config,
    ),
    _report(
        reports.AGENTS,
        "What each of canopy's agents is offered once the operator's runtime config is merged into canopy's, as JSON: "
        "every MCP server and skill, each server's reach per agent, and the commands runtime.allow_bash gives each. "
        "It starts the runtime to ask, so it takes a few seconds.",
        reports.Agents,
        reports.read_agents,
    ),
)


@dataclass(frozen=True)
class Mode:
    """What the server serves: the overseer's verbs, a chore its history, canopy's reports, or git."""

    #: The tools it lists and serves.
    tools: Sequence[Tool]
    #: Why it lists no tool now, or None when it lists them; each call checks again for itself.
    refusal: Callable[[Opener], str | None]


def run_stdio(
    runner: procs.Runner,
    *,
    chore: bool = False,
    serve_reports: bool = False,
    checkouts: Mapping[str, Path] | None = None,
) -> int:
    """Serve on this process's stdin and stdout until stdin closes, with `runner` for every process a call starts.

    `chore` serves a chore's run its history (`CHORE`), and `serve_reports` canopy's reports (`REPORTS`), each from the
    workspace its run names; `checkouts`, a review's or a plan's run read-only git in those checkouts, by name
    (`git_mode`); else it serves the overseer's verbs.

    The protocol keeps its own copy of stdout; the process's stdout and stderr then go nowhere, so nothing a call
    prints, and no warning or traceback, reaches the runtime's pipes.

    Returns:
        0, once stdin has closed or the runtime stopped reading.
    """
    out = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    devnull = os.open(os.devnull, os.O_WRONLY)
    for fd in (sys.stdout.fileno(), sys.stderr.fileno()):
        os.dup2(devnull, fd)
    os.close(devnull)

    def write(line: str) -> None:
        out.write(line)
        out.flush()

    # A chore's agent may run in a `cwd` outside the workspace; its run names the workspace it belongs to.
    root = os.environ.get(history.WORKSPACE_ENV) if chore or serve_reports else None
    start = Path(root) if root else Path.cwd()
    mode = git_mode(runner, checkouts) if checkouts else CHORE if chore else REPORTS if serve_reports else OVERSEER
    with contextlib.suppress(BrokenPipeError), out:
        serve(sys.stdin.buffer, write, lambda: opened(runner, start), mode)
    return 0


def git_mode(runner: procs.Runner, checkouts: Mapping[str, Path]) -> Mode:
    """Read-only git in `checkouts`, by name, for a review's or a plan's run, with `runner` for each git it runs.

    It lists its tools wherever it runs: what it may read is what its command line names, set by the harness for the
    run, never by the agent. A call opens no workspace.

    Returns:
        The mode.
    """
    found = (
        _git_tool(
            git_tools.MERGE_BASE,
            "Find the commit where two commits' histories meet, such as where a branch left its base.",
            git_tools.MergeBase,
            git_tools.merge_base,
            runner=runner,
            checkouts=checkouts,
        ),
        _git_tool(
            git_tools.DIFF,
            "Show the diff from one commit to another, in the paths named if any, or with stat each file changed and "
            "its lines added and removed. Commits only, never the working tree.",
            git_tools.Diff,
            git_tools.diff,
            runner=runner,
            checkouts=checkouts,
        ),
        _git_tool(
            git_tools.LOG,
            "List commits, newest first, with each one's message and the files it changed: one commit's history, or "
            "BASE..HEAD for those on HEAD and not BASE. Narrow it to commits that change some paths, add or remove a "
            "text (search), or say one in their message (message); follow one path across renames.",
            git_tools.Log,
            git_tools.log,
            runner=runner,
            checkouts=checkouts,
        ),
        _git_tool(
            git_tools.SHOW,
            "Read a file as it is at a commit, or list a directory's entries there.",
            git_tools.Show,
            git_tools.show,
            runner=runner,
            checkouts=checkouts,
        ),
        _git_tool(
            git_tools.BLAME,
            "Name the commit that last changed each of some lines of a file as it is at a commit, with its author and "
            "date: which lines a branch wrote, and what commit to read for why the rest are so. moves and "
            "ignore_whitespace look past a refactor that moved or reindented them.",
            git_tools.Blame,
            git_tools.blame,
            runner=runner,
            checkouts=checkouts,
        ),
        _git_tool(
            git_tools.GREP,
            "Find the lines that hold an exact text in the files as they are at a commit, each as path:line:text: "
            "who calls a function, or what used a name before a branch changed it. Not a pattern; files that are not "
            "text are left out.",
            git_tools.Grep,
            git_tools.grep,
            runner=runner,
            checkouts=checkouts,
        ),
        _git_tool(
            git_tools.FILES,
            "List the paths of the files as they are at a commit, under some paths if named, and only those whose own "
            "name matches a name or a glob such as `*.py` if one is given.",
            git_tools.Files,
            git_tools.files,
            runner=runner,
            checkouts=checkouts,
        ),
    )
    return Mode(found, lambda _opener: None)


def _git_tool[R: git_tools.Request](
    name: str,
    description: str,
    request: type[R],
    do: Callable[[procs.Runner, Mapping[str, Path], R], str],
    *,
    runner: procs.Runner,
    checkouts: Mapping[str, Path],
) -> Tool:
    """Make git read `do` a tool over `checkouts`, taking `request` as its arguments.

    Returns:
        The tool, which never opens the workspace.
    """

    def call(arguments: Mapping[str, object], opened: Opener) -> str:  # noqa: ARG001  (git reads no journal)
        asked = request.model_validate(arguments)
        try:
            return do(runner, checkouts, asked)
        except git_tools.Refused as r:
            raise tools.Refused(str(r)) from None

    return Tool(name, description, request, call)


def serve(lines: Iterable[bytes], write: Callable[[str], object], opener: Opener, mode: Mode | None = None) -> None:
    """Answer each message in `lines` with `write`, one at a time, until `lines` ends.

    `opener` opens the workspace for a call: `opened`, outside the tests. `mode` is what it serves, the overseer's verbs
    unless given.
    """
    for line in lines:
        if line.strip():
            response = answer(line, opener, mode)
            if response is not None:
                # Escaped to ASCII: a lone surrogate a client sent, echoed in a refusal, could not be written as UTF-8.
                write(json.dumps(response) + "\n")


@contextlib.contextmanager
def opened(runner: procs.Runner, start: Path) -> Iterator[Context]:
    """Open the workspace `start` is in, as a command does, for one call.

    Yields:
        The context, whose journal closes when the block ends.
    """
    ctx = context.open_at(start, runner)
    try:
        yield ctx
    finally:
        ctx.conn.close()


def answer(line: bytes, opener: Opener, mode: Mode | None = None) -> Response:
    """Answer one message, serving `mode`, the overseer's verbs unless given.

    Returns:
        The response to a request, or None for a notification, which is never answered.
    """
    try:
        message = _read(line)
    except _Failed as e:
        return _error(e.request_id, e.code, str(e))
    if message is None:
        return None
    method = _METHODS.get(message.method)
    if method is None:
        return _error(message.id, METHOD_NOT_FOUND, f"no method {message.method!r}: canopy serves tools only")
    try:
        result = method(message.params, opener, mode or OVERSEER)
    except _Failed as e:
        return _error(message.id, e.code, str(e))
    except Exception as e:  # noqa: BLE001  (a bug answers this request, and the server goes on serving)
        logs.for_tick(None).error(
            "mcp request failed",
            extra={"method": message.method, "error": type(e).__name__, "frames": traceback.format_tb(e.__traceback__)},
        )
        return _error(message.id, INTERNAL_ERROR, f"canopy failed: {type(e).__name__}; its log says where")
    return {"jsonrpc": "2.0", "id": message.id, "result": result}


def schema(model: type[BaseModel], mode: JsonSchemaMode = "validation") -> dict[str, object]:
    """Return a model's JSON schema as a tool's: every reference inlined, and no titles.

    A request's, in `mode` "validation", is its tool's input schema; a result's, in "serialization", its output schema.
    Some models' providers take no `$ref`, and a title only repeats its field's name. What a docstring says is for
    canopy's readers, so only the fields' own descriptions are kept.

    Returns:
        The schema, an object that holds no field the model does not.
    """
    whole = model.model_json_schema(mode=mode)
    # The model's docstring says what it is to canopy's readers; the tool's description says what it does.
    whole.pop("description", None)
    definitions = whole.pop("$defs", {})
    inlined = _inlined(whole, definitions if isinstance(definitions, dict) else {})
    return inlined if isinstance(inlined, dict) else {}


class _Message(BaseModel):
    """A JSON-RPC 2.0 request, or a notification without its `id`."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    jsonrpc: Literal["2.0"]
    id: StrictInt | StrictStr | None = None
    method: StrictStr
    params: Mapping[str, object] = Field(default_factory=dict)


class _Params(BaseModel):
    # A method's parameters keep a field the protocol adds in a later version, such as `_meta`, which this server has
    # no use for; it is a tool's arguments that refuse an unknown field.
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)


class _Initialize(_Params):
    """What a client says it speaks."""

    protocol_version: Annotated[StrictStr, Field(alias="protocolVersion")]


class _Call(_Params):
    """Which tool a client calls, with what."""

    name: StrictStr
    arguments: Mapping[str, object] | None = None


class _Failed(Exception):  # noqa: N818  (answered as JSON-RPC's error, not raised past the server)
    """A message the server cannot answer as asked: `code` is JSON-RPC's for why, and `request_id` the request's."""

    def __init__(self, code: int, message: str, request_id: object = None) -> None:
        """Say why, with JSON-RPC's code for it, about the request `request_id` names."""
        super().__init__(message)
        self.code = code
        self.request_id = request_id


def _read(line: bytes) -> _Message | None:
    """Read one message.

    Returns:
        The request, or None for a notification: `notifications/initialized`, or one the server has no use for.

    Raises:
        _Failed: The line is not JSON, or not one JSON-RPC message.
    """
    try:
        raw: object = json.loads(line)
    except ValueError:
        raise _Failed(PARSE_ERROR, "not a JSON message") from None
    if not isinstance(raw, dict):
        raise _Failed(INVALID_REQUEST, "a message is one JSON object; batches are not taken")
    try:
        message = _Message.model_validate(raw)
    except ValidationError as e:
        raise _Failed(INVALID_REQUEST, tools.explain(e), _id_of(raw)) from None
    return message if "id" in raw else None


def _initialize(params: Mapping[str, object], opener: Opener, mode: Mode) -> dict[str, object]:  # noqa: ARG001
    asked = _parsed(_Initialize, params)
    version = asked.protocol_version if asked.protocol_version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "canopy", "version": db.CANOPY_VERSION},
    }


def _ping(params: Mapping[str, object], opener: Opener, mode: Mode) -> dict[str, object]:  # noqa: ARG001
    return {}


def _list(params: Mapping[str, object], opener: Opener, mode: Mode) -> dict[str, object]:  # noqa: ARG001  (one page)
    return {"tools": [] if mode.refusal(opener) is not None else [t.listed() for t in mode.tools]}


def _call(params: Mapping[str, object], opener: Opener, mode: Mode) -> dict[str, object]:
    asked = _parsed(_Call, params)
    found = next((t for t in mode.tools if t.name == asked.name), None)
    if found is None:
        raise _Failed(INVALID_PARAMS, f"no tool named {asked.name!r}")
    try:
        said = found.call(asked.arguments or {}, opener)
    except ValidationError as e:
        return _said(tools.explain(e), error=True)
    except tools.Refused as e:
        return _said(str(e), error=True)
    except (config.ConfigError, db.MigrationError) as e:
        return _said(f"canopy: {e}", error=True)
    return _said(said) if isinstance(said, str) else _said(said.text, structured=said.result)


_METHODS: Mapping[str, Callable[[Mapping[str, object], Opener, Mode], dict[str, object]]] = {
    "initialize": _initialize,
    "ping": _ping,
    "tools/list": _list,
    "tools/call": _call,
}


def _overseer_refusal(opener: Opener) -> str | None:
    """Say why none of the overseer's tools is served now: inside a run, or outside a running tick.

    Returns:
        Why, as a refusal says it, or None when tools are served.
    """
    if os.environ.get(conversation.RUN_ID_ENV):
        return _inside_run()
    try:
        with opener() as ctx:
            tools.running_tick(ctx)
    except tools.Refused as e:
        return str(e)
    except (config.ConfigError, db.MigrationError) as e:
        return f"canopy: {e}"
    return None


def _chore_refusal(opener: Opener) -> str | None:
    """Say why a chore's tool is not served now: CANOPY_RUN_ID names no chore's run.

    Returns:
        Why, as a refusal says it, or None when it is served.
    """
    try:
        with opener() as ctx:
            history.run_chore(ctx.conn)
    except history.Refused as r:
        return str(r)
    except (config.ConfigError, db.MigrationError) as e:
        return f"canopy: {e}"
    return None


#: The overseer's verbs, served inside a running tick and never inside a run.
OVERSEER = Mode(TOOLS, _overseer_refusal)
#: A chore's history, served inside that chore's run alone.
CHORE = Mode(CHORE_TOOLS, _chore_refusal)
#: canopy's read-only reports, served inside a chore's run alone, the one run the harness gives their server today.
REPORTS = Mode(REPORT_TOOLS, _chore_refusal)


def _inside_run() -> str:
    return f"{conversation.RUN_ID_ENV} is set: canopy's tools are the overseer's, and refuse inside a run"


def _parsed[P: _Params](params_model: type[P], params: Mapping[str, object]) -> P:
    try:
        return params_model.model_validate(params)
    except ValidationError as e:
        raise _Failed(INVALID_PARAMS, tools.explain(e)) from None


def _said(text: str, *, error: bool = False, structured: BaseModel | None = None) -> dict[str, object]:
    said: dict[str, object] = {"content": [{"type": "text", "text": text}], "isError": error}
    if structured is not None:
        said["structuredContent"] = structured.model_dump(mode="json")
    return said


def _error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _id_of(raw: Mapping[str, object]) -> object:
    """Find the id of a message that is not a valid request.

    Returns:
        Its id when it has one JSON-RPC allows, else None.
    """
    found = raw.get("id")
    return found if isinstance(found, int | str) and not isinstance(found, bool) else None


def _inlined(node: object, definitions: Mapping[str, object], *, fields: bool = False) -> object:
    """Inline each `$ref` in `node`, and leave out each schema's `title`.

    `fields` marks a `properties` object, whose keys are field names, kept whatever they are.

    Returns:
        `node` with each reference replaced by the definition it names.
    """
    if isinstance(node, list):
        return [_inlined(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    if fields:
        return {name: _inlined(value, definitions) for name, value in node.items()}
    ref = node.get("$ref")
    if isinstance(ref, str):
        # A definition's description is its class's docstring, for canopy's readers; a field's own is kept.
        named = definitions.get(ref.rsplit("/", 1)[-1])
        defined = {k: v for k, v in named.items() if k != "description"} if isinstance(named, dict) else {}
        return _inlined({**defined, **{k: v for k, v in node.items() if k != "$ref"}}, definitions)
    return {
        key: _inlined(value, definitions, fields=key == "properties") for key, value in node.items() if key != "title"
    }
