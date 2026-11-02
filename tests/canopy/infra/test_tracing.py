"""Tracing: off and free until configured, then each span appended to the traces file as OTLP JSON."""

import json
import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from canopy.infra import procs, tracing

TRACE = "0af7651916cd43dd8448eb211c80319c"
PARENT = "b7ad6b7169203331"


@pytest.fixture
def traced(tmp_path: Path) -> Iterator[Path]:
    """Tracing on, to the traces file in `tmp_path`, which it yields, and off again when the test ends."""
    tracing.configure(tmp_path, "file")
    yield tmp_path / tracing.TRACES_FILE_NAME
    tracing.configure(tmp_path, "off")


def spans(path: Path) -> list[dict[str, object]]:
    """Each span in the traces file, in the order written, with its attributes as a plain dict."""
    found: list[dict[str, object]] = []
    for line in path.read_text().splitlines():
        for resource in json.loads(line)["resourceSpans"]:
            for scope in resource["scopeSpans"]:
                for span in scope["spans"]:
                    values = {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}
                    found.append({**span, "attributes": values})
    return found


def test_a_span_while_tracing_is_off_records_nothing_and_loads_no_opentelemetry(tmp_path: Path) -> None:
    with tracing.span("tick", tick_id=1) as traced:
        traced.set(status="ok")
    assert tracing.carrier() == {}
    assert not (tmp_path / tracing.TRACES_FILE_NAME).exists()
    # In a process of its own, as this one may have loaded it for another test: opening canopy's modules loads none.
    probe = (
        "import sys; import canopy.cli.main, canopy.core.context, canopy.loop.tick; "
        "print(any(m.startswith('opentelemetry') for m in sys.modules))"
    )
    ran = procs.SubprocessRunner().run([sys.executable, "-c", probe], cwd=tmp_path, timeout=60)
    assert ran.stdout.strip() == "False"


def test_spans_nest_and_are_written_as_otlp_json(traced: Path) -> None:
    with tracing.span("tick", tick_id=7, dry_run=False, woken_by=None) as tick:
        with tracing.span("state"):
            pass
        tick.set(status="ok", cost_usd=0.25)
    state, tick_span = spans(traced)
    assert (state["name"], tick_span["name"]) == ("state", "tick")
    assert state["traceId"] == tick_span["traceId"]
    assert state["parentSpanId"] == tick_span["spanId"]
    assert "parentSpanId" not in tick_span
    # Named canopy's own, typed as OTLP types them, and None left out.
    assert tick_span["attributes"] == {
        "canopy.tick_id": "7",
        "canopy.dry_run": False,
        "canopy.status": "ok",
        "canopy.cost_usd": 0.25,
    }
    assert tick_span["kind"] == 1
    assert int(str(tick_span["endTimeUnixNano"])) >= int(str(tick_span["startTimeUnixNano"])) > 0
    assert stat.S_IMODE(traced.stat().st_mode) == 0o600


def test_a_span_that_raises_is_failed_with_its_exceptions_type_alone(traced: Path) -> None:
    with pytest.raises(ValueError, match="secret"), tracing.span("overseer"):
        raise ValueError("a PR body's secret")
    [span] = spans(traced)
    assert span["status"] == {"code": 2, "message": "ValueError"}
    assert "secret" not in traced.read_text()


def test_a_child_continues_the_trace_its_parent_passed(tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {tracing.TRACEPARENT: f"00-{TRACE}-{PARENT}-01"}):
        tracing.configure(tmp_path, "file")
        with tracing.span("run", run_id=3):
            carried = tracing.carrier()
    [run] = spans(tmp_path / tracing.TRACES_FILE_NAME)
    assert (run["traceId"], run["parentSpanId"]) == (TRACE, PARENT)
    # What it passes on names its own span, in the same trace.
    assert carried[tracing.TRACEPARENT].startswith(f"00-{TRACE}-{run['spanId']}-")


def test_a_process_canopy_starts_carries_the_current_span(traced: Path, tmp_path: Path) -> None:
    printed = [sys.executable, "-c", "import os; print(os.environ.get('TRACEPARENT', ''))"]
    with tracing.span("spawn"):
        ran = procs.SubprocessRunner().run(printed, cwd=tmp_path, timeout=60)
    [span] = spans(traced)
    assert ran.stdout.strip().startswith(f"00-{span['traceId']}-{span['spanId']}-")


def test_configuring_again_alike_keeps_the_trace_and_off_stops_it(traced: Path, tmp_path: Path) -> None:
    with tracing.span("tool"):
        tracing.configure(tmp_path, "file")
    tracing.configure(tmp_path, "off")
    with tracing.span("after"):
        pass
    assert [s["name"] for s in spans(traced)] == ["tool"]
