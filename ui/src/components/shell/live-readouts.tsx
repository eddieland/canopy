import type { ReactNode } from 'react'

import { useQuery } from '@tanstack/react-query'

import { leasesQuery, metaQuery, sessionsQuery } from '@/api/queries'
import { LeaseDot, SessionDot } from '@/components/status'
import { Skeleton } from '@/components/ui/skeleton'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { cn } from '@/lib/utils'

const STREAM_LABEL: Record<StreamStatus, string> = {
    connecting: 'connecting',
    open: 'live',
    reconnecting: 'reconnecting',
    closed: 'offline',
}

/** How many of `items` pass `test`, or undefined before the first load. */
function count<T>(items: T[] | undefined, test: (item: T) => boolean): number | undefined {
    return items?.filter(test).length
}

/** The header's counters: running and blocked sessions, held leases, and the event stream's state. */
export function LiveReadouts({ stream }: { stream: StreamStatus }) {
    const sessions = useQuery(sessionsQuery)
    const leases = useQuery(leasesQuery)
    const meta = useQuery(metaQuery)

    return (
        <div className="flex items-center gap-5" data-testid="live-readouts">
            <Readout label="running" value={count(sessions.data, (s) => s.state === 'running')}>
                <SessionDot state="running" />
            </Readout>
            <Readout label="blocked" value={count(sessions.data, (s) => s.state === 'blocked')}>
                <SessionDot state="blocked" />
            </Readout>
            <Readout label="leases" value={count(leases.data, (l) => l.state !== 'released')}>
                <LeaseDot state="held" />
            </Readout>
            <span
                className={cn(
                    'readout inline-flex w-28 items-center justify-end gap-1.5 text-[0.6875rem] uppercase',
                    stream === 'open' ? 'text-accent' : 'text-muted-foreground',
                )}
                data-testid="stream-status"
                data-status={stream}
            >
                {meta.data?.mock && <span className="rounded-sm border px-1 text-muted-foreground">mock</span>}
                {STREAM_LABEL[stream]}
            </span>
        </div>
    )
}

/** One counter. Its width is fixed, and it shows a skeleton only until the first data arrives. */
function Readout({ label, value, children }: { label: string; value: number | undefined; children: ReactNode }) {
    return (
        <div className="flex items-center gap-2">
            {children}
            <span className="panel-label">{label}</span>
            <span className="readout inline-flex w-6 justify-end text-sm">
                {value === undefined ? <Skeleton className="h-3.5 w-full" /> : value}
            </span>
        </div>
    )
}
