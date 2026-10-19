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
    )


def test_no_call_costs_nothing_and_has_no_first_call() -> None:
    assert report.total([]) == Usage(0, 0, 0, 0, 0, 0, peak_context=0, first_call=None, first_cache_write=None)


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
