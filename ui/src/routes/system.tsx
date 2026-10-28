import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { HOST_REFRESH_MS, hostQuery, metaQuery } from '@/api/queries'
import type { Disk, HostResources } from '@/api/types'
import { Age } from '@/components/age'
import { CopyButton } from '@/components/copy-button'
import { Counter } from '@/components/counter'
import { Field, Fields } from '@/components/fields'
import { PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { Timestamp } from '@/components/timestamp'
import {
    bytesText,
    concerns,
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
import { cn } from '@/lib/utils'

// What the page shows, the same on every visit: the title's help, so the description is left for the machine.
const HELP =
    'The machine the loop runs on: how busy its processors are, its memory, the disks canopy writes to, and the ' +
    `loop's own process. Read when the page opens and every ${HOST_REFRESH_MS / 1000} seconds while it is open.`

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

// Between a counter's number and its unit: a rolling number's glyphs are drawn by CSS, which collapses a plain space.
const NBSP = '\u00A0'

/**
 * The machine the loop runs on (the header's host readout opens it): what is under pressure first, four counters
 * (the load, the memory used, the free space where the workspace is or on a disk under more pressure, how long the
 * loop has run), then each disk canopy writes to, the processors and memory, the loop's process, and the machine. In
 * no section; read again every few seconds.
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
    // The workspace's disk, where agents build, unless another is under more pressure.
    const least = host.disks.toSorted((a, b) => RANK[diskPressure(b)] - RANK[diskPressure(a)])[0]
    return (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(12rem,1fr))] gap-3" data-testid="host-counters">
            <Counter
                label="Load"
                value={five === undefined ? '–' : loadText(five)}
                tone={PRESSURE_TONE[loadPressure(cpu)]}
            >
                {cpu.cores === null ? 'over 5 minutes' : `over 5 minutes, on ${cpu.cores} cores`}
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
                    Under {bytesText(disk.floor)} free, a tick runs no overseer (
                    <code className="font-mono">loop.min_free_disk_mib</code>).
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
                            <span className="text-muted-foreground"> over 1, 5, and 15 minutes</span>
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
