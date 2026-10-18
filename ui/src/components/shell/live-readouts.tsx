import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { loopQuery, metaQuery, tickQuery } from '@/api/queries'
import type { MemoryState, Tick } from '@/api/types'
import { Age } from '@/components/age'
import { Word } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { useLoopDown } from '@/hooks/use-loop-down'
import { TICK_TONE } from '@/lib/ticks'
import { localTime } from '@/lib/time'
import { cn } from '@/lib/utils'

// The stream's state, in a word.
const STREAM_LABEL: Record<StreamStatus, string> = {
    connecting: 'opening',
    open: 'live',
    reconnecting: 'retrying',
    closed: 'offline',
}

/**
 * The header's readouts: the latest tick, and agent memory while a tier is on. The counters are the attention page's.
 */
export function LiveReadouts() {
    const last = useQuery(tickQuery)
    const memory = useQuery(loopQuery).data?.memory ?? null
    return (
        // Inset as far as a ghost button's label, so the rules either side sit midway between their neighbors.
        <div className="flex items-center gap-4 px-2.5" data-testid="live-readouts">
            {last.data?.tick && <LastTick tick={last.data.tick} />}
            {memory !== null && <MemoryReadout memory={memory} />}
        </div>
    )
}

/**
 * The stream's state beside the name, and `mock` over fixture data. It sits at the left, before the ticker, so its
 * word hugs its text and a drop moves nothing: the ticker's window gives way, not the actions or the readouts.
 */
export function StreamReadout({ stream }: { stream: StreamStatus }) {
    const meta = useQuery(metaQuery)
    const down = useLoopDown()
    // Down past the first retry's wait, it says for how long, in the color of what waits on the operator.
    const since = down.offline && down.since !== null ? new Date(down.since).toISOString() : null
    return (
        <span
            className={cn(
                'readout inline-flex items-center gap-1.5 text-2xs whitespace-nowrap uppercase',
                since === null ? (stream === 'open' ? 'text-accent' : 'text-muted-foreground') : 'text-status-blocked',
            )}
            title={since === null ? undefined : `Down since ${localTime(since)}: the loop isn't answering.`}
            data-testid="stream-status"
            data-status={since === null ? stream : 'down'}
        >
            {meta.data?.mock && <span className="rounded-sm border px-1 text-muted-foreground">mock</span>}
            {since === null ? (
                STREAM_LABEL[stream]
            ) : (
                <span>
                    down · <Age at={since} className="text-2xs text-inherit" />
                </span>
            )}
        </span>
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

/**
 * `memory: recording` while no tier is at `use`, `memory: in use` once one is (DESIGN §28): words, never color alone,
 * so recorded memory is never taken for memory in use. Each tier's mode on hover and to a screen reader; it opens the
 * memory page.
 */
function MemoryReadout({ memory }: { memory: MemoryState }) {
    return (
        <Link
            to="/memory"
            className="readout text-xs whitespace-nowrap text-muted-foreground underline-offset-4 hover:underline"
            title={memory.tiers}
            aria-label={`${memory.readout}: ${memory.tiers}`}
            data-testid="memory-readout"
        >
            {memory.readout}
        </Link>
    )
}
