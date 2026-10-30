"""The system resources page's processes: what keeps the machine busy, read from Linux's `/proc`."""

import os
import pwd
from datetime import UTC, datetime
from pathlib import Path

from canopy.core.context import Context
from canopy.serve import mock, processes
from tests.canopy.web_helpers import client, signed_in_client

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
BOOT = 1_791_000_000
TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


class FakeClock:
    """A monotonic clock that moves only when the watch waits, or the test says."""

    def __init__(self) -> None:
        """Start at a thousand seconds, as a clock that only moves forward may."""
        self.at = 1000.0
        self.waits: list[float] = []

    def __call__(self) -> float:
        """The time now."""
        return self.at

    def wait(self, seconds: float) -> None:
        """Wait `seconds`, at once."""
        self.waits.append(seconds)
        self.at += seconds


def write_process(
    proc: Path,
    pid: int,
    *,
    parent: int = 1,
    name: str = "worker",
    state: str = "S",
    ticks: int = 0,
    rss_pages: int = 0,
    threads: int = 1,
    start: int = 500,
    argv: bytes = b"worker\0",
    flags: int = 0,
) -> None:
    """Write `/proc/<pid>`'s `stat` and `cmdline` as Linux does, its processor time all its own."""
    directory = proc / str(pid)
    directory.mkdir(parents=True, exist_ok=True)
    # Fields 3 to 24: state, parent, four not read, the flags, four more, utime and stime, eight more, the start, vsize,
    # and rss.
    fields = [state, str(parent), *["0"] * 4, str(flags), *["0"] * 4, str(ticks), "0", *["0"] * 4, str(threads), "0"]
    fields += [str(start), "0"]
    (directory / "stat").write_text(f"{pid} ({name}) {' '.join(fields)} {rss_pages} 0 0\n")
    (directory / "cmdline").write_bytes(argv)


def fake_proc(root: Path) -> Path:
    """A `/proc` with the machine's boot time and nothing running."""
    root.mkdir(parents=True)
    (root / "stat").write_text(f"cpu  1 2 3 4\nbtime {BOOT}\n")
    return root


def test_each_process_is_measured_over_a_seconds_wait_on_the_first_read(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path / "proc")
    clock = FakeClock()

    def make(ticks: int) -> None:
        write_process(
            proc,
            10,
            name="build",
            ticks=ticks,
            rss_pages=256,
            threads=4,
            start=TICK * 30,
            argv=b"make\0-j8\0",
        )

    make(50)
    write_process(proc, 11, name="editor", ticks=7)

    def busy_second(seconds: float) -> None:
        clock.wait(seconds)
        # In the second, the build kept two cores busy and the editor none.
        make(50 + 2 * TICK)

    watch = processes.ProcessWatch(proc, clock=clock, wait=busy_second, now=lambda: NOW)

    found = watch.read()

    assert clock.waits == [processes.BASELINE_SECONDS]
    assert (found.read_at, found.over_seconds) == (NOW, 1.0)
    assert found.processes is not None
    build, editor = found.processes
    assert (build.pid, build.parent, build.name, build.command) == (10, 1, "build", "make -j8")
    assert (build.cpu, editor.cpu) == (2.0, 0.0)
    assert (build.rss, build.threads, build.state) == (256 * PAGE, 4, "sleeping")
    assert build.user == pwd.getpwuid(os.getuid()).pw_name
    assert build.started_at == datetime.fromtimestamp(BOOT + 30, UTC)


def test_a_later_read_is_measured_against_the_one_before_without_waiting(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path / "proc")
    clock = FakeClock()
    write_process(proc, 10, ticks=0)
    watch = processes.ProcessWatch(proc, clock=clock, wait=clock.wait, now=lambda: NOW)
    watch.read()

    clock.at += 10
    write_process(proc, 10, ticks=5 * TICK, state="R")
    found = watch.read()

    assert clock.waits == [processes.BASELINE_SECONDS]
    assert found.over_seconds == 10.0
    assert found.processes is not None
    assert [(p.cpu, p.state) for p in found.processes] == [(0.5, "running")]


def test_an_ask_just_after_another_gets_its_answer_and_one_after_a_while_waits_again(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path / "proc")
    clock = FakeClock()
    write_process(proc, 10)
    watch = processes.ProcessWatch(proc, clock=clock, wait=clock.wait, now=lambda: NOW)
    first = watch.read()

    clock.at += 0.5
    assert watch.read() is first

    clock.at += processes.STALE_SECONDS + 1
    watch.read()
    assert clock.waits == [processes.BASELINE_SECONDS, processes.BASELINE_SECONDS]


def test_a_process_that_took_an_ended_ones_pid_counts_its_own_time_alone(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path / "proc")
    clock = FakeClock()
    write_process(proc, 10, ticks=90 * TICK, start=100)
    watch = processes.ProcessWatch(proc, clock=clock, wait=clock.wait, now=lambda: NOW)
    watch.read()

    clock.at += 10
    write_process(proc, 10, ticks=TICK, start=9000)
    found = watch.read()

    assert found.processes is not None
    assert [p.cpu for p in found.processes] == [0.1]


def test_the_kernels_threads_and_what_cannot_be_read_are_left_out(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path / "proc")
    clock = FakeClock()
    kernel = 0x00208040
    write_process(proc, 1, parent=0, name="init")
    write_process(proc, 2, parent=0, name="kthreadd", argv=b"", flags=kernel)
    write_process(proc, 3, parent=2, name="kworker/0:0", state="I", argv=b"", flags=kernel)
    (proc / "4").mkdir()
    (proc / "self").mkdir()
    watch = processes.ProcessWatch(proc, clock=clock, wait=clock.wait, now=lambda: NOW)

    found = watch.read()

    assert found.processes is not None
    assert [p.name for p in found.processes] == ["init"]


def test_in_a_containers_namespace_process_2_and_its_children_are_kept(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path / "proc")
    clock = FakeClock()
    # An init such as tini is process 1, and the program it starts, the loop's shell here, process 2.
    write_process(proc, 1, parent=0, name="tini")
    write_process(proc, 2, parent=1, name="bash")
    write_process(proc, 7, parent=2, name="canopy")
    watch = processes.ProcessWatch(proc, clock=clock, wait=clock.wait, now=lambda: NOW)

    found = watch.read()

    assert found.processes is not None
    assert [p.name for p in found.processes] == ["tini", "bash", "canopy"]


def test_a_name_and_a_command_line_are_kept_to_one_line_of_text(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path / "proc")
    clock = FakeClock()
    # A name may hold spaces and parentheses; an argument a newline, an escape, or bytes that are not UTF-8.
    long = b"x" * 1000
    write_process(proc, 10, name="my (odd) name", state="Z", argv=b"sh\0-c\0echo hi\n\x1b[2J\xff\0" + long + b"\0\0")
    watch = processes.ProcessWatch(proc, clock=clock, wait=clock.wait, now=lambda: NOW)

    found = watch.read()

    assert found.processes is not None
    [process] = found.processes
    assert (process.name, process.state) == ("my (odd) name", "zombie")
    assert process.command.startswith("sh -c echo hi  [2J� xxx")
    assert len(process.command) == processes.COMMAND_CHARS


def test_off_linux_no_process_is_read(tmp_path: Path) -> None:
    watch = processes.ProcessWatch(tmp_path / "no-proc", now=lambda: NOW)

    found = watch.read()

    assert (found.read_at, found.over_seconds, found.processes) == (NOW, None, None)


def test_the_page_reads_the_processes_of_the_machine_the_loop_runs_on(ctx: Context) -> None:
    c, _ = signed_in_client(ctx)

    found = c.get("/api/host/processes").json()

    assert found["over_seconds"] is not None
    assert os.getpid() in [p["pid"] for p in found["processes"]]


def test_the_mock_shows_fixed_processes_never_its_hosts(tmp_path: Path) -> None:
    c = client(None, mock.seed(tmp_path / "mock"))

    found = c.get("/api/host/processes").json()
    loop = c.get("/api/host").json()["process"]["pid"]

    by_pid = {p["pid"]: p for p in found["processes"]}
    assert (found["read_at"], found["over_seconds"]) == ("2026-10-08T12:30:00Z", 10.0)
    assert by_pid[loop]["name"] == "canopy"
    assert os.getpid() not in by_pid
