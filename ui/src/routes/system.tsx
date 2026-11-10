import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Sprout, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { HOST_REFRESH_MS, hostQuery, hostSamplesQuery, metaQuery } from '@/api/queries'
import type { Disk, HostHistory, HostResources } from '@/api/types'
import { Age } from '@/components/age'
import { Code } from '@/components/code'
import { CopyButton } from '@/components/copy-button'
import { Counter } from '@/components/counter'
import { Field, Fields } from '@/components/fields'
import { FoldPanel } from '@/components/fold-panel'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { ProcessTree } from '@/components/process-tree'
import { InlineCode } from '@/components/rich-text'
import { TrendChart } from '@/components/trend-chart'
import type { TrendReference, TrendTone } from '@/components/trend-chart'
import { Skeleton } from '@/components/ui/skeleton'
import { HEADROOM } from '@/lib/chart'
import {
    bytesText,
    concerns,
    coreShare,
    diskHolds,
    diskPressure,
    fillsIn,
    fillsInText,
    loadPressure,
    loadText,
    loadTrend,
    memoryHighAt,
    memoryPressure,
    percentText,
    PRESSURE_TEXT,
    PRESSURE_TONE,
    usedShare,
} from '@/lib/host'
import type { Concern, Pressure } from '@/lib/host'
import { useNow } from '@/lib/time'
import { trend } from '@/lib/trend'
import type { Trend } from '@/lib/trend'
import { cn } from '@/lib/utils'

// What the page shows, the same on every visit: the title's help, so the description is left for the machine.
const HELP =
    'The machine the loop runs on: what is under pressure and the way out, how busy its processors are, its ' +
    'memory, what each process uses, and the disks canopy writes to. Read when the page opens and every ' +
    `${HOST_REFRESH_MS / 1000} seconds while it is open; the graphs are the last hour of readings the server keeps ` +
    'in memory.'

// Written out so Tailwind finds them: a disk's bar, in its pressure's color, the accent while it is fine.
const BAR: Record<Pressure, string> = {
    ok: 'bg-accent/70',
    high: 'bg-status-blocked',
    critical: 'bg-status-failed',
}

// A graph's line, in its pressure's color, the accent while it is fine.
const TONE: Record<Pressure, TrendTone> = { ok: 'accent', high: 'blocked', critical: 'failed' }

// And the band's tint, in the worst pressure's color.
const BAND: Record<Exclude<Pressure, 'ok'>, string> = {
    high: 'border-status-blocked/40 bg-status-blocked/8',
    critical: 'border-status-failed/40 bg-status-failed/8',
}

// How pressed, as a number to sort by.
const RANK: Record<Pressure, number> = { ok: 0, high: 1, critical: 2 }

// The least top a stall's graph has: a process waits a little now and then on any machine, which a graph scaled to its
// peak would draw as a cliff, so a tenth of the time is drawn as tall as anything short of real pressure.
const STALL_TOP = 0.1

// Between a counter's number and its unit: a rolling number's glyphs are drawn by CSS, which collapses a plain space.
const NBSP = ' '

// What the calm line adds once nothing is under pressure, one a day: fun (ui/DESIGN.md, "Fun"), so never a tip.
const CALM = [
    'The fans have nothing to report.',
    'Plenty of room, which a cargo build will take as a challenge.',
    'Enjoy it: somewhere a lockfile is about to change.',
    'The machine is mostly waiting on you.',
] as const

const DAY_MS = 86_400_000

/**
 * The machine the loop runs on (the header's host readout opens it), leading with the answer: a band saying what is
 * under pressure, what it costs and the way out, or a calm line; three counters (the load and its direction, the
 * memory used, the free space where the workspace is or on a disk under more pressure); then the section a concern is
 * about, the disks for a disk's, else the processes first; each disk with its last hour; the graphs of the last hour;
 * and, folded, the details nothing above shows. In no section; read again every few seconds.
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
                {data === undefined ? 'The machine the loop runs on.' : <Machine host={data} />}
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

/** The page's description: the machine, how long it has been up, and how long the loop has. */
function Machine({ host }: { host: HostResources }) {
    const started = host.process.started_at
    return (
        <>
            <span className="font-mono text-xs">{host.hostname}</span>, {host.system} on {host.machine}
            {host.booted_at === null ? null : (
                <>
                    , up <Age at={host.booted_at} variant="bare" className="text-sm text-inherit" />
                </>
            )}
            {started === null ? null : (
                <>
                    ; the loop up <Age at={started} variant="bare" className="text-sm text-inherit" />
                </>
            )}
            .
        </>
    )
}

/**
 * Everything the page shows of a read, the answer first: what is under pressure, the counters, then the section the
 * worst concern is about. The disks stand above the graphs either way, so every one is on the first screen.
 */
function Resources({ host }: { host: HostResources }) {
    const found = concerns(host)
    const linux = onLinux(host)
    const disks = <Disks host={host} />
    // Off Linux nothing says what each process uses, which the line under the counters says once for all of it.
    const processes = linux ? <ProcessTree loop={host.process.pid} cores={host.cpu.cores} /> : null
    const diskFirst = found[0]?.what === 'disk'
    return (
        <>
            {found.length > 0 ? <PressureBand found={found} /> : <CalmLine />}
            <HostCounters host={host} />
            {!linux && (
                <p className="text-xs text-muted-foreground" data-testid="host-unread">
                    Memory, stalls, and processes are read on Linux only.
                </p>
            )}
            {diskFirst ? disks : processes}
            {diskFirst ? processes : disks}
            <LastHour host={host} />
            <Details host={host} />
        </>
    )
}

/**
 * What is under pressure, as a band heading the page (ui/DESIGN.md, "A band heads the content column") on the worst
 * pressure's tint: each concern, what it costs, in its own pressure's color, and the way out under it.
 */
function PressureBand({ found }: { found: readonly Concern[] }) {
    const worst = found.some((c) => c.pressure === 'critical') ? 'critical' : 'high'
    return (
        <section
            aria-label="Under pressure"
            data-testid="host-concerns"
            className={cn('flex items-start gap-3 rounded-md border px-3 py-2', BAND[worst])}
        >
            <TriangleAlert aria-hidden className={cn('mt-0.5 size-4 shrink-0', PRESSURE_TEXT[worst])} />
            <ul className="flex min-w-0 flex-col gap-1.5">
                {found.map((c) => (
                    <li key={c.text} className="flex flex-col gap-0.5">
                        <span className={cn('text-sm font-medium break-words', PRESSURE_TEXT[c.pressure])}>
                            {c.text}
                        </span>
                        <span className="text-xs text-muted-foreground">
                            <InlineCode text={c.way} links={false} />
                        </span>
                    </li>
                ))}
            </ul>
        </section>
    )
}

/** In the band's place while nothing is under pressure: says so, with a line of its own for the day. */
function CalmLine() {
    const day = Math.floor(useNow() / DAY_MS)
    return (
        <p className="flex items-center gap-2 px-1 text-sm text-muted-foreground" data-testid="host-calm">
            <Sprout aria-hidden className="size-4 shrink-0 text-accent" />
            <span>Nothing under pressure. {CALM[day % CALM.length]}</span>
        </p>
    )
}

/** The machine at a glance: the five minutes' load and its direction, the memory in use, a disk's free space. */
function HostCounters({ host }: { host: HostResources }) {
    const { cpu, memory } = host
    const five = cpu.load?.[1]
    const share = five === undefined ? null : coreShare(five, cpu.cores)
    const heading = loadTrend(cpu)
    // The workspace's disk, where agents build, unless another is under more pressure.
    const least = host.disks.toSorted((a, b) => RANK[diskPressure(b)] - RANK[diskPressure(a)])[0]
    return (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(12rem,1fr))] gap-3" data-testid="host-counters">
            <Counter
                label="Load"
                value={five === undefined ? '–' : share === null ? loadText(five) : percentText(share)}
                tone={PRESSURE_TONE[loadPressure(cpu)]}
            >
                {/* The bare average where the value is not already it, then which way it is heading. */}
                {[five === undefined || share === null ? 'over 5 min' : `${loadText(five)} over 5 min`, heading]
                    .filter((part) => part !== null)
                    .join(', ')}
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
                {memoryLine(memory)}
            </Counter>
            <Counter
                label="Disk free"
                testId="disk"
                value={least === undefined ? '–' : bytesText(least.free).replace(' ', NBSP)}
                tone={least === undefined ? 'plain' : PRESSURE_TONE[diskPressure(least)]}
                wrap
            >
                {least === undefined ? 'no disk read' : `where ${diskHolds(least)} ${verb(least)}`}
            </Counter>
        </div>
    )
}

// The memory counter's line: what is available of all there is, or only all there is where the system says no more.
function memoryLine(memory: HostResources['memory']): string | undefined {
    if (memory.total === null) {
        return undefined
    }
    return memory.available === null
        ? `${bytesText(memory.total)} in all`
        : `${bytesText(memory.available)} of ${bytesText(memory.total)} available`
}

/** Each disk canopy writes to, a row each with its last hour of free space. */
function Disks({ host }: { host: HostResources }) {
    const { data } = useQuery(hostSamplesQuery)
    return (
        <Panel data-testid="host-disks">
            <PanelHeader label="Disks">
                <span className="text-xs text-muted-foreground">where canopy writes</span>
            </PanelHeader>
            {host.disks.length === 0 ? (
                <p className="p-3 text-sm text-muted-foreground">none could be read</p>
            ) : (
                <ul className="divide-y">
                    {host.disks.map((disk) => (
                        <DiskRow key={disk.path} disk={disk} history={data} />
                    ))}
                </ul>
            )}
        </Panel>
    )
}

/**
 * One disk: what canopy keeps there, its path, a bar of what is used, the tick's floor when it has one, how soon it
 * fills when its free space fell over the hour, and beside them the hour's line of its free space, naming the low.
 */
function DiskRow({ disk, history }: { disk: Disk; history: HostHistory | undefined }) {
    const pressure = diskPressure(disk)
    const used = usedShare(disk.total, disk.free)
    const free =
        history === undefined
            ? undefined
            : trend(history, (s) => s.disks.find((d) => d.path === disk.path)?.free ?? null)
    const fills = free === undefined || free === null ? null : fillsIn(free)
    return (
        <li className="grid @3xl:grid-cols-2" data-testid="disk-row">
            <div className="flex min-w-0 flex-col gap-1.5 px-3 py-2.5">
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
                        Under {bytesText(disk.floor)} free, a tick runs no overseer (<Code>loop.min_free_disk_mib</Code>
                        ).
                    </span>
                )}
                {fills !== null && (
                    <span className="text-xs text-status-blocked" data-testid="disk-fills">
                        {fillsInText(fills)}
                    </span>
                )}
            </div>
            {free === undefined ? (
                // The size of the chart that comes, so nothing moves when it does.
                <div className="px-3 py-2.5">
                    <Skeleton className="h-30 w-full" />
                </div>
            ) : free === null ? null : (
                <TrendChart
                    label="Last hour"
                    trend={free}
                    top={disk.total}
                    format={bytesText}
                    extreme="low"
                    latest={false}
                    tone={TONE[pressure]}
                    reference={
                        disk.floor === null ? undefined : { value: disk.floor, label: `floor ${bytesText(disk.floor)}` }
                    }
                />
            )}
        </li>
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
    tone?: TrendTone
}

/** The last hour's graphs, in their two ranks. */
interface Graphs {
    /** The load, the memory, and the processors: what the operator reads first, at full height. */
    primary: Graph[]
    /** The swap, the stalls, and the loop's memory, flat nearly always: half as tall, under them. */
    secondary: Graph[]
}

/**
 * The server's readings of the machine over the last hour, kept in memory since it started, each a graph of its own: a
 * first rank of the load, the memory in use, and the processors busy, and under it, half as tall, the swap, how long
 * processes waited for memory and on disks, and the loop's own memory. They share one pointer and one hour, which the
 * header says once with how long ago they were read, in amber once a read again failed. A measure the system gives no
 * reading of draws none; each disk's is on its row.
 */
function LastHour({ host }: { host: HostResources }) {
    const query = useQuery(hostSamplesQuery)
    const { data } = query
    return (
        <Panel data-testid="host-graphs">
            <PanelHeader label="Last hour">
                {data !== undefined && (
                    <span
                        className={cn(
                            'text-xs',
                            query.isRefetchError ? 'text-status-blocked' : 'text-muted-foreground',
                        )}
                        data-testid="host-graphs-read"
                    >
                        the last {Math.round(((data.kept - 1) * data.every_seconds) / 60)} min, read{' '}
                        <Age at={new Date(query.dataUpdatedAt).toISOString()} variant="ago" className="text-inherit" />
                        {query.isRefetchError && ', and the last read again failed'}
                    </span>
                )}
            </PanelHeader>
            {data === undefined ? (
                <PanelSkeleton rows={3} className="min-h-32" />
            ) : (
                <GraphRanks host={host} history={data} />
            )}
        </Panel>
    )
}

/** Each graph of `history` there are readings for, in their ranks, or what says there are none yet. */
function GraphRanks({ host, history }: { host: HostResources; history: HostHistory }) {
    const [at, setAt] = useState<number | null>(null)
    const { primary, secondary } = graphsOf(host, history)
    if (primary.length + secondary.length === 0) {
        return <Empty>no readings yet: the server reads the machine every {history.every_seconds} seconds</Empty>
    }
    const pointer = { at, set: setAt }
    return (
        <>
            <div className="grid divide-y sm:grid-cols-3 sm:divide-y-0">
                {primary.map((g) => (
                    <TrendChart key={g.label} {...g} axis={false} pointer={pointer} />
                ))}
            </div>
            {secondary.length > 0 && (
                <div className="grid border-t sm:grid-cols-2 xl:grid-cols-4">
                    {secondary.map((g) => (
                        <TrendChart key={g.label} {...g} axis={false} pointer={pointer} half />
                    ))}
                </div>
            )}
        </>
    )
}

// The graphs of `history`. First: the load as a share of the cores (the bare average where they are not known), in
// its pressure's color with where every core is busy, the memory against all there is, in its pressure's color with
// where it turns amber, and the share of the processors busy. Then: the swap against all there is (none for a machine
// with no swap), the share of the time a process waited for memory and on a disk, and the loop's own memory.
function graphsOf(host: HostResources, history: HostHistory): Graphs {
    const primary: Graph[] = []
    const secondary: Graph[] = []
    const cores = host.cpu.cores
    const load = trend(history, (s) => (s.load === null ? null : (coreShare(s.load, cores) ?? s.load)))
    if (load !== null) {
        primary.push({
            label: 'Load',
            detail: cores === null ? 'over a minute' : 'of all cores, over a minute',
            trend: load,
            top: headroom(load.peak),
            format: cores === null ? loadText : percentText,
            reference: cores === null ? undefined : { value: 1, label: 'all busy' },
            tone: TONE[loadPressure(host.cpu)],
        })
    }
    const memory = trend(history, (s) => s.memory_used)
    const total = host.memory.total
    if (memory !== null) {
        primary.push({
            label: 'Memory used',
            detail: total === null ? undefined : `of ${bytesText(total)}`,
            trend: memory,
            top: total ?? headroom(memory.peak),
            format: bytesText,
            reference:
                total === null
                    ? undefined
                    : { value: memoryHighAt(total), label: `${percentText(1 - memoryHighAt(1))} left` },
            tone: TONE[memoryPressure(host.memory)],
        })
    }
    const busy = trend(history, (s) => s.cpu_busy)
    if (busy !== null) {
        primary.push({ label: 'CPU busy', detail: 'of all cores', trend: busy, top: 1, format: percentText })
    }
    const swapTotal = host.memory.swap_total ?? 0
    const swap = swapTotal > 0 ? trend(history, (s) => s.swap_used) : null
    if (swap !== null) {
        secondary.push({
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
            secondary.push({
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
        secondary.push({ label: "Loop's memory", trend: rss, top: headroom(rss.peak), format: bytesText })
    }
    return { primary, secondary }
}

// A graph's top over its peak, the room Charts keeps over a bar's; a peak of nothing still has a top.
function headroom(peak: number): number {
    return peak > 0 ? peak * HEADROOM : 1
}

/**
 * What nothing above shows, folded on arrival: the cores, the three load averages, the swap, the loop's peak memory,
 * threads and open files, and the Python and canopy it runs. A figure the system does not give is left out, as the
 * line under the counters says off Linux.
 */
function Details({ host }: { host: HostResources }) {
    return (
        <FoldPanel
            label="Details"
            what="details"
            data-testid="host-details"
            readout={<span className="text-xs text-muted-foreground">cores, load, swap, the loop, versions</span>}
        >
            <DetailFields host={host} />
        </FoldPanel>
    )
}

/** The details' fields, built once the panel opens. */
function DetailFields({ host }: { host: HostResources }) {
    const { cpu, memory, process } = host
    const version = useQuery(metaQuery).data?.version
    const swap = swapText(memory)
    const files = openFilesText(process)
    return (
        <Fields>
            {cpu.cores !== null && <Field label="Cores">{cpu.cores}</Field>}
            {cpu.load !== null && (
                <Field label="Load">
                    <span className="readout">{cpu.load.map(loadText).join('  ')}</span>
                    <span className="text-muted-foreground">
                        {' '}
                        processes running or waiting for a core, on average over 1, 5, and 15 minutes
                    </span>
                </Field>
            )}
            {swap !== null && <Field label="Swap">{swap}</Field>}
            {process.peak_rss !== null && <Field label="Loop's peak">{bytesText(process.peak_rss)}</Field>}
            <Field label="Loop's threads">{process.threads}</Field>
            {files !== null && <Field label="Open files">{files}</Field>}
            <Field label="Python" mono>
                {host.python}
            </Field>
            <Field label="canopy" mono>
                <span data-testid="host-version">{version ?? '–'}</span>
            </Field>
        </Fields>
    )
}

/** Whether the machine is Linux, the one system whose `/proc` gives the memory, the stalls, and the processes. */
function onLinux(host: HostResources): boolean {
    return host.system.split(' ')[0] === 'Linux'
}

// How much swap is in use, of how much; null where the system does not say.
function swapText(memory: HostResources['memory']): string | null {
    if (memory.swap_total === null || memory.swap_free === null) {
        return null
    }
    if (memory.swap_total === 0) {
        return 'none'
    }
    return `${bytesText(memory.swap_total - memory.swap_free)} used of ${bytesText(memory.swap_total)}`
}

// How many files the loop's process holds open, of how many it may; null where the system does not say.
function openFilesText(process: HostResources['process']): string | null {
    if (process.open_files === null) {
        return null
    }
    return process.max_open_files === null
        ? String(process.open_files)
        : `${process.open_files} of ${process.max_open_files}`
}

// `is` or `are`, for what a disk keeps.
function verb(disk: Disk): string {
    return disk.holds.length > 1 ? 'are' : 'is'
}
