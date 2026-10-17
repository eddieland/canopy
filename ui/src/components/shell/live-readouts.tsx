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

// Each no longer than `down · 59m`, the width the readout keeps (`w-[10ch]`), so a drop moves nothing beside it.
const STREAM_LABEL: Record<StreamStatus, string> = {
    connecting: 'opening',
    open: 'live',
    reconnecting: 'retrying',
    closed: 'offline',
}

/**
 * The header's readouts: the latest tick, agent memory while a tier is on, the stream's state, and `mock` over fixture
 * data. The counters are the attention page's.
 */
export function LiveReadouts({ stream }: { stream: StreamStatus }) {
    const meta = useQuery(metaQuery)
    const last = useQuery(tickQuery)
    const memory = useQuery(loopQuery).data?.memory ?? null
    const down = useLoopDown()
    // Down past the first retry's wait, it says for how long, in the color of what waits on the operator.
    const since = down.offline && down.since !== null ? new Date(down.since).toISOString() : null
    return (
        // Inset as far as a ghost button's label, so the rules either side sit midway between their neighbors.
        <div className="flex items-center gap-4 px-2.5" data-testid="live-readouts">
            {last.data?.tick && <LastTick tick={last.data.tick} />}
            {memory !== null && <MemoryReadout memory={memory} />}
            <span
                className={cn(
                    'readout inline-flex items-center gap-1.5 text-2xs uppercase',
                    since === null
                        ? stream === 'open'
                            ? 'text-accent'
                            : 'text-muted-foreground'
                        : 'text-status-blocked',
                )}
                title={since === null ? undefined : `Down since ${localTime(since)}: the loop isn't answering.`}
                data-testid="stream-status"
                data-status={since === null ? stream : 'down'}
            >
                {meta.data?.mock && <span className="rounded-sm border px-1 text-muted-foreground">mock</span>}
                <span className="inline-block w-[10ch] text-right whitespace-nowrap">
                    {since === null ? (
                        STREAM_LABEL[stream]
                    ) : (
                        <>
                            down · <Age at={since} className="text-2xs text-inherit" />
                        </>
                    )}
                </span>
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
