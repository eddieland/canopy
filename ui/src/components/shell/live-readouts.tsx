import { useQuery } from '@tanstack/react-query'

import { metaQuery, tickQuery } from '@/api/queries'
import type { Tick } from '@/api/types'
import { Age } from '@/components/age'
import { Word } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { TICK_TONE } from '@/lib/ticks'
import { cn } from '@/lib/utils'

const STREAM_LABEL: Record<StreamStatus, string> = {
    connecting: 'connecting',
    open: 'live',
    reconnecting: 'reconnecting',
    closed: 'offline',
}

/**
 * The header's readouts: the latest tick, the stream's state, and `mock` over fixture data. The counters are the
 * attention page's.
 */
export function LiveReadouts({ stream }: { stream: StreamStatus }) {
    const meta = useQuery(metaQuery)
    const last = useQuery(tickQuery)
    return (
        // Inset as far as a ghost button's label, so the rules either side sit midway between their neighbors.
        <div className="flex items-center gap-4 px-2.5" data-testid="live-readouts">
            {last.data?.tick && <LastTick tick={last.data.tick} />}
            <span
                className={cn(
                    'readout inline-flex items-center gap-1.5 text-2xs uppercase',
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

/**
 * `tick:12 · 3m ago`, with its status when it is not `ok`, as `canopy status`'s first line names it. The tick opens its
 * page: what it decided and why.
 */
function LastTick({ tick }: { tick: Tick }) {
    const shown = tick.status === 'ok' ? null : tick.status
    return (
        <span
            className={cn('readout text-xs whitespace-nowrap', TICK_TONE[tick.status] ?? 'text-muted-foreground')}
            title={tick.summary ?? undefined}
            data-testid="last-tick"
        >
            <TickLink id={tick.id} className="text-inherit" />
            {tick.dry_run ? ' (dry run)' : ''}
            {shown && (
                <>
                    {' '}
                    <Word word={shown} />
                </>
            )}
            {' · '}
            {/* `3m ago` once it ended: the header's line is short, so it leaves the span's `ended` out. */}
            {tick.ended_at === null ? (
                <Age variant="span" started={tick.started_at} ended={null} className="text-inherit" />
            ) : (
                <Age at={tick.ended_at} variant="ago" className="text-inherit" />
            )}
        </span>
    )
}
