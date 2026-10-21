"""What OpenCode offers canopy's agents, read from `opencode debug` as OpenCode 1.19.3 prints it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from canopy.infra import procs
from canopy.runtime.agents import AgentOffer, ServerOffer
from canopy.runtime.opencode import offerings
from canopy.runtime.opencode.offerings import matches

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

#: `opencode debug config` with two servers, one turned off, and a secret OpenCode redacts.
CONFIG = {
    "mcp": {
        "github": {"type": "remote", "url": "https://api.example.test/mcp/", "headers": {"Authorization": "***"}},
        "sentry.io": {"type": "local", "command": ["sentry-mcp"], "enabled": False},
    },
}
#: `opencode debug skill`: one built in, two of canopy's.
SKILLS = [
    {"name": "customize-opencode", "description": "d", "location": "<built-in>", "content": "x"},
    {"name": "tracker-jira", "description": "d", "location": "/defs/skills/tracker-jira/SKILL.md", "content": "x"},
    {"name": "tracker-github", "description": "d", "location": "/defs/skills/tracker-github/SKILL.md", "content": "x"},
]


def rule(permission: str, action: str = "deny", pattern: str = "*") -> dict[str, str]:
    return {"permission": permission, "pattern": pattern, "action": action}


#: The rules OpenCode starts every agent from, as `opencode debug agent` prints them first.
DEFAULTS = [rule("*", "allow"), rule("doom_loop", "ask"), rule("external_directory", "ask")]


@dataclass
class Debug:
    """Plays `opencode debug`, each agent's rules as given, and records what it was run with."""

    rules: Mapping[str, Sequence[dict[str, str]]]
    config: object = field(default_factory=lambda: CONFIG)
    fail: Callable[[Sequence[str]], procs.Result | None] = lambda _: None
    #: The built-in tools `debug agent` says each agent keeps.
    tools: Mapping[str, bool] = field(default_factory=dict)
    #: What a plugin prints before and after each command's own output.
    around: tuple[str, str] = ("", "")
    ran: list[tuple[tuple[str, ...], Path | None, Mapping[str, str] | None]] = field(default_factory=list)

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,  # noqa: ARG002
        timeout: float | None = None,  # noqa: ARG002
        on_start: Callable[[int], None] | None = None,  # noqa: ARG002
        on_line: Callable[[str], None] | None = None,  # noqa: ARG002
        stdout_to_file: bool = False,  # noqa: ARG002
    ) -> procs.Result:
        self.ran.append((tuple(args), cwd, env))
        failed = self.fail(args)
        if failed is not None:
            return failed
        # Whatever starts OpenCode, the words after it are its own.
        start = max(i for i, word in enumerate(args) if Path(word).name == "opencode")
        match ["opencode", *args[start + 1 :]]:
            case ["opencode", "debug", "config"]:
                printed: object = self.config
            case ["opencode", "debug", "skill"]:
                printed = SKILLS
            case ["opencode", "debug", "agent", name]:
                permission = [*DEFAULTS, *self.rules[name]]
                printed = {"name": name, "mode": "primary", "permission": permission, "tools": self.tools}
            case _:
                raise AssertionError(args)
        before, after = self.around
        return procs.Result(tuple(args), 0, f"{before}{json.dumps(printed, indent=2)}\n{after}", "")

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:  # noqa: ARG002
        raise AssertionError(args)


def offered(debug: Debug, *agents: str) -> offerings.Offerings:
    return offerings.offerings(debug, cwd=Path("/ws"), definitions_dir=Path("/defs"), agents=agents)


def test_each_agent_is_offered_what_its_merged_rules_leave_it() -> None:
    debug = Debug(
        {
            # The operator denied github to the chore; canopy's own patterns after it change nothing more of it.
            "canopy-chore": [rule("github_*"), rule("*create*"), rule("skill", pattern="customize-opencode")],
            # Canopy's read tools only: every tool of the server denied, then some named.
            "canopy-planner": [rule("github_*"), rule("github_issue_read", "allow"), rule("skill")],
            "canopy-worker": [],
        },
    )
    found = offered(debug, "canopy-chore", "canopy-planner", "canopy-worker")
    assert found.error is None
    assert (found.servers, found.disabled_servers) == (("github", "sentry.io"), ("sentry.io",))
    assert found.skills == ("customize-opencode", "tracker-github", "tracker-jira")
    chore, planner, worker = found.agents
    assert chore == AgentOffer(
        "canopy-chore",
        # `sentry.io`'s tools are named `sentry_io_*`, and `*create*` could match one of them.
        servers=(ServerOffer("github", "none"), ServerOffer("sentry.io", "some", ("deny *create*",))),
        skills=("tracker-github", "tracker-jira"),
        denied_skills=("customize-opencode",),
    )
    assert planner.servers[0] == ServerOffer("github", "some", ("offer github_issue_read",))
    # The skill tool denied whole: no skill reaches the agent.
    assert (planner.skills, planner.denied_skills) == ((), found.skills)
    assert worker.servers == (ServerOffer("github", "all"), ServerOffer("sentry.io", "all"))
    # Every command started where a run starts, with canopy's definitions as OpenCode's config directory.
    assert {(cwd, tuple(sorted((env or {}).items()))) for _, cwd, env in debug.ran} == {
        (Path("/ws"), (("OPENCODE_CONFIG_DIR", "/defs"),)),
    }


def test_a_later_rule_wins_over_an_earlier_one() -> None:
    debug = Debug({"canopy-worker": [rule("github_*"), rule("github_*", "allow"), rule("*_delete_*")]})
    [worker] = offered(debug, "canopy-worker").agents
    assert worker.servers[0] == ServerOffer("github", "some", ("deny *_delete_*",))


def test_a_deny_of_some_patterns_only_keeps_the_tool_offered() -> None:
    # OpenCode keeps a tool from an agent only for a deny whose pattern is `*`: any other is a call it then refuses.
    rules = [rule("github_*", pattern="secret*"), rule("skill", pattern="tracker-*", action="ask")]
    debug = Debug({"canopy-worker": rules})
    [worker] = offered(debug, "canopy-worker").agents
    assert worker.servers[0] == ServerOffer("github", "all")
    assert worker.denied_skills == ()


@pytest.mark.parametrize(
    ("text", "pattern", "matched"),
    [
        ("github_issue_read", "github_*", True),
        ("github_issue_read", "*issue*", True),
        ("github_issue_read", "jira_*", False),
        ("github_issue_read", "github_issue_rea?", True),
        ("github.issue", "github?issue", True),
        ("githubxissue", "github.issue", False),  # `.` is literal
        ("canopy health", "canopy health *", True),  # a trailing ` *` matches without the space too
        ("canopy healthy", "canopy health *", False),
        ("a\nb", "a*", True),
    ],
)
def test_patterns_match_as_opencode_matches_them(text: str, pattern: str, *, matched: bool) -> None:
    assert matches(text, pattern) is matched


def test_a_debug_command_that_fails_is_the_error_and_names_no_secret() -> None:
    def fail(args: Sequence[str]) -> procs.Result | None:
        if args[-1] == "canopy-worker":
            return procs.Result(tuple(args), 1, "", "Error: bad config: token = ghp_s3cret\n")
        return None

    found = offered(Debug({"canopy-chore": []}, fail=fail), "canopy-chore", "canopy-worker")
    assert found.agents[0].error is None
    assert "s3cret" not in str(found)
    assert found.agents[1] == AgentOffer(
        "canopy-worker",
        error="`opencode debug agent canopy-worker` exited 1; run it to see why",
    )
    unreadable = offered(Debug({}, config={"mcp": {"github": {"enabled": "token-abc"}}}))
    assert unreadable.error == "`opencode debug config` printed what canopy cannot read"
    assert unreadable.agents == ()


@pytest.mark.parametrize(
    "around",
    [
        ("[corp-plugin] loaded v2.1\nhooks ready {\n", ""),
        ("", "[corp-plugin] flushed 3 events\n[ unclosed\n"),
        ('{"level": "info", "msg": "corp-plugin up"}\n[1, 2]\n', '{"mcp": {}, "permission": []}\n'),
    ],
    ids=["before", "after", "json-lines-around"],
)
def test_what_a_plugin_prints_around_opencode_s_output_is_passed_over(around: tuple[str, str]) -> None:
    rules = {"canopy-worker": [rule("github_*")]}
    clean = offered(Debug(rules), "canopy-worker")
    assert clean.agents[0].servers[0] == ServerOffer("github", "none")
    assert offered(Debug(rules, around=around), "canopy-worker") == clean


def test_a_plugin_s_output_alone_is_not_opencode_s() -> None:
    def plugin_only(args: Sequence[str]) -> procs.Result | None:
        return procs.Result(tuple(args), 0, '[corp-plugin] loaded\n{"level": "info"}\n{"mcp": {}}\n', "")

    assert offered(Debug({}, fail=plugin_only)).error == "`opencode debug config` printed what canopy cannot read"


def test_opencode_missing_or_slow_is_the_error() -> None:
    def missing(args: Sequence[str]) -> procs.Result | None:
        raise procs.CommandNotFoundError(args[0])

    assert offered(Debug({}, fail=missing)).error == "opencode is not on PATH"

    def slow(args: Sequence[str]) -> procs.Result | None:
        return procs.Result(tuple(args), -9, "", "", timed_out=True)

    assert offered(Debug({}, fail=slow)).error == (
        f"`opencode debug config` took over {offerings.TIMEOUT_SECONDS} seconds"
    )


def test_a_run_is_asked_about_as_its_own_command_starts_opencode() -> None:
    debug = Debug(
        {"canopy-chore": [rule("github_*"), rule("github_issue_read", "allow"), rule("skill", pattern="tr*")]},
    )
    argv = ("canopy-sandbox", "chore", "env", "OPENCODE_CONFIG_DIR=/defs", "/usr/bin/opencode", "run")
    found = offerings.offered(
        debug,
        (*argv, "--agent=canopy-chore", "--format", "json", "Say ok."),
        cwd=Path("/run"),
        env={"CANOPY_RUN_ID": "7"},
    )
    # The server its config turns off is offered to no run, so it is not among them.
    assert found == AgentOffer(
        "canopy-chore",
        servers=(ServerOffer("github", "some", ("offer github_issue_read",)),),
        skills=("customize-opencode",),
        denied_skills=("tracker-github", "tracker-jira"),
    )
    # `opencode run` and what follows it swapped for each debug command, inside what wraps it, where the run starts.
    assert debug.ran == [
        ((*argv[:-1], "debug", *command), Path("/run"), {"CANOPY_RUN_ID": "7"})
        for command in (("config",), ("skill",), ("agent", "canopy-chore"))
    ]


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
    debug = Debug({})
    assert offerings.offered(debug, argv, cwd=Path("/run"), env={}) == AgentOffer("", error=error)
    assert debug.ran == []


def test_a_run_the_runtime_cannot_say_about_has_only_its_error() -> None:
    def fail(args: Sequence[str]) -> procs.Result | None:
        return procs.Result(tuple(args), 1, "", "") if args[-1] == "skill" else None

    found = offerings.offered(
        Debug({}, fail=fail),
        ("opencode", "run", "--agent", "canopy-worker"),
        cwd=Path("/run"),
        env={},
    )
    assert found == AgentOffer("canopy-worker", error="`opencode debug skill` exited 1; run it to see why")


def test_an_agent_is_offered_the_built_in_tools_opencode_says_it_keeps() -> None:
    debug = Debug({"canopy-reviewer": []}, tools={"invalid": True, "read": True, "bash": False, "glob": True})
    [reviewer] = offered(debug, "canopy-reviewer").agents
    # `invalid` stands in for a call to a tool OpenCode does not have, and no request carries it.
    assert reviewer.tools == ("glob", "read")
