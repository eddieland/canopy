import { useQuery } from '@tanstack/react-query'

import { attentionQuery, runsQuery, ticketsQuery } from '@/api/queries'
import { Age } from '@/components/age'
import { Counter } from '@/components/counter'
import { answered } from '@/lib/acknowledged'
import { countBySeverity, type Severity } from '@/lib/attention'
import { latestRuns } from '@/lib/run-state'

/**
 * The loop at a glance, above the attention list: what runs, what waits on you, and what needs you. What it cost is
 * in the rail, on every page.
 */
export function Counters() {
    const runs = useQuery(runsQuery)
    const tickets = useQuery(ticketsQuery)
    const attention = useQuery(attentionQuery)

    const running = runs.data?.filter((r) => r.state === 'running').length
    // A ticket counts once, by its latest run: an earlier question a later run took up waits on nothing.
    const blocked = runs.data === undefined ? undefined : latestRuns(runs.data).filter((r) => r.state === 'blocked')
    const waiting = tickets.data?.filter((t) => t.awaiting !== null).length
    // An answered question stays on the list until the next tick; it waits on the loop now, not on you.
    const questions = attention.data
        ?.filter((i) => i.reason === 'awaiting_reply' && !answered(i, tickets.data))
        .map((i) => i.since)
    const oldest = questions?.toSorted()[0]
    const counts = attention.data === undefined ? undefined : countBySeverity(attention.data)
    const broken = (counts?.failed ?? 0) > 0

    return (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(12rem,1fr))] gap-3" data-testid="counters">
            <Counter label="Running" value={running} tone="running">
                {blocked === undefined ? null : `${blocked.length} blocked`}
            </Counter>
            <Counter label="Waiting on you" value={waiting} tone="blocked">
                {oldest === undefined ? (
                    'no question open'
                ) : (
                    <>
                        oldest <Age at={oldest} className="inline" />
                    </>
                )}
            </Counter>
            <Counter label="Attention" value={attention.data?.length} tone={broken ? 'failed' : 'plain'}>
                {counts === undefined ? null : breakdown(counts)}
            </Counter>
        </div>
    )
}

function breakdown(counts: Record<Severity, number>): string {
    const rest = counts.other + counts.finding
    const parts = [
        counts.failed && `${counts.failed} failed`,
        counts.waiting && `${counts.waiting} waiting`,
        rest && `${rest} more`,
    ].filter(Boolean)
    return parts.length === 0 ? 'nothing' : parts.join(' · ')
}
