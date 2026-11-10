"""The mock's machine, for the system resources page of `python -m canopy.serve --mock`.

A fixed reading, never the host's: the pages show the same machine on every run, and the public demo (demo.py) tells
nobody about the machine it runs on. Every figure is one canopy reads on Linux, so the page shows them all, and it is
caught mid-build, so the page shows each pressure once beside a calm resource: the temporary directory red, under a
gigabyte free; the memory amber, under 15% available; the load amber and rising, past every core over five minutes;
and the workspace's and journal's disk calm. That disk stays far above the tick's floor, since under it no tick runs
the overseer and the mock's journal shows ticks running: the red disk is the temporary directory, which has no floor.

Its hour of readings (`samples`) tells the same story: run 41's build starts twelve minutes before the last reading,
the load, the processors, and the memory climb with it, the temporary directory drains as the build fills it, and the
stalls rise. Its processes (`processes`) are a fixed list too: the loop, its two running runs' agents, one of them
compiling, the two compilers holding most of the memory the build took, a search waiting on a disk, and what else a
build box keeps.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from canopy.serve import host
from canopy.serve.schema.host import (
    Cpu,
    CpuTime,
    Disk,
    DiskSample,
    HostProcess,
    HostProcesses,
    HostResources,
    HostSample,
    LoopProcess,
    Memory,
    ProcessState,
    Stalls,
)

_GIB = 1024**3
_MIB = 1024**2
#: The minutes before the last reading run 41's build started: it is still running at the last reading.
_BUILD_START = 12
#: The minutes the build takes, from its start, to keep every core busy.
_BUILD_RAMP = 4
#: The share of the cores the mock's processors keep busy while no build runs.
_IDLE_BUSY = 0.15
#: The share of the cores busy at the last reading, the build at full tilt.
_BUILD_BUSY = 0.91
#: The mock's cores.
_CORES = 12
#: How long the mock's machine has been up.
_UP = timedelta(days=9, hours=4)
#: The time between two readings.
_STEP = timedelta(seconds=host.SAMPLE_SECONDS)
#: The loop's process id, which its process and the processes' list share.
_LOOP = 48213
#: The pids of the running runs' processes in `_PROCESSES`, by run id: the run's own, then its agent's, as the mock's
#: journal records them, so the page ties each to its run.
RUN_PIDS: dict[int, tuple[int, int]] = {41: (50110, 50128), 43: (50140, 50152)}
#: The mock's processes, parent first: pid, parent, name, user, state, processors kept busy, memory in MiB, threads,
#: minutes since it started, and command line. Runs 41 and 43 are running in its journal, started 30 and 25 minutes
#: before the reading; 41's agent is compiling, its two `rustc` holding most of the memory the build took.
_PROCESSES: tuple[tuple[int, int, str, str, ProcessState, float, int, int, int, str], ...] = (
    (1, 0, "systemd", "root", "sleeping", 0.002, 14, 1, 13200, "/sbin/init splash"),
    (612, 1, "systemd-journal", "root", "sleeping", 0.004, 48, 1, 13200, "/usr/lib/systemd/systemd-journald"),
    (880, 1, "sshd", "root", "sleeping", 0.0, 9, 1, 13199, "sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups"),
    (41022, 880, "sshd", "root", "sleeping", 0.0, 11, 1, 195, "sshd: operator [priv]"),
    (41040, 41022, "sshd", "operator", "sleeping", 0.001, 7, 1, 195, "sshd: operator@pts/0"),
    (41041, 41040, "bash", "operator", "sleeping", 0.0, 5, 1, 195, "-bash"),
    (
        _LOOP,
        41041,
        "canopy",
        "operator",
        "sleeping",
        0.031,
        268,
        19,
        192,
        "/home/operator/.local/share/uv/tools/canopy/bin/python /home/operator/.local/bin/canopy loop",
    ),
    (
        50110,
        _LOOP,
        "python3",
        "operator",
        "sleeping",
        0.002,
        61,
        3,
        30,
        "/home/operator/.local/share/uv/tools/canopy/bin/python -m canopy _run 41",
    ),
    (50128, 50110, "opencode", "operator", "sleeping", 0.118, 412, 22, 30, "opencode run --agent canopy-worker"),
    (50311, 50128, "bash", "operator", "sleeping", 0.0, 4, 1, 12, "/bin/bash -c cargo test --workspace"),
    (50312, 50311, "cargo", "operator", "sleeping", 0.046, 151, 9, 12, "cargo test --workspace"),
    (
        50398,
        50312,
        "rustc",
        "operator",
        "running",
        5.62,
        9420,
        14,
        6,
        "rustc --crate-name api --edition=2021 src/lib.rs --test -C opt-level=0 -C debuginfo=2",
    ),
    (
        50401,
        50312,
        "rustc",
        "operator",
        "running",
        4.81,
        6610,
        12,
        5,
        "rustc --crate-name api_server --edition=2021 src/main.rs --test -C opt-level=0 -C debuginfo=2",
    ),
    (
        50140,
        _LOOP,
        "python3",
        "operator",
        "sleeping",
        0.001,
        58,
        3,
        25,
        "/home/operator/.local/share/uv/tools/canopy/bin/python -m canopy _run 43",
    ),
    (50152, 50140, "opencode", "operator", "sleeping", 0.036, 377, 21, 25, "opencode run --agent canopy-worker"),
    (50290, 50152, "rg", "operator", "disk", 0.012, 22, 1, 0, "rg --line-number --hidden retry_after src"),
    (1203, 1, "dockerd", "root", "sleeping", 0.009, 96, 31, 13198, "/usr/bin/dockerd -H fd://"),
    (
        1310,
        1,
        "postgres",
        "postgres",
        "sleeping",
        0.003,
        41,
        1,
        13198,
        "/usr/lib/postgresql/16/bin/postgres -D /var/lib/postgresql/16/main",
    ),
    (1315, 1310, "postgres", "postgres", "sleeping", 0.001, 9, 1, 13198, "postgres: 16/main: walwriter"),
    (
        2001,
        41041,
        "node",
        "operator",
        "sleeping",
        0.011,
        183,
        11,
        180,
        "node /home/operator/acme/web/node_modules/.bin/vite --port 5173",
    ),
)


def machine(now: datetime) -> HostResources:
    """The mock's machine as read at `now`.

    Returns:
        A 12-core Linux box mid-build, with the workspace and journal on one disk, calm, and the temporary directory on
        another, nearly full.
    """
    before = _time(_UP - _STEP)
    step = _STEP.total_seconds() * _CORES
    return HostResources(
        hostname="build-box",
        system="Linux 6.8.0",
        machine="x86_64",
        python="3.13.1",
        booted_at=now - _UP,
        read_at=now,
        # Past every core over five minutes, and rising: the last minute's well over the last quarter hour's.
        cpu=Cpu(
            cores=_CORES,
            load=[14.62, 13.71, 8.94],
            time=CpuTime(busy=before.busy + step * _BUILD_BUSY, total=before.total + step),
        ),
        # 11% available: under the 15% the page calls worth a look, short of the 5% it calls critical.
        memory=Memory(
            total=64 * _GIB,
            available=7 * _GIB + 300 * _MIB,
            swap_total=8 * _GIB,
            swap_free=6 * _GIB + 410 * _MIB,
        ),
        stalled=Stalls(memory=0.03, io=0.094),
        disks=[
            Disk(
                holds=["workspace", "journal"],
                path="/home/operator/acme",
                total=931 * _GIB,
                free=412 * _GIB,
                floor=2 * _GIB,
            ),
            # Under a gigabyte free, which the page calls critical on any disk: the build filled it over the hour.
            Disk(holds=["temp"], path="/tmp", total=32 * _GIB, free=768 * _MIB, floor=None),  # noqa: S108
        ],
        process=LoopProcess(
            pid=_LOOP,
            started_at=now - timedelta(hours=3, minutes=12),
            rss=268 * _MIB,
            peak_rss=412 * _MIB,
            threads=19,
            open_files=61,
            max_open_files=65536,
        ),
    )


def processes(now: datetime) -> HostProcesses:
    """The mock's processes as read at `now`, measured over the ten seconds before.

    Returns:
        A build box's: the loop, its two running runs' agents with a compile under one and a search waiting on a disk
        under the other, and a few services.
    """
    return HostProcesses(
        read_at=now,
        over_seconds=10.0,
        processes=[
            HostProcess(
                pid=pid,
                parent=parent,
                name=name,
                command=command,
                user=user,
                state=state,
                cpu=cpu,
                rss=mib * _MIB,
                threads=threads,
                started_at=now - timedelta(minutes=minutes),
            )
            for pid, parent, name, user, state, cpu, mib, threads, minutes, command in sorted(_PROCESSES)
        ],
    )


def samples(now: datetime) -> host.Samples:
    """The mock's hour of readings, ending with `machine(now)`'s.

    Returns:
        A full hour, every `host.SAMPLE_SECONDS`, of a quiet machine until a build starts 12 minutes before the last:
        the load and the processors climb to every core within minutes and keep climbing, the memory and its stalls
        grow as the compilers do, the swap takes what memory cannot hold, the temporary directory drains from 27 GiB
        to under one as the build fills it, the workspace's disk gives up what the build writes there, and the loop's
        own memory climbs slowly, as a long-lived process's does.
    """
    last = machine(now)
    readings = [_reading(now, i) for i in range(host.KEPT - 1, 0, -1)]
    return host.Samples(seeded=[*readings, host.sample(last, _time(_UP - _STEP))])


def _time(up: timedelta) -> CpuTime:
    # The processors' time after `up`, busy at the idle share throughout: the build's is not counted, nor need it be,
    # since only the last reading is measured against the one before it, and `machine` adds that step at the build's.
    total = up.total_seconds() * _CORES
    return CpuTime(busy=total * _IDLE_BUSY, total=total)


def _reading(now: datetime, back: int) -> HostSample:
    # `back` readings before the last: a smooth wobble, plus the build's share of its time so far, `grown`, from 0 at
    # its start to 1 at the last reading, and `full`, from 0 to 1 as it comes to keep every core busy. Each figure
    # climbs to `machine`'s at the last reading.
    minutes = back * host.SAMPLE_SECONDS / 60
    into = max(0.0, _BUILD_START - minutes)
    grown = into / _BUILD_START
    full = min(1.0, into / _BUILD_RAMP)
    wobble = math.sin(back / 7) * 0.35 + math.sin(back / 23) * 0.25
    # The temporary directory: 27.3 GiB free an hour ago, a little taken before the build, then drained by it, faster
    # as it goes, to the last reading's 0.75 GiB.
    before = min(1.0, (60 - minutes) / (60 - _BUILD_START))
    temp = 27.3 - 0.9 * before - 25.65 * grown**1.3
    return HostSample(
        at=now - timedelta(seconds=back * host.SAMPLE_SECONDS),
        load=round(max(0.2, 1.9 + wobble + 11.4 * full + 1.3 * grown), 2),
        cpu_busy=round(_IDLE_BUSY + wobble * 0.06 + (_BUILD_BUSY - _IDLE_BUSY) * full, 4),
        memory_used=int((40.6 + wobble * 0.8 + 16.1 * grown) * _GIB),
        # What memory could not hold went to swap.
        swap_used=int((0.85 + 0.75 * grown) * _GIB),
        memory_stalled=round(0.03 * grown, 4),
        io_stalled=round(0.004 + abs(wobble) * 0.004 + 0.09 * full, 4),
        rss=int((268 - minutes * 0.45 + (back % 31) * 0.3) * _MIB),
        disks=[
            # The build writes to the workspace too: 1.6 GiB more was free before it.
            DiskSample(path="/home/operator/acme", free=int((412 + 1.6 * (1 - grown)) * _GIB)),
            DiskSample(path="/tmp", free=int(temp * _GIB)),  # noqa: S108
        ],
    )
