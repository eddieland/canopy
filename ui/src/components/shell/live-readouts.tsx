import { useQuery } from '@tanstack/react-query'

import { metaQuery, tickQuery } from '@/api/queries'
import type { Tick } from '@/api/types'
import { Age } from '@/components/age'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { cn } from '@/lib/utils'

const STREAM_LABEL: Record<StreamStatus, string> = {
    connecting: 'connecting',
    open: 'live',
    reconnecting: 'reconnecting',
    closed: 'offline',
}

// A tick that failed or was cut short is shown in the failure color; a running one in the running color.
const TICK_TONE: Record<string, string> = {
    running: 'text-status-running',
    overseer_failed: 'text-status-failed',
    reconcile_failed: 'text-status-failed',
    abandoned: 'text-status-failed',
}

/**
 * The header's readouts: the latest tick, the stream's state, and `mock` over fixture data. The counters are the
 * attention page's.
 */
export function LiveReadouts({ stream }: { stream: StreamStatus }) {
    const meta = useQuery(metaQuery)
    const last = useQuery(tickQuery)
    return (
        <div className="flex items-center gap-5" data-testid="live-readouts">
            {last.data?.tick && <LastTick tick={last.data.tick} />}
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

/** `tick 12 · 3m ago`, with its status when it is not `ok`, as `canopy status`'s first line names it. */
function LastTick({ tick }: { tick: Tick }) {
    const shown = tick.status === 'ok' ? null : tick.status.replace('_', ' ')
    return (
        <span
            className={cn('readout text-xs whitespace-nowrap', TICK_TONE[tick.status] ?? 'text-muted-foreground')}
            title={tick.summary ?? undefined}
            data-testid="last-tick"
        >
            tick {tick.id}
            {tick.dry_run ? ' (dry run)' : ''}
            {shown ? ` ${shown}` : ''} · {tick.ended_at === null ? 'for ' : ''}
            <Age at={tick.ended_at ?? tick.started_at} className="text-inherit" />
            {tick.ended_at === null ? '' : ' ago'}
        </span>
    )
}
