"""What any runtime reports, built the same way whatever printed it: the model calls' total and the tools' rollup."""

from canopy.runtime import report
from canopy.runtime.report import Call, ToolUse, Usage


def test_the_calls_total_is_their_sum_with_the_peak_and_the_first_call() -> None:
    calls = [Call(0.25, 100, 20, 3, 400, 50), Call(0.5, 10, 5, 0, 900, 0)]
    assert report.total(calls) == Usage(
        cost_usd=0.75,
        input=110,
        output=25,
        reasoning=3,
        cache_read=1300,
        cache_write=50,
        peak_context=910,
        first_call=550,
        first_cache_write=50,
        first_cache_read=400,
    )


def test_no_call_costs_nothing_and_has_no_first_call() -> None:
    assert report.total([]) == Usage(0, 0, 0, 0, 0, 0, peak_context=0, first_call=None, first_cache_write=None)
    assert report.total([]).first_cache_read is None


def test_tool_calls_are_rolled_up_by_tool_with_what_they_returned() -> None:
    tools = report.Tools()
    tools.add("bash", error=False, said="12345")
    tools.add("read", error=False, said=None)
    tools.add("bash", error=True, said="no")
    assert tools.rolled_up == (ToolUse("bash", calls=2, errors=1, result_chars=7), ToolUse("read", 1, 0, 0))


def test_a_tools_name_is_one_printable_line_and_their_number_is_bounded() -> None:
    tools = report.Tools()
    for name in ("evil\x1b[31m\n tool", "", "t" * 500, *(f"mcp_{i}" for i in range(report.MAX_TOOLS + 5))):
        tools.add(name, error=False, said="a")
    rolled = tools.rolled_up
    assert [t.tool for t in rolled[:3]] == ["evil[31m tool", "?", "t" * report.MAX_TOOL_NAME]
    assert len(rolled) == report.MAX_TOOLS + 1
    # The calls of every tool past the bound count together, under a name no runtime gives a tool.
    assert rolled[-1] == ToolUse(report.OTHER_TOOLS, calls=8, errors=0, result_chars=8)


def test_a_session_id_is_one_canopy_prints() -> None:
    assert report.session_id("ses_abc-123") == "ses_abc-123"
    for bad in ("bad id!", "", "x" * 101, 7, None):
        assert report.session_id(bad) is None


def test_a_shell_command_searches_when_a_stage_of_it_starts_a_search() -> None:
    """By each stage's first word, past any variables it sets: a measurement's reading, never a guard's."""
    for command in (
        "rg parse src",
        "grep -rn TODO .",
        "cd src && rg parse",
        "LC_ALL=C grep -r x .",
        "find . -name '*.py' | head",
        "git grep -n parse",
        "git ls-files src",
        "/usr/bin/fd parse",
        "cat a|grep x",
        "ls\nrg x",
    ):
        assert report.shell_searches(command), command
    quoted = ('echo "a; grep x"', "echo 'a | rg b'", 'grep "unclosed', "uv run pytest 2>&1 | tail")
    for command in ("uv run pytest -q", "git status", "cat src/a.py", "xargs grep x", "echo grep", "", *quoted):
        assert not report.shell_searches(command), command


def test_a_shell_commands_stages_are_its_words_split_as_the_shell_splits_them() -> None:
    """Past the variables each sets, line by line; a line whose quotes do not close has none."""
    assert report.shell_stages("cd web && LC_ALL=C gh run view 7 | tail -n 5\nls") == [
        ["cd", "web"],
        ["gh", "run", "view", "7"],
        ["tail", "-n", "5"],
        ["ls"],
    ]
    assert report.shell_stages('echo "a; b"; X=1') == [["echo", "a; b"]]
    assert report.shell_stages('grep "unclosed\nls') == [["ls"]]


def test_a_kept_name_is_one_printable_line_within_its_bound() -> None:
    assert report.kept_name("evil\x1b[31m\n tool") == "evil[31m tool"
    assert report.kept_name("") == "?"
    assert report.kept_name("t" * 500) == "t" * report.MAX_TOOL_NAME


def test_a_sessions_title_is_one_line_with_nothing_hidden_within_its_bound() -> None:
    assert report.session_title("  Fix the\r\nflaky\u2028test\u200d\u202e ") == "Fix the flaky test"
    assert report.session_title("\x00\u200b") is None
    assert report.session_title(7) is None
    assert report.session_title("a " * 300) == ("a " * 100).strip()
