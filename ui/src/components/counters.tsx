import type { ReactNode } from 'react'

import { useQuery } from '@tanstack/react-query'

import { attentionQuery, runsQuery, spendQuery, ticketsQuery } from '@/api/queries'
import { Age } from '@/components/age'
import { Skeleton } from '@/components/ui/skeleton'
import { severity, type Severity } from '@/lib/attention'
import { cn } from '@/lib/utils'

type Tone = 'running' | 'blocked' | 'failed' | 'accent' | 'plain'

// Written out so Tailwind finds them: each counter's top rule.
const RULE: Record<Tone, string> = {
    running: 'border-t-status-running',
    blocked: 'border-t-status-blocked',
    failed: 'border-t-status-failed',
    accent: 'border-t-accent',
    plain: 'border-t-border',
}

/** The loop at a glance, above the attention list: what runs, what waits on you, what needs you, what it cost. */
export function Counters() {
    const runs = useQuery(runsQuery)
    const tickets = useQuery(ticketsQuery)
    const attention = useQuery(attentionQuery)
    const spend = useQuery(spendQuery)

    const running = runs.data?.filter((r) => r.state === 'running').length
    const waiting = tickets.data?.filter((t) => t.awaiting !== null).length
    const questions = attention.data?.filter((i) => i.reason === 'awaiting_reply').map((i) => i.since)
    const oldest = questions?.toSorted()[0]
    const counts = attention.data?.reduce<Partial<Record<Severity, number>>>((found, item) => {
        const s = severity(item)
        found[s] = (found[s] ?? 0) + 1
        return found
    }, {})
    const broken = (counts?.failed ?? 0) > 0
    const cost = spend.data?.cost_usd

    return (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(12rem,1fr))] gap-3" data-testid="counters">
            <Counter label="Running" value={running} tone="running">
                {running === undefined ? null : `${runs.data?.filter((r) => r.state === 'blocked').length} blocked`}
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
            <Counter
                label="Spent, 24h"
                value={spend.data === undefined ? undefined : cost === null || cost === undefined ? '–' : usd(cost)}
                tone="accent"
            >
                {spend.data === undefined ? null : cost === null ? 'nothing reported' : 'overseer and workers'}
            </Counter>
        </div>
    )
}

function usd(cost: number): string {
    return `$${cost.toFixed(2)}`
}

function breakdown(counts: Partial<Record<Severity, number>>): string {
    const rest = (counts.other ?? 0) + (counts.finding ?? 0)
    const parts = [
        counts.failed && `${counts.failed} failed`,
        counts.waiting && `${counts.waiting} waiting`,
        rest && `${rest} more`,
    ].filter(Boolean)
    return parts.length === 0 ? 'nothing' : parts.join(' · ')
}

/** One counter. Its value keeps a fixed width, and it shows a skeleton only until the first data arrives. */
function Counter({
    label,
    value,
    tone,
    children,
}: {
    label: string
    value: number | string | undefined
    tone: Tone
    children: ReactNode
}) {
    return (
        <div
            className={cn(
                'flex min-w-0 flex-col gap-1.5 rounded-md border border-t-2 bg-surface px-4 py-3',
                RULE[tone],
            )}
            data-testid={`counter-${label.toLowerCase().split(/[ ,]+/)[0]}`}
        >
            <span className="panel-label">{label}</span>
            <span className="readout h-8 text-3xl leading-8 font-medium">
                {value === undefined ? <Skeleton className="h-7 w-12" /> : value}
            </span>
            <span className="truncate text-xs text-muted-foreground">{children}</span>
        </div>
    )
}
