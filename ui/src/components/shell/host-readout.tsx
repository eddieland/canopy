import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Server } from 'lucide-react'
import type { ReactNode } from 'react'

import { hostQuery } from '@/api/queries'
import type { HostResources } from '@/api/types'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import {
    bytesText,
    concerns,
    coreShare,
    diskHolds,
    diskPressure,
    hostPressure,
    hostReadout,
    loadText,
    loadTrend,
    PRESSURE_TEXT,
    percentText,
    usedShare,
} from '@/lib/host'
import { age, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/**
 * The machine the loop runs on, in the header's readouts: a server's icon and `host ok` muted, or its worst pressure
 * in two words, `disk low` in `status-failed` past what canopy works with and `status-blocked` short of it; under
 * `lg`, the icon alone, in that color. Hovered or focused, a card shows the machine at a glance: what is under
 * pressure, the load, the memory, each disk canopy writes to, and the loop's process. It opens the system resources
 * page. Nothing until the first read lands, and nothing while the server cannot be read, since the stream's readout
 * says so already.
 */
export function HostReadout() {
    const host = useQuery(hostQuery).data
    if (host === undefined) {
        return null
    }
    const pressure = hostPressure(host)
    const readout = hostReadout(host)
    return (
        <HoverCard>
            <HoverCardTrigger asChild>
                <Link
                    to="/system"
                    className={cn(
                        'readout inline-flex items-center gap-1.5 text-xs whitespace-nowrap underline-offset-4',
                        'hover:underline',
                        PRESSURE_TEXT[pressure],
                    )}
                    aria-label={`${readout}: system resources of ${host.hostname}`}
                    data-testid="host-readout"
                    data-pressure={pressure}
                >
                    <Server aria-hidden className="size-3.5 shrink-0" />
                    {/* Under `lg` the header has no room for the words, so the icon stands alone, in the pressure's
                    color, as the rail's strip shows a count on its icon; the words are its name and the card's. */}
                    <span className="hidden lg:inline">{readout}</span>
                </Link>
            </HoverCardTrigger>
            <HoverCardContent data-testid="host-card">
                <HostCard host={host} />
            </HoverCardContent>
        </HoverCard>
    )
}

/** The machine at a glance, as the card under the header's readout shows it. */
function HostCard({ host }: { host: HostResources }) {
    const now = useNow()
    const found = concerns(host)
    const { cpu, memory, process } = host
    const used = memory.total === null || memory.available === null ? 0 : usedShare(memory.total, memory.available)
    return (
        <div className="flex flex-col gap-2.5 text-xs">
            <div className="flex min-w-0 items-baseline justify-between gap-3">
                <span className="truncate font-medium">{host.hostname}</span>
                <span className="readout shrink-0 text-muted-foreground">
                    {host.system} {host.machine}
                </span>
            </div>
            {found.length > 0 && (
                <ul className="flex flex-col gap-1">
                    {found.map((c) => (
                        <li key={c.text} className={PRESSURE_TEXT[c.pressure]}>
                            {c.text}
                        </li>
                    ))}
                </ul>
            )}
            <dl className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-1">
                <CardRow label="Load">
                    <LoadSummary cpu={cpu} />
                </CardRow>
                <CardRow label="Memory">
                    {memory.total === null ? (
                        'not read on this system'
                    ) : memory.available === null ? (
                        <span className="readout">{bytesText(memory.total)}</span>
                    ) : (
                        <>
                            <span className="readout">{percentText(used)}</span>
                            {` used, ${bytesText(memory.available)} of ${bytesText(memory.total)} available`}
                        </>
                    )}
                </CardRow>
                {host.disks.map((disk) => (
                    <CardRow key={disk.path} label="Disk">
                        <span
                            className={cn('readout', diskPressure(disk) !== 'ok' && PRESSURE_TEXT[diskPressure(disk)])}
                        >
                            {bytesText(disk.free)}
                        </span>{' '}
                        free of {bytesText(disk.total)}, {diskHolds(disk)}
                    </CardRow>
                ))}
                <CardRow label="Loop">
                    {process.started_at === null ? `pid ${process.pid}` : `up ${age(process.started_at, now)}`}
                    {process.rss === null ? null : (
                        <>
                            , <span className="readout">{bytesText(process.rss)}</span>
                        </>
                    )}
                </CardRow>
            </dl>
            <span className="text-muted-foreground">Open it for the rest.</span>
        </div>
    )
}

/**
 * The load as the card says it: the five minutes' average as a share of the cores, `16% of 12 cores`, and which way it
 * is heading; the bare average where the cores are not known.
 */
function LoadSummary({ cpu }: { cpu: HostResources['cpu'] }) {
    const five = cpu.load?.[1]
    if (five === undefined) {
        return 'not read on this system'
    }
    const share = coreShare(five, cpu.cores)
    const trend = loadTrend(cpu)
    return (
        <>
            <span className="readout">{share === null ? loadText(five) : percentText(share)}</span>
            {share === null ? ' over 5 minutes' : ` of ${cpu.cores} cores over 5 minutes`}
            {trend === null ? null : `, ${trend}`}
        </>
    )
}

/** One row of the card: a label, and its value. */
function CardRow({ label, children }: { label: string; children: ReactNode }) {
    return (
        <>
            <dt className="panel-label">{label}</dt>
            <dd className="min-w-0 text-muted-foreground">{children}</dd>
        </>
    )
}
