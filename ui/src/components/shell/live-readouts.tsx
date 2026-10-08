import type { ReactNode } from 'react'

import { useQuery } from '@tanstack/react-query'

import { attentionQuery, metaQuery, runsQuery, ticketsQuery } from '@/api/queries'
import { RunDot } from '@/components/status'
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

/** The header's counters: running runs, tickets waiting on a reply, the attention list, and the stream's state. */
export function LiveReadouts({ stream }: { stream: StreamStatus }) {
    const runs = useQuery(runsQuery)
    const tickets = useQuery(ticketsQuery)
    const attention = useQuery(attentionQuery)
    const meta = useQuery(metaQuery)

    return (
        <div className="flex items-center gap-5" data-testid="live-readouts">
            <Readout label="running" value={count(runs.data, (r) => r.state === 'running')}>
                <RunDot state="running" />
            </Readout>
            <Readout label="waiting" value={count(tickets.data, (t) => t.awaiting !== null)}>
                <RunDot state="blocked" />
            </Readout>
            <Readout label="attention" value={attention.data?.length}>
                <span aria-hidden className="size-2 rounded-full border border-accent" />
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
