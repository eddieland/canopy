"""The mock's machine, for the system resources page of `python -m canopy.serve --mock`.

A fixed reading, never the host's: the pages show the same machine on every run, and the public demo (demo.py) tells
nobody about the machine it runs on. Every figure is one canopy reads on Linux, so the page shows them all, and none
is under pressure, so the header's readout is calm. Its hour of readings (`samples`) is as fixed: a build ran twenty
minutes before, so the graphs have a shape to show. Its processes (`processes`) are a fixed list too: the loop,
its two running runs' agents, one of them compiling, and what else a build box keeps.
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
#: The minutes before the last reading a build started, and ended: the hour's readings rise and settle with it.
_BUILD_START, _BUILD_END = 25, 15
#: The share of the cores the mock's processors keep busy while no build runs, and at the last reading.
_IDLE_BUSY = 0.15
#: The mock's cores.
_CORES = 12
#: How long the mock's machine has been up.
_UP = timedelta(days=9, hours=4)
#: The loop's process id, which its process and the processes' list share.
_LOOP = 48213
#: The mock's processes, parent first: pid, parent, name, user, state, processors kept busy, memory in MiB, threads,
#: minutes since it started, and command line. Runs 41 and 43 are running in its journal; 41's agent is compiling.
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
        14,
        "/home/operator/.local/share/uv/tools/canopy/bin/python -m canopy _run 41",
    ),
    (50128, 50110, "opencode", "operator", "sleeping", 0.118, 412, 22, 14, "opencode run --agent canopy-worker"),
    (50311, 50128, "bash", "operator", "sleeping", 0.0, 4, 1, 3, "/bin/bash -c cargo test --workspace"),
    (50312, 50311, "cargo", "operator", "sleeping", 0.046, 151, 9, 3, "cargo test --workspace"),
    (
        50398,
        50312,
        "rustc",
        "operator",
        "running",
        0.982,
        1210,
        14,
        1,
        "rustc --crate-name api --edition=2021 src/lib.rs --test -C opt-level=0 -C debuginfo=2",
    ),
    (
        50401,
        50312,
        "rustc",
        "operator",
        "running",
        0.957,
        880,
        12,
        1,
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
        9,
        "/home/operator/.local/share/uv/tools/canopy/bin/python -m canopy _run 43",
    ),
    (50152, 50140, "opencode", "operator", "sleeping", 0.036, 377, 21, 9, "opencode run --agent canopy-worker"),
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
        A 12-core Linux box with the workspace and journal on one disk and the temporary directory on another.
    """
    return HostResources(
        hostname="build-box",
        system="Linux 6.8.0",
        machine="x86_64",
        python="3.13.1",
        booted_at=now - _UP,
        read_at=now,
        cpu=Cpu(cores=_CORES, load=[2.41, 1.87, 1.52], time=_time(_UP)),
        memory=Memory(total=64 * _GIB, available=23 * _GIB + 410 * _MIB, swap_total=8 * _GIB, swap_free=7 * _GIB),
        stalled=Stalls(memory=0.0, io=0.004),
        disks=[
            Disk(
                holds=["workspace", "journal"],
                path="/home/operator/acme",
                total=931 * _GIB,
                free=412 * _GIB,
                floor=2 * _GIB,
            ),
            Disk(holds=["temp"], path="/tmp", total=32 * _GIB, free=27 * _GIB + 300 * _MIB, floor=None),  # noqa: S108
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
        A build box's: the loop, its two running runs' agents with a compile under one, and a few services.
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
        A full hour, every `host.SAMPLE_SECONDS`: the load, the processors, the memory, and the stalls rise with a
        build from 25 to 15 minutes before and settle again, the swap it pushed out stays out, the temporary directory
        fills while it runs and is cleared after, the workspace's disk keeps what it wrote, and the loop's own memory
        climbs slowly, as a long-lived process's does.
    """
    last = machine(now)
    readings = [_reading(now, i) for i in range(host.KEPT - 1, 0, -1)]
    before = _time(_UP - timedelta(seconds=host.SAMPLE_SECONDS))
    return host.Samples(seeded=[*readings, host.sample(last, before)])


def _time(up: timedelta) -> CpuTime:
    # The processors' time after `up`, busy at the idle share throughout: the build's is not counted, nor need it be,
    # since only the last reading is measured against the one before it.
    total = up.total_seconds() * _CORES
    return CpuTime(busy=total * _IDLE_BUSY, total=total)


def _reading(now: datetime, back: int) -> HostSample:
    # `back` readings before the last: a smooth wobble, plus a build's bump `build` from 0 to 1 and back.
    minutes = back * host.SAMPLE_SECONDS / 60
    lasted = _BUILD_START - _BUILD_END
    running = _BUILD_END <= minutes <= _BUILD_START
    build = max(0.0, math.sin(math.pi * (_BUILD_START - minutes) / lasted)) if running else 0.0
    wobble = math.sin(back / 7) * 0.35 + math.sin(back / 23) * 0.25
    # What the build wrote to the workspace stays: before it, 1.6 GiB more was free.
    written = 0.0 if minutes < _BUILD_END else 1.6 if minutes > _BUILD_START else 1.6 * (minutes - _BUILD_END) / lasted
    return HostSample(
        at=now - timedelta(seconds=back * host.SAMPLE_SECONDS),
        load=round(max(0.2, 1.9 + wobble + 5.2 * build), 2),
        cpu_busy=round(_IDLE_BUSY + wobble * 0.06 + 0.6 * build, 4),
        memory_used=int((40.6 + wobble * 0.8 + 9.5 * build) * _GIB),
        # The build pushed a little out to swap, which stays there after it.
        swap_used=int((0.85 + 0.15 * min(1.0, max(0.0, (_BUILD_START - minutes) / lasted))) * _GIB),
        memory_stalled=round(0.03 * build, 4),
        io_stalled=round(0.004 + abs(wobble) * 0.004 + 0.09 * build, 4),
        rss=int((268 - minutes * 0.45 + (back % 31) * 0.3) * _MIB),
        disks=[
            DiskSample(path="/home/operator/acme", free=int((412 + written) * _GIB)),
            DiskSample(path="/tmp", free=int((27.3 - 11 * build) * _GIB)),  # noqa: S108
        ],
    )
