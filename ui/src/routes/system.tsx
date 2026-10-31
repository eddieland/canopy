import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { HOST_REFRESH_MS, hostQuery, hostSamplesQuery, metaQuery } from '@/api/queries'
import type { Disk, HostHistory, HostResources } from '@/api/types'
import { Age } from '@/components/age'
import { CopyButton } from '@/components/copy-button'
import { Counter } from '@/components/counter'
import { Field, Fields } from '@/components/fields'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { ProcessTree } from '@/components/process-tree'
import { Timestamp } from '@/components/timestamp'
import { TrendChart } from '@/components/trend-chart'
import type { TrendReference } from '@/components/trend-chart'
import { HEADROOM } from '@/lib/chart'
import {
    bytesText,
    concerns,
    coreShare,
    diskHolds,
    diskPressure,
    loadPressure,
    loadText,
    memoryPressure,
    percentText,
    PRESSURE_TEXT,
    PRESSURE_TONE,
    usedShare,
} from '@/lib/host'
import type { Pressure } from '@/lib/host'
import { age, useNow } from '@/lib/time'
import { trend } from '@/lib/trend'
import type { Trend } from '@/lib/trend'
import { cn } from '@/lib/utils'
import { Code } from '@/components/code'

// What the page shows, the same on every visit: the title's help, so the description is left for the machine.
const HELP =
    'The machine the loop runs on: how busy its processors are, its memory, the disks canopy writes to, what each ' +
    `process uses, and the loop's own process. Read when the page opens and every ${HOST_REFRESH_MS / 1000} ` +
    'seconds while it is open; the graphs are the last hour of readings the server keeps in memory.'

// What a figure the operating system does not give reads as: off Linux, the standard library has no way to it.
const UNREAD = 'not read on this system'

// Written out so Tailwind finds them: a disk's bar, in its pressure's color, the accent while it is fine.
const BAR: Record<Pressure, string> = {
    ok: 'bg-accent/70',
    high: 'bg-status-blocked',
    critical: 'bg-status-failed',
}

// How pressed, as a number to sort by.
const RANK: Record<Pressure, number> = { ok: 0, high: 1, critical: 2 }

// The least top a stall's graph has: a process waits a little now and then on any machine, which a graph scaled to its
// peak would draw as a cliff, so a tenth of the time is drawn as tall as anything short of real pressure.
const STALL_TOP = 0.1

// Between a counter's number and its unit: a rolling number's glyphs are drawn by CSS, which collapses a plain space.
const NBSP = '\u00A0'

/**
 * The machine the loop runs on (the header's host readout opens it): what is under pressure first, four counters
 * (the load, the memory used, the free space where the workspace is or on a disk under more pressure, how long the
 * loop has run), a graph of each over the last hour, the processes keeping it busy, then each disk canopy writes to,
 * the processors and memory, the loop's process, and the machine. In no section; read again every few seconds.
 */
export const Route = createFileRoute('/system')({
    component: SystemPage,
})

function SystemPage() {
    const query = useQuery(hostQuery)
    const { data } = query
    return (
        <>
            <PageHeader root="System" title="System resources" help={HELP}>
                {data === undefined ? (
                    'The machine the loop runs on.'
                ) : (
                    <>
                        <span className="font-mono text-xs">{data.hostname}</span>, {data.system} on {data.machine}
                        {data.booted_at === null ? null : (
                            <>
                                , up <Age at={data.booted_at} variant="bare" className="text-sm text-inherit" />
                            </>
                        )}
                        .
                    </>
                )}
            </PageHeader>
            {data === undefined ? (
                <Panel>
                    <PanelLoading query={query} className="min-h-72" rows={4} />
                </Panel>
            ) : (
                <Resources host={data} />
            )}
        </>
    )
}

/** Everything the page shows of a read. */
function Resources({ host }: { host: HostResources }) {
    const found = concerns(host)
    return (
        <>
            {found.length > 0 && (
                <Panel data-testid="host-concerns">
                    <PanelHeader label="Under pressure" />
                    <ul className="flex flex-col gap-1 p-3 text-sm">
                        {found.map((c) => (
                            <li key={c.text} className={PRESSURE_TEXT[c.pressure]}>
                                {c.text}
                            </li>
                        ))}
                    </ul>
                </Panel>
            )}
            <HostCounters host={host} />
            <LastHour host={host} />
            <ProcessTree loop={host.process.pid} cores={host.cpu.cores} />
            <Panel>
                <PanelHeader label="Disks">
                    <span className="text-xs text-muted-foreground">where canopy writes</span>
                </PanelHeader>
                {host.disks.length === 0 ? (
                    <p className="p-3 text-sm text-muted-foreground">none could be read</p>
                ) : (
                    <ul className="divide-y">
                        {host.disks.map((disk) => (
                            <DiskRow key={disk.path} disk={disk} />
                        ))}
                    </ul>
                )}
            </Panel>
            <div className="grid gap-6 xl:grid-cols-3">
                <Processors host={host} />
                <LoopProcess host={host} />
                <Machine host={host} />
            </div>
        </>
    )
}

/** The machine at a glance: the five minutes' load, the memory in use, a disk's free space, the loop's age. */
function HostCounters({ host }: { host: HostResources }) {
    const now = useNow()
    const { cpu, memory, process } = host
    const five = cpu.load?.[1]
    const share = five === undefined ? null : coreShare(five, cpu.cores)
    // The workspace's disk, where agents build, unless another is under more pressure.
    const least = host.disks.toSorted((a, b) => RANK[diskPressure(b)] - RANK[diskPressure(a)])[0]
    return (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(12rem,1fr))] gap-3" data-testid="host-counters">
            <Counter
                label="Load"
                value={five === undefined ? '–' : share === null ? loadText(five) : percentText(share)}
                tone={PRESSURE_TONE[loadPressure(cpu)]}
            >
                {five === undefined || share === null
                    ? 'over 5 minutes'
                    : `of ${cpu.cores} cores over 5 minutes, a load of ${loadText(five)}`}
            </Counter>
            <Counter
                label="Memory used"
                value={
                    memory.total === null || memory.available === null
                        ? '–'
                        : percentText(usedShare(memory.total, memory.available))
                }
                tone={PRESSURE_TONE[memoryPressure(memory)]}
            >
                {memory.total === null || memory.available === null
                    ? UNREAD
                    : `${bytesText(memory.available)} of ${bytesText(memory.total)} available`}
            </Counter>
            <Counter
                label="Disk free"
                testId="disk"
                value={least === undefined ? '–' : bytesText(least.free).replace(' ', NBSP)}
                tone={least === undefined ? 'plain' : PRESSURE_TONE[diskPressure(least)]}
            >
                {least === undefined ? 'no disk read' : `where ${diskHolds(least)} ${verb(least)}`}
            </Counter>
            <Counter
                label="Loop up"
                testId="loop"
                value={process.started_at === null ? '–' : age(process.started_at, now)}
                tone="plain"
            >
                {process.rss === null ? `pid ${process.pid}` : `pid ${process.pid}, ${bytesText(process.rss)}`}
            </Counter>
        </div>
    )
}

/** One graph the last hour's panel draws. */
interface Graph {
    label: string
    detail?: string
    trend: Trend
    top: number
    format: (value: number) => string
    reference?: TrendReference
}

/**
 * The server's readings of the machine over the last hour, kept in memory since it started: the load, the processors
 * busy, the memory and swap in use, how long processes waited for memory and on disks, the loop's own memory, and
 * each disk's free space, each a graph of its own. A measure the system gives no reading of draws none.
 */
function LastHour({ host }: { host: HostResources }) {
    const { data } = useQuery(hostSamplesQuery)
    return (
        <Panel data-testid="host-graphs">
            <PanelHeader label="Last hour">
                {data !== undefined && (
                    <span className="text-xs text-muted-foreground">read every {data.every_seconds} seconds</span>
                )}
            </PanelHeader>
            {data === undefined ? (
                <PanelSkeleton rows={3} className="min-h-32" />
            ) : (
                <Graphs host={host} history={data} />
            )}
        </Panel>
    )
}

/** Each graph of `history` there are readings for, or what says there are none yet. */
function Graphs({ host, history }: { host: HostResources; history: HostHistory }) {
    const graphs = graphsOf(host, history)
    if (graphs.length === 0) {
        return <Empty>no readings yet: the server reads the machine every {history.every_seconds} seconds</Empty>
    }
    return (
        <div className="grid divide-y sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-3">
            {graphs.map((g) => (
                <TrendChart key={`${g.label} ${g.detail ?? ''}`} {...g} />
            ))}
        </div>
    )
}

// The graphs of `history`: the load as a share of the cores (the bare average where they are not known), the share of
// the processors busy, the memory and the swap against all there is (none for a machine with no swap), the share of
// the time a process waited for memory and on a disk, the loop's own memory, and each disk's free space against its
// size, with the tick's floor where it has one.
function graphsOf(host: HostResources, history: HostHistory): Graph[] {
    const graphs: Graph[] = []
    const cores = host.cpu.cores
    const load = trend(history, (s) => (s.load === null ? null : (coreShare(s.load, cores) ?? s.load)))
    if (load !== null) {
        graphs.push({
            label: 'Load',
            detail: cores === null ? 'over a minute' : `of ${cores} cores, over a minute`,
            trend: load,
            top: headroom(load.peak),
            format: cores === null ? loadText : percentText,
            reference: cores === null ? undefined : { value: 1, label: 'all busy' },
        })
    }
    const busy = trend(history, (s) => s.cpu_busy)
    if (busy !== null) {
        graphs.push({
            label: 'CPU busy',
            detail: cores === null ? 'of all cores' : `of ${cores} cores`,
            trend: busy,
            top: 1,
            format: percentText,
        })
    }
    const memory = trend(history, (s) => s.memory_used)
    if (memory !== null) {
        graphs.push({
            label: 'Memory used',
            detail: host.memory.total === null ? undefined : `of ${bytesText(host.memory.total)}`,
            trend: memory,
            top: host.memory.total ?? headroom(memory.peak),
            format: bytesText,
        })
    }
    const swapTotal = host.memory.swap_total ?? 0
    const swap = swapTotal > 0 ? trend(history, (s) => s.swap_used) : null
    if (swap !== null) {
        graphs.push({
            label: 'Swap used',
            detail: `of ${bytesText(swapTotal)}`,
            trend: swap,
            top: swapTotal,
            format: bytesText,
        })
    }
    const stalls: [string, Trend | null][] = [
        ['Memory stalls', trend(history, (s) => s.memory_stalled)],
        ['Disk stalls', trend(history, (s) => s.io_stalled)],
    ]
    for (const [label, stalled] of stalls) {
        if (stalled !== null) {
            graphs.push({
                label,
                detail: 'time a process waited',
                trend: stalled,
                top: Math.max(headroom(stalled.peak), STALL_TOP),
                format: percentText,
            })
        }
    }
    const rss = trend(history, (s) => s.rss)
    if (rss !== null) {
        graphs.push({ label: "Loop's memory", trend: rss, top: headroom(rss.peak), format: bytesText })
    }
    for (const disk of host.disks) {
        const free = trend(history, (s) => s.disks.find((d) => d.path === disk.path)?.free ?? null)
        if (free !== null) {
            graphs.push({
                label: 'Disk free',
                // In a word each, as the disks' rows below name them in full: a graph's label has little room.
                detail: disk.holds.join(' and '),
                trend: free,
                top: disk.total,
                format: bytesText,
                reference:
                    disk.floor === null ? undefined : { value: disk.floor, label: `floor ${bytesText(disk.floor)}` },
            })
        }
    }
    return graphs
}

// A graph's top over its peak, the room Charts keeps over a bar's; a peak of nothing still has a top.
function headroom(peak: number): number {
    return peak > 0 ? peak * HEADROOM : 1
}

/** One disk: what canopy keeps there, its path, a bar of what is used, and the tick's floor when it has one. */
function DiskRow({ disk }: { disk: Disk }) {
    const pressure = diskPressure(disk)
    const used = usedShare(disk.total, disk.free)
    return (
        <li className="flex flex-col gap-1.5 px-3 py-2.5" data-testid="disk-row">
            <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="flex min-w-0 items-baseline gap-2">
                    <span className="text-sm first-letter:uppercase">{diskHolds(disk)}</span>
                    <span className="truncate font-mono text-xs text-muted-foreground">{disk.path}</span>
                    <CopyButton text={disk.path} label="path" />
                </span>
                <span className="readout text-xs text-muted-foreground">
                    <span className={PRESSURE_TEXT[pressure]}>{bytesText(disk.free)}</span> free of{' '}
                    {bytesText(disk.total)}, {percentText(used)} used
                </span>
            </div>
            {/* The words beside it say how full it is, so the bar is for the eye alone. */}
            <div aria-hidden className="h-1.5 overflow-hidden rounded-full bg-surface-raised">
                <div className={cn('h-full rounded-full', BAR[pressure])} style={{ width: percentText(used) }} />
            </div>
            {disk.floor !== null && (
                <span className="text-xs text-muted-foreground">
                    Under {bytesText(disk.floor)} free, a tick runs no overseer (<Code>loop.min_free_disk_mib</Code>).
                </span>
            )}
        </li>
    )
}

/** The processors and the memory. */
function Processors({ host }: { host: HostResources }) {
    const { cpu, memory } = host
    return (
        <Panel>
            <PanelHeader label="Processors and memory" />
            <Fields>
                <Field label="Cores">{cpu.cores ?? UNREAD}</Field>
                <Field label="Load">
                    {cpu.load === null ? (
                        UNREAD
                    ) : (
                        <>
                            <span className="readout">{cpu.load.map(loadText).join('  ')}</span>
                            <span className="text-muted-foreground">
                                {' '}
                                processes running or waiting for a core, on average over 1, 5, and 15 minutes
                            </span>
                        </>
                    )}
                </Field>
                <Field label="Memory">{memory.total === null ? UNREAD : bytesText(memory.total)}</Field>
                <Field label="Available">{memory.available === null ? UNREAD : bytesText(memory.available)}</Field>
                <Field label="Swap">{swapText(memory)}</Field>
            </Fields>
        </Panel>
    )
}

/** The loop's own process: its id, when it started, what it holds. */
function LoopProcess({ host }: { host: HostResources }) {
    const { process } = host
    return (
        <Panel>
            <PanelHeader label="The loop's process" />
            <Fields>
                <Field label="PID" mono>
                    {process.pid}
                </Field>
                <Field label="Started">{process.started_at === null ? UNREAD : <When at={process.started_at} />}</Field>
                <Field label="Memory">{process.rss === null ? UNREAD : bytesText(process.rss)}</Field>
                <Field label="Peak">{process.peak_rss === null ? UNREAD : bytesText(process.peak_rss)}</Field>
                <Field label="Threads">{process.threads}</Field>
                <Field label="Open files">{openFilesText(process)}</Field>
            </Fields>
        </Panel>
    )
}

/** The machine itself, and what canopy runs on it. */
function Machine({ host }: { host: HostResources }) {
    const version = useQuery(metaQuery).data?.version
    return (
        <Panel>
            <PanelHeader label="Machine" />
            <Fields>
                <Field label="Hostname" mono>
                    {host.hostname}
                </Field>
                <Field label="System">{host.system}</Field>
                <Field label="Architecture" mono>
                    {host.machine}
                </Field>
                <Field label="Booted">{host.booted_at === null ? UNREAD : <When at={host.booted_at} />}</Field>
                <Field label="Python" mono>
                    {host.python}
                </Field>
                <Field label="canopy" mono>
                    {version ?? '–'}
                </Field>
            </Fields>
        </Panel>
    )
}

/** A moment shown whole, and its age. */
function When({ at }: { at: string }): ReactNode {
    return (
        <span className="inline-flex flex-wrap items-baseline gap-x-2">
            <Timestamp at={at} />
            <Age at={at} variant="ago" />
        </span>
    )
}

// How much swap is in use, of how much.
function swapText(memory: HostResources['memory']): string {
    if (memory.swap_total === null || memory.swap_free === null) {
        return UNREAD
    }
    if (memory.swap_total === 0) {
        return 'none'
    }
    return `${bytesText(memory.swap_total - memory.swap_free)} used of ${bytesText(memory.swap_total)}`
}

// How many files the process holds open, of how many it may.
function openFilesText(process: HostResources['process']): string {
    if (process.open_files === null) {
        return UNREAD
    }
    return process.max_open_files === null
        ? String(process.open_files)
        : `${process.open_files} of ${process.max_open_files}`
}

// `is` or `are`, for what a disk keeps.
function verb(disk: Disk): string {
    return disk.holds.length > 1 ? 'are' : 'is'
}
