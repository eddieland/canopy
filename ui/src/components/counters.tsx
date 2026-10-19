import { useQuery } from '@tanstack/react-query'

import { attentionQuery, runsQuery, ticketsQuery } from '@/api/queries'
import { Age } from '@/components/age'
import { Counter } from '@/components/counter'
import { answered } from '@/lib/acknowledged'
import { countBySeverity } from '@/lib/attention'

/**
 * The loop at a glance, above the attention list: what runs, what waits on you, and what needs you. What it cost is
 * in the rail, on every page. Only Waiting on you has a line under its value, the oldest question's age, since it has
 * no other home: what waits on you is that counter's value, and how the list splits is the nav's badge.
 */
export function Counters() {
    const runs = useQuery(runsQuery)
    const tickets = useQuery(ticketsQuery)
    const attention = useQuery(attentionQuery)

    const running = runs.data?.filter((r) => r.state === 'running').length
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
            <Counter label="Running" value={running} tone="running" />
            <Counter label="Waiting on you" value={waiting} tone="blocked">
                {oldest === undefined ? (
                    'no question open'
                ) : (
                    <>
                        oldest <Age at={oldest} className="inline" />
                    </>
                )}
            </Counter>
            <Counter label="Attention" value={attention.data?.length} tone={broken ? 'failed' : 'plain'} />
        </div>
    )
}
