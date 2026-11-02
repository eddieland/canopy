import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import {
    choresQuery,
    loopQuery,
    reviewsQuery,
    runsQuery,
    runsSinceQuery,
    tasksQuery,
    ticketsQuery,
    tickQuery,
} from '@/api/queries'
import type { Tick } from '@/api/types'
import { Age } from '@/components/age'
import { Empty, Panel, PanelSkeleton } from '@/components/panel'
import { Word } from '@/components/status'
import { TickNow } from '@/components/tick-now'
import { Skeleton } from '@/components/ui/skeleton'
import { useLoopDown } from '@/hooks/use-loop-down'
import { useClock } from '@/lib/clock'
import { startOfDay, todayLine } from '@/lib/digest'
import { workingCount } from '@/lib/run-state'
import { TICK_TONE } from '@/lib/ticks'
import { stamp, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

// An age in the digest's running text: its size and color, not a readout's.
const AGE = 'text-sm text-inherit'

/**
 * The attention page with nothing listed. Before the journal holds any ticket, nothing has started, so it names the
 * first step rather than read as all clear; once there was work, `AllClear` is the reward for an inbox emptied. A
 * tickets read that failed tells neither apart, and the list read without it, so it is `AllClear`, as before.
 */
export function EmptyAttention() {
    const { data: tickets, isError } = useQuery(ticketsQuery)
    if (tickets === undefined) {
        if (isError) {
            return <AllClear />
        }
        return (
            <Panel>
                <PanelSkeleton className="min-h-40" />
            </Panel>
        )
    }
    if (tickets.length > 0) {
        return <AllClear />
    }
    return (
        <Panel data-testid="first-run">
            <Empty size="panel">
                no tickets yet: give one your queue label in the tracker, or start one privately on{' '}
                <Link to="/tickets" className="text-accent underline-offset-4 hover:underline">
                    Tickets
                </Link>
                , then <TickNow inline />, and what needs you lands here
            </Empty>
        </Panel>
    )
}

/**
 * The attention page with nothing listed: a canopy swaying in the wind, one leaf drifting off it, over a digest of
 * the day (`Digest`). While the loop isn't answering, the list is only what it last said, so it says nothing needed the
 * operator as of then, and never celebrates.
 */
export function AllClear() {
    const clock = useClock()
    const down = useLoopDown()
    if (down.offline && down.since !== null) {
        return (
            <Panel data-testid="all-clear">
                <div className="grid min-h-40 place-items-center content-center gap-0.5 p-6 text-center">
                    <span className="text-sm">
                        Nothing needed you as of {stamp(new Date(down.since).toISOString(), clock)}.
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">
                        the loop isn&apos;t answering, so this list can&apos;t change
                    </span>
                </div>
            </Panel>
        )
    }
    return <Digest />
}

/**
 * The true all clear, for a tab left open all day: one quiet column in the middle of the page rather than a panel,
 * the canopy, what the journal says of today, and what is going on now. It holds what it can answer for: each figure
 * goes when it is none, and the line of the day when the day held nothing or its read failed.
 */
function Digest() {
    const now = useNow()
    const today = useQuery(runsSinceQuery(startOfDay(now)))
    const tick = useQuery(tickQuery).data?.tick ?? null
    const paused = useQuery(loopQuery).data?.paused ?? null
    const runs = useQuery(runsQuery).data
    const reviews = useQuery(reviewsQuery).data
    const chores = useQuery(choresQuery).data
    const tasks = useQuery(tasksQuery).data
    // The rail's Working number, from the same reads and reckoning, so the two never disagree.
    const working = runs === undefined ? 0 : workingCount({ runs, reviews, chores, tasks })
    const day = today.data === undefined ? null : todayLine(today.data)
    return (
        // The page's height less its title and padding, a little more for the line `HiddenFindings` may add, so the
        // column sits in the window with nothing to scroll. Its padding lifts it over the middle, where the eye rests.
        <div
            data-testid="all-clear"
            className="grid min-h-[max(24rem,calc(100dvh-13rem))] place-content-center justify-items-center pb-[12dvh]"
        >
            <div className="flex max-w-prose flex-col items-center gap-8 text-center">
                <div className="flex flex-col items-center gap-3">
                    <Canopy />
                    <div className="flex flex-col gap-1">
                        <span className="text-xl">Nothing needs you.</span>
                        <span className="font-mono text-xs text-muted-foreground">all clear under the canopy</span>
                    </div>
                </div>
                <div className="flex flex-col items-center gap-1.5 text-sm text-muted-foreground">
                    {today.isLoading && <Skeleton className="h-5 w-64" />}
                    {day !== null && <p data-testid="all-clear-today">{day}</p>}
                    {paused !== null && (
                        <p className="text-status-blocked" data-testid="all-clear-paused">
                            Paused <Age at={paused.since} variant="ago" className={AGE} />: no tick starts until you
                            resume.
                        </p>
                    )}
                    <p className="flex flex-wrap justify-center gap-x-6">
                        {working > 0 && (
                            <Link
                                to="/workspace"
                                className="text-accent underline-offset-4 hover:underline"
                                data-testid="all-clear-working"
                            >
                                Working now: <span className="readout">{working}</span>
                            </Link>
                        )}
                        {tick !== null && <TickLine tick={tick} />}
                    </p>
                </div>
            </div>
        </div>
    )
}

/** The small canopy, swaying, and the leaf drifting off it. */
function Canopy() {
    return (
        <svg viewBox="0 0 64 52" className="h-24 text-accent" aria-hidden>
            <line
                x1="32"
                y1="50"
                x2="32"
                y2="30"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                className="text-muted-foreground"
            />
            <g className="origin-[32px_50px] animate-sway">
                <circle cx="22" cy="26" r="10" fill="currentColor" fillOpacity="0.12" stroke="currentColor" />
                <circle cx="42" cy="26" r="10" fill="currentColor" fillOpacity="0.12" stroke="currentColor" />
                <circle cx="32" cy="16" r="12" fill="currentColor" fillOpacity="0.16" stroke="currentColor" />
            </g>
            <ellipse cx="47" cy="35" rx="2.2" ry="1.2" fill="currentColor" className="animate-drift" />
        </svg>
    )
}

/**
 * The latest tick in words, opening its page: `Last tick 3m ago`, with its status when it is not `ok`, in the color the
 * header's readout gives it, so a tick that failed never reads as a quiet one, or while it runs, how long it has.
 */
function TickLine({ tick }: { tick: Tick }) {
    const shown = tick.status === 'ok' || tick.ended_at === null ? null : tick.status
    return (
        <Link
            to="/workspace/ticks/$id"
            params={{ id: String(tick.id) }}
            className={cn('underline-offset-4 hover:underline', TICK_TONE[tick.status])}
            data-testid="all-clear-tick"
        >
            {tick.ended_at === null ? (
                <>
                    Tick running <Age variant="span" started={tick.started_at} ended={null} className={AGE} />
                </>
            ) : (
                <>
                    {tick.dry_run ? 'Last dry run' : 'Last tick'}
                    {shown !== null && (
                        <>
                            {' '}
                            <Word word={shown} />
                        </>
                    )}{' '}
                    <Age at={tick.ended_at} variant="ago" className={AGE} />
                </>
            )}
        </Link>
    )
}
