"""What OpenCode 2 offers canopy's agents, asked of a private `opencode serve` as OpenCode 2.1.2 answers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.infra import procs
from canopy.runtime.agents import AgentOffer, ServerOffer, SkillFile
from canopy.runtime.opencode2 import offerings
from canopy.runtime.opencode2.offerings import matches

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

URL = "http://127.0.0.1:41234"
#: `config.get`: canopy's definitions directory, a project file with a secret, and inline config, as OpenCode normalized
#: them. A later definition of `github` replaces the earlier one whole.
CONFIG: list[object] = [
    {"type": "directory", "path": "/defs"},
    {
        "type": "document",
        "path": "/ws/opencode.json",
        "info": {
            "providers": {"anthropic": {"settings": {"apiKey": "sk-s3cret"}}},
            "mcp": {"servers": {"github": {"type": "remote", "url": "https://x", "disabled": True}}},
        },
    },
    {
        "type": "document",
        "info": {
            "mcp": {
                "servers": {
                    "github": {"type": "remote", "url": "https://api.example.test/mcp/"},
                    "sentry.io": {"type": "local", "command": ["sentry-mcp"], "disabled": True},
                    "canopy": {"type": "local", "command": ["canopy", "_mcp"], "codemode": False},
                },
            },
        },
    },
]
#: `skill.list`: OpenCode's two built in, and two of canopy's.
SKILLS = [{"id": s, "name": s, "description": "d"} for s in ("opencode", "report", "tracker-jira", "tracker-github")]


def rule(action: str, effect: str = "deny", resource: str = "*") -> dict[str, str]:
    return {"action": action, "resource": resource, "effect": effect}


#: Every built-in tool OpenCode 2.1.2 sends an agent whose rules keep none from it.
EVERY_TOOL = (
    "edit",
    "execute",
    "glob",
    "grep",
    "question",
    "read",
    "shell",
    "skill",
    "subagent",
    "webfetch",
    "websearch",
    "write",
)
#: The rules OpenCode 2 starts every agent from.
DEFAULTS = [rule("*", "allow"), rule("read", "ask", "*.env"), rule("read", "ask", "*.env.*")]
#: What OpenCode writes of its stdout to a pipe before it exits: what the pipe's buffer holds.
PIPE_BUFFER = 64 * 1024


@dataclass
class Serve:
    """Plays `opencode serve` and `opencode api --server`, each agent's rules as given, and records what ran."""

    rules: Mapping[str, Sequence[dict[str, str]]]
    config: object = field(default_factory=lambda: CONFIG)
    skills: object = field(default_factory=lambda: SKILLS)
    #: How many times `agent.list` answers with OpenCode's own agents alone, before the plugins load canopy's.
    loading: int = 0
    #: Whether `agent.list` answers with no agent at all while loading, rather than OpenCode's own.
    empty: bool = False
    #: What answers in place of the play, for a command it is given.
    fail: Callable[[Sequence[str]], procs.Result | None] = lambda _: None
    ran: list[tuple[tuple[str, ...], Path | None, dict[str, str]]] = field(default_factory=list)

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,  # noqa: ARG002
        timeout: float | None = None,  # noqa: ARG002
        on_start: Callable[[int], None] | None = None,  # noqa: ARG002
        on_line: Callable[[str], None] | None = None,
        stdout_to_file: bool = False,
    ) -> procs.Result:
        self.ran.append((tuple(args), cwd, dict(env or {})))
        failed = self.fail(args)
        if failed is not None:
            return failed
        # Whatever starts OpenCode, the words after it are its own.
        start = max(i for i, word in enumerate(args) if Path(word).name == "opencode")
        match ["opencode", *args[start + 1 :]]:
            case ["opencode", "serve", *_]:
                assert on_line is not None
                on_line("Warning: plugin loading\n")
                on_line(f"server listening on {URL}\n")
                raise AssertionError("the server outlived its questions")
            case ["opencode", "api", "--server", url, operation]:
                assert url == URL
                printed = self._answer(operation)
            case _:
                raise AssertionError(args)
        stdout = json.dumps(printed)
        return procs.Result(tuple(args), 0, stdout if stdout_to_file else stdout[:PIPE_BUFFER], "")

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:  # noqa: ARG002
        raise AssertionError(args)

    def _answer(self, operation: str) -> object:
        location = {"directory": "/ws"}
        match operation:
            case "agent.list":
                if self.loading:
                    self.loading -= 1
                    own: list[object] = [] if self.empty else [{"id": "build", "permissions": DEFAULTS}]
                    return {"location": location, "data": own}
                agents = [{"id": n, "mode": "primary", "permissions": [*DEFAULTS, *r]} for n, r in self.rules.items()]
                return {"location": location, "data": [{"id": "build", "permissions": DEFAULTS}, *agents]}
            case "skill.list":
                return {"location": location, "data": self.skills}
            case "config.get":
                return self.config
            case _:
                raise AssertionError(operation)


@pytest.fixture(autouse=True)
def no_waiting() -> Iterator[None]:
    with mock.patch.object(offerings, "POLL_SECONDS", 0):
        yield


def offered(serve: Serve, *agents: str) -> offerings.Offerings:
    return offerings.offerings(serve, cwd=Path("/ws"), definitions_dir=Path("/defs"), agents=agents)


def test_each_agent_is_offered_what_its_merged_rules_leave_it() -> None:
    serve = Serve(
        {
            # The operator denied github to the chore; canopy's own patterns after it change nothing more of it.
            "canopy-chore": [rule("github_*"), rule("*create*"), rule("skill", resource="report")],
            # Canopy's read tools only: every tool of the server denied, then some named; and no skill at all.
            "canopy-planner": [rule("github_*"), rule("github_issue_read", "allow"), rule("skill")],
            "canopy-worker": [],
        },
        loading=2,
    )
    found = offered(serve, "canopy-chore", "canopy-planner", "canopy-worker")
    assert found.error is None
    assert (found.servers, found.disabled_servers) == (("github", "sentry.io", "canopy"), ("sentry.io",))
    assert found.skills == ("opencode", "report", "tracker-github", "tracker-jira")
    chore, planner, worker = found.agents
    assert chore == AgentOffer(
        "canopy-chore",
        # `sentry.io`'s tools are named `sentry_io_*`, and `*create*` could match one of them.
        servers=(
            ServerOffer("github", "none"),
            ServerOffer("sentry.io", "some", ("deny *create*",)),
            ServerOffer("canopy", "some", ("deny *create*",)),
        ),
        skills=("opencode", "tracker-github", "tracker-jira"),
        denied_skills=("report",),
        tools=EVERY_TOOL,
    )
    assert planner.servers[0] == ServerOffer("github", "some", ("offer github_issue_read",))
    assert (planner.skills, planner.denied_skills) == ((), found.skills)
    assert "skill" not in planner.tools
    assert worker.servers == (
        ServerOffer("github", "all"),
        ServerOffer("sentry.io", "all"),
        ServerOffer("canopy", "all"),
    )
    # The server started where a run starts, with canopy's definitions, on loopback, and each question asked with the
    # same environment, its password one canopy made.
    serve_argv, cwd, env = serve.ran[0]
    assert serve_argv == ("opencode", "serve", "--hostname", "127.0.0.1", "--port", "0")
    assert cwd == Path("/ws")
    assert env["OPENCODE_CONFIG_DIR"] == "/defs"
    assert len(env[offerings.PASSWORD_ENV]) >= 32
    asked = [argv[-1] for argv, _, _ in serve.ran[1:]]
    assert asked == ["agent.list"] * 3 + ["skill.list", "config.get"]
    assert all(e == env for _, _, e in serve.ran)


def test_each_skill_is_kept_as_the_server_read_it_sorted_by_id() -> None:
    skills = [
        {"id": "terse", "name": "terse", "path": "/ws/.opencode/skills/terse/SKILL.md", "content": "Be brief.\n"},
        {
            "id": "audit",
            "name": "audit",
            "description": "Check the books.",
            "path": "/defs/skills/a/SKILL.md",
            "content": "x",
        },
    ]
    found = offered(Serve({"canopy-worker": []}, skills=skills), "canopy-worker")
    assert found.skills == ("audit", "terse")
    assert found.skill_files == (
        SkillFile("audit", "Check the books.", "/defs/skills/a/SKILL.md", "x"),
        SkillFile("terse", None, "/ws/.opencode/skills/terse/SKILL.md", "Be brief.\n"),
    )


def test_what_opencode_prints_past_a_pipes_buffer_is_read() -> None:
    long = {"id": "long", "name": "long", "description": "x" * PIPE_BUFFER}
    found = offered(Serve({"canopy-worker": []}, skills=[*SKILLS, long]), "canopy-worker")
    assert found.error is None
    assert "long" in found.skills


def test_a_tool_is_kept_from_an_agent_only_by_a_deny_of_every_resource() -> None:
    rules = [rule("shell"), rule("shell", "allow", "git status"), rule("edit"), rule("webfetch", resource="https://*")]
    [worker] = offered(Serve({"canopy-worker": rules}), "canopy-worker").agents
    # A later allow of one command keeps `shell` offered; `edit` takes `write` with it; `webfetch` is refused per call.
    assert "shell" in worker.tools
    assert "webfetch" in worker.tools
    assert not {"edit", "write"} & set(worker.tools)


def test_a_server_in_code_mode_is_reached_through_execute_alone() -> None:
    [overseer] = offered(Serve({"canopy-overseer": [rule("execute")]}), "canopy-overseer").agents
    reason = ("deny execute, which its tools are called through",)
    # `canopy`'s config takes it out of code mode, so its tools are offered by name.
    assert overseer.servers == (
        ServerOffer("github", "none", reason),
        ServerOffer("sentry.io", "none", reason),
        ServerOffer("canopy", "all"),
    )
    assert "execute" not in overseer.tools


def test_an_agent_opencode_did_not_load_says_so() -> None:
    with mock.patch.object(offerings, "LOADED_SECONDS", 0):
        found = offered(Serve({"canopy-worker": []}), "canopy-worker", "canopy-chore")
    assert found.agents[1] == AgentOffer(
        "canopy-chore",
        error="OpenCode has no agent canopy-chore: its definition did not load",
    )


def test_a_server_that_never_loads_an_agent_is_the_error() -> None:
    with mock.patch.object(offerings, "LOADED_SECONDS", 0):
        found = offered(Serve({"canopy-worker": []}, loading=10**6, empty=True), "canopy-worker")
    assert found.error == "`opencode serve` had loaded no agent after 0 seconds"


@pytest.mark.parametrize(
    ("text", "pattern", "matched"),
    [
        ("github_issue_read", "github_*", True),
        ("github_issue_read", "jira_*", False),
        ("github.issue", "github?issue", True),
        ("githubxissue", "github.issue", False),  # `.` is literal
        ("git status", "git status *", True),  # a trailing ` *` matches without the space too
        ("a\nb", "a*", True),
    ],
)
def test_patterns_match_as_opencode_matches_them(text: str, pattern: str, *, matched: bool) -> None:
    assert matches(text, pattern) is matched


def test_an_answer_canopy_cannot_read_is_the_error_and_names_no_secret() -> None:
    unreadable = offered(
        Serve({}, config=[{"type": "document", "info": {"mcp": {"servers": {"x": {"disabled": "sk-s3cret"}}}}}]),
    )
    assert unreadable.error == "`opencode api config.get` printed what canopy cannot read"
    assert "s3cret" not in str(unreadable)

    def fail(args: Sequence[str]) -> procs.Result | None:
        return procs.Result(tuple(args), 1, "", "token = sk-s3cret") if args[-1] == "skill.list" else None

    failed = offered(Serve({}, fail=fail))
    assert failed.error == "`opencode api skill.list` exited 1"


def test_a_server_that_cannot_start_or_never_listens_is_the_error() -> None:
    def missing(args: Sequence[str]) -> procs.Result | None:
        raise procs.CommandNotFoundError(args[0])

    assert offered(Serve({}, fail=missing)).error == "opencode is not on PATH"

    def exits(args: Sequence[str]) -> procs.Result | None:
        return procs.Result(tuple(args), 2, "", "")

    assert offered(Serve({}, fail=exits)).error == "`opencode serve` exited 2; run it to see why"

    def slow(args: Sequence[str]) -> procs.Result | None:
        return procs.Result(tuple(args), -9, "", "", timed_out=True)

    assert offered(Serve({}, fail=slow)).error == (
        f"`opencode serve` did not listen within {offerings.TIMEOUT_SECONDS} seconds"
    )


def test_a_run_is_asked_about_as_its_own_command_starts_opencode() -> None:
    serve = Serve(
        {"canopy-chore": [rule("github_*"), rule("github_issue_read", "allow"), rule("skill", resource="tr*")]},
    )
    argv = ("canopy-sandbox", "chore", "env", "OPENCODE_CONFIG_DIR=/defs", "/usr/bin/opencode", "run")
    found = offerings.offered(
        serve,
        (*argv, "--standalone", "--agent=canopy-chore", "--format", "json", "Say ok."),
        cwd=Path("/run"),
        env={"CANOPY_RUN_ID": "7"},
    )
    # The server its config turns off is offered to no run, so it is not among them.
    assert found.servers == (
        ServerOffer("github", "some", ("offer github_issue_read",)),
        ServerOffer("canopy", "all"),
    )
    assert (found.skills, found.denied_skills) == (("opencode", "report"), ("tracker-github", "tracker-jira"))
    # `opencode run` and what follows it swapped for `serve`, then `api`, inside what wraps it, where the run starts.
    launcher = argv[:-1]
    assert [args[: len(launcher)] for args, _, _ in serve.ran] == [launcher] * 4
    assert {cwd for _, cwd, _ in serve.ran} == {Path("/run")}
    assert all(env["CANOPY_RUN_ID"] == "7" for _, _, env in serve.ran)


@pytest.mark.parametrize(
    ("argv", "error"),
    [
        (("agent", "run", "--agent", "canopy-worker", "x"), "its command runs no `opencode run`"),
        (("opencode", "serve"), "its command runs no `opencode run`"),
        (("opencode", "run", "--agent", "Not A Name", "x"), "its command names no agent"),
        # The prompt is one word, whatever its text says.
        (("opencode", "run", "Run with --agent canopy-worker please"), "its command names no agent"),
    ],
)
def test_a_run_whose_command_canopy_cannot_read_is_not_asked_about(argv: Sequence[str], error: str) -> None:
    serve = Serve({})
    assert offerings.offered(serve, argv, cwd=Path("/run"), env={}) == AgentOffer("", error=error)
    assert serve.ran == []
