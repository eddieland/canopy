"""The web UI's system resources page: the machine the loop runs on, read from the operating system."""

import asyncio
import contextlib
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from canopy.core.context import Context
from canopy.serve import host, mock
from canopy.serve.schema.host import HostResources
from tests.canopy.web_helpers import client, signed_in_client

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
BOOT = 1_791_000_000
GIB = 1024**3


def fake_proc(root: Path) -> Path:
    """A `/proc` with what the reader reads of it: memory, boot time, and this process's status, start, and files."""
    (root / "self" / "fd").mkdir(parents=True)
    # Three the process holds, and the one listing the directory opens, which the kernel lists too.
    for fd in ("0", "1", "2", "3"):
        (root / "self" / "fd" / fd).touch()
    (root / "meminfo").write_text(
        "MemTotal:       16384000 kB\nMemFree:  100 kB\nMemAvailable:    4096000 kB\n"
        "SwapTotal:       2048000 kB\nSwapFree:        1024000 kB\n",
    )
    (root / "stat").write_text(f"cpu  1 2 3 4\nbtime {BOOT}\nprocesses 99\n")
    (root / "self" / "status").write_text("Name:\tcanopy\nVmRSS:\t  204800 kB\nThreads:\t7\n")
    # Its name holds a space and a parenthesis, which the fields after it are counted past. Its 22nd field says it
    # started 100 clock ticks after the machine did.
    (root / "self" / "stat").write_text(f"42 (can opy) ) S {' '.join(['0'] * 18)} 100 0\n")
    return root


def test_it_reads_the_machine_from_proc(tmp_path: Path) -> None:
    proc = fake_proc(tmp_path / "proc")

    found = host.read_at([("workspace", tmp_path)], proc=proc, now=NOW)

    assert found.read_at == NOW
    assert found.booted_at == datetime.fromtimestamp(BOOT, UTC)
    assert (found.memory.total, found.memory.available) == (16384000 * 1024, 4096000 * 1024)
    assert (found.memory.swap_total, found.memory.swap_free) == (2048000 * 1024, 1024000 * 1024)
    assert (found.process.rss, found.process.threads, found.process.open_files) == (204800 * 1024, 7, 3)
    assert found.process.started_at is not None
    assert found.process.started_at.timestamp() - BOOT == 100 / os.sysconf("SC_CLK_TCK")


def test_off_linux_what_only_proc_says_is_none(tmp_path: Path) -> None:
    found = host.read_at([("workspace", tmp_path)], proc=tmp_path / "no-proc", now=NOW)

    assert (found.booted_at, found.memory.available, found.memory.swap_total) == (None, None, None)
    assert (found.process.started_at, found.process.rss, found.process.open_files) == (None, None, None)
    # What the standard library gives everywhere is still there.
    assert found.memory.total is not None
    assert found.process.threads >= 1


def test_uses_on_one_filesystem_share_a_disk_and_a_missing_one_is_left_out(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()

    [disk] = host.disks(
        [
            ("workspace", tmp_path),
            ("journal", tmp_path / "state"),
            ("temp", tmp_path / "gone"),
        ],
        floor=GIB,
    )

    assert (disk.holds, disk.path, disk.floor) == (["workspace", "journal"], str(tmp_path), GIB)
    assert 0 <= disk.free <= disk.total


def test_the_ticks_floor_is_on_the_disks_it_checks_alone(tmp_path: Path) -> None:
    [disk] = host.disks([("temp", tmp_path)], floor=GIB)

    assert disk.floor is None


def test_the_page_reads_the_machine_the_loop_runs_on(ctx: Context) -> None:
    c, _ = signed_in_client(ctx)

    found = c.get("/api/host").json()

    assert found["disks"][0]["holds"][0] == "workspace"
    assert found["disks"][0]["path"] == str(ctx.workspace.root)
    assert found["disks"][0]["floor"] == 2048 * 1024 * 1024
    assert found["process"]["threads"] >= 1


def test_the_mock_shows_a_fixed_machine_never_its_host(tmp_path: Path) -> None:
    c = client(None, mock.seed(tmp_path / "mock"))

    found = c.get("/api/host").json()

    assert (found["hostname"], found["cpu"]["cores"], found["read_at"]) == ("build-box", 12, "2026-10-08T12:30:00Z")
    assert [d["holds"] for d in found["disks"]] == [["workspace", "journal"], ["temp"]]
    assert found["memory"]["total"] == 64 * GIB


def test_the_server_keeps_the_last_readings_oldest_first(tmp_path: Path) -> None:
    samples = host.Samples(kept=2, every=5)
    reads = [_reading(tmp_path, NOW + timedelta(seconds=5 * i)) for i in range(3)]

    for found in reads:
        samples.add(found)

    kept = samples.history()
    assert (kept.every_seconds, kept.kept) == (5, 2)
    assert [s.at for s in kept.samples] == [reads[1].read_at, reads[2].read_at]


def test_a_sample_is_what_the_graphs_draw_of_a_reading(tmp_path: Path) -> None:
    found = _reading(tmp_path, NOW)

    taken = host.sample(found)

    assert taken.load == 1.5
    assert taken.memory_used == (16384000 - 4096000) * 1024
    assert taken.rss == 204800 * 1024
    assert [(d.path, d.free) for d in taken.disks] == [(d.path, d.free) for d in found.disks]


def test_the_sampler_reads_until_cancelled_and_skips_any_read_that_fails(tmp_path: Path) -> None:
    samples = host.Samples(every=0)
    calls = 0
    # Set as the sixth read starts: the sampler starts it once it kept the fifth's, the third that succeeded.
    read_enough = threading.Event()

    def read_now() -> HostResources:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("gone")
        if calls == 3:
            raise ValueError("not a number")
        if calls >= 6:
            read_enough.set()
        return _reading(tmp_path, NOW + timedelta(seconds=calls))

    async def run() -> None:
        task = asyncio.create_task(host.sampling(read_now, samples))
        assert await asyncio.to_thread(read_enough.wait, 5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(run())

    kept = samples.history().samples
    assert len(kept) >= 3
    # The second and third reads failed, the one with an error of its own as well, so the second sample is the fourth's.
    assert kept[1].at == NOW + timedelta(seconds=4)


def test_the_server_reads_the_machine_into_memory_from_when_it_starts(ctx: Context) -> None:
    c, _ = signed_in_client(ctx)

    with c:
        deadline = time.monotonic() + 10
        found = c.get("/api/host/samples").json()
        while not found["samples"] and time.monotonic() < deadline:
            time.sleep(0.05)
            found = c.get("/api/host/samples").json()

    assert (found["every_seconds"], found["kept"]) == (host.SAMPLE_SECONDS, host.KEPT)
    [first, *_] = found["samples"]
    assert first["disks"][0]["path"] == str(ctx.workspace.root)


def test_the_mock_serves_a_fixed_hour_ending_with_its_machine(tmp_path: Path) -> None:
    c = client(None, mock.seed(tmp_path / "mock"))

    found = c.get("/api/host/samples").json()

    samples = found["samples"]
    assert len(samples) == host.KEPT
    assert samples[-1]["at"] == "2026-10-08T12:30:00Z"
    assert samples[-1]["load"] == 2.41
    assert [d["path"] for d in samples[0]["disks"]] == ["/home/operator/acme", "/tmp"]  # noqa: S108


def _reading(tmp_path: Path, now: datetime) -> HostResources:
    proc = tmp_path / "proc"
    if not proc.exists():
        fake_proc(proc)
    found = host.read_at([("workspace", tmp_path)], proc=proc, now=now)
    return found.model_copy(update={"cpu": found.cpu.model_copy(update={"load": [1.5, 1.0, 0.5]})})
