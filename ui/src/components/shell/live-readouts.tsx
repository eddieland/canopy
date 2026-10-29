import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Wallet } from 'lucide-react'

import { loopQuery, metaQuery, spendQuery, tickQuery } from '@/api/queries'
import type { MemoryState, SpendMonth, Tick } from '@/api/types'
import { Age } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { Word } from '@/components/status'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { useLoopDown } from '@/hooks/use-loop-down'
import { useTickAsked } from '@/hooks/use-tick-asked'
import { costText } from '@/lib/cost-total'
import { counted } from '@/lib/descriptions'
import { tickRef } from '@/lib/refs'
import { BUDGET_WORD, budgetPartsText, budgetPercent, budgetState, budgetText, monthName } from '@/lib/spend'
import type { BudgetState } from '@/lib/spend'
import { TICK_TONE } from '@/lib/ticks'
import { useClock } from '@/lib/clock'
import { age, lasted, localTime, stamp, useNow } from '@/lib/time'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

import { HostReadout } from './host-readout'
import { CardRow, CardRows, ReadoutCard, ReadoutHover } from './readout-card'

// The stream's state, in a word.
const STREAM_LABEL: Record<StreamStatus, string> = {
    connecting: 'opening',
    open: 'live',
    reconnecting: 'retrying',
    closed: 'offline',
}

// A pill beside the name: `mock`, and the stream's word with its dot. Its capitals are trimmed to their height, so
// they center in it rather than sit high on a line box made for lowercase.
const PILL = 'inline-flex h-5 items-center gap-1.5 rounded-full border px-2 [text-box:trim-both_cap_alphabetic]'

// The stream's pill, in the accent while live, muted while it connects, and in the color of what waits on the operator
// once it has been down a while.
const PILL_TONE = {
    open: 'border-accent/30 bg-accent/14 text-accent',
    waiting: 'border-border text-muted-foreground',
    down: 'border-status-blocked/40 bg-status-blocked/10 text-status-blocked',
} as const

// The budget's readout, muted while on budget, as `host ok` is, and in a state's color once it wants a look.
const BUDGET_TONE: Record<BudgetState, string> = {
    under: 'text-muted-foreground',
    headed: 'text-status-blocked',
    over: 'text-status-failed',
}

/**
 * The header's readouts: the latest tick, or `no tick yet` before the first, `tick starting` from Tick now until the
 * tick it asked for starts, agent memory while a tier is on, the month against its budget while one is set, and the
 * machine the loop runs on (`HostReadout`). The counters are the attention page's.
 */
export function LiveReadouts() {
    const last = useQuery(tickQuery)
    const starting = useTickAsked()
    const memory = useQuery(loopQuery).data?.memory ?? null
    const budget = useQuery(spendQuery).data?.budget ?? null
    return (
        // Inset as far as a ghost button's label, so the rules either side sit midway between their neighbors.
        <div className="flex items-center gap-4 px-2.5" data-testid="live-readouts">
            {/* Nothing until the read lands, so a workspace that has ticked never flashes `no tick yet`. Starting, it
                says so from the click on, before the tick's row lands. */}
            {starting ? (
                <span
                    className={cn('readout text-xs whitespace-nowrap', TICK_TONE.running)}
                    title="Tick now asked for a tick: the loop starts it as soon as it finishes what it is doing."
                    data-testid="last-tick"
                >
                    tick starting
                </span>
            ) : last.data === undefined ? null : last.data.tick === null ? (
                <span className="readout text-xs whitespace-nowrap text-muted-foreground" data-testid="last-tick">
                    no tick yet
                </span>
            ) : (
                <LastTick tick={last.data.tick} />
            )}
            {memory !== null && <MemoryReadout memory={memory} />}
            {budget !== null && <BudgetReadout month={budget} />}
            <HostReadout />
        </div>
    )
}

/**
 * The stream's state beside the name, and `mock` over fixture data. It sits at the left, before the ticker, so its
 * word hugs its text and a drop moves nothing: the ticker's window gives way, not the actions or the readouts.
 */
export function StreamReadout({ stream }: { stream: StreamStatus }) {
    const clock = useClock()
    const meta = useQuery(metaQuery)
    const down = useLoopDown()
    // Down past the first retry's wait, it says for how long, in the color of what waits on the operator.
    const since = down.offline && down.since !== null ? new Date(down.since).toISOString() : null
    const tone = since === null ? (stream === 'open' ? 'open' : 'waiting') : 'down'
    return (
        <span
            className="readout inline-flex items-center gap-1.5 text-2xs whitespace-nowrap uppercase"
            title={since === null ? undefined : `Down since ${localTime(since, clock)}: the loop isn't answering.`}
            data-testid="stream-status"
            data-status={since === null ? stream : 'down'}
        >
            {meta.data?.mock && <span className={cn(PILL, 'border-border text-muted-foreground')}>mock</span>}
            <span className={cn(PILL, PILL_TONE[tone])}>
                {/* Live, the dot breathes with the logo's. */}
                <span
                    aria-hidden
                    className={cn('size-1.5 rounded-full bg-current', tone === 'open' && 'animate-breathe')}
                />
                {since === null ? (
                    STREAM_LABEL[stream]
                ) : (
                    <span>
                        down · <Age at={since} className="text-2xs text-inherit" />
                    </span>
                )}
            </span>
        </span>
    )
}

/**
 * `tick:12 · 3m ago`, with its status when it is not `ok`, as `canopy status`'s first line names it. Hovered or
 * focused, a card shows the tick at a glance (`TickCard`). It opens the tick's page: what it decided and why.
 */
function LastTick({ tick }: { tick: Tick }) {
    const shown = tick.status === 'ok' ? null : tick.status
    return (
        <ReadoutHover card={<TickCard tick={tick} />} testId="tick-card">
            {/* One link, as the other readouts are, so the word's and the age's facts are its titles rather than tips
            of their own over the card. */}
            <Link
                to="/runs/ticks/$id"
                params={{ id: String(tick.id) }}
                className={cn(
                    'readout text-xs whitespace-nowrap underline-offset-4 hover:underline',
                    TICK_TONE[tick.status] ?? 'text-muted-foreground',
                )}
                data-testid="last-tick"
            >
                {tickRef(tick.id)}
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
            </Link>
        </ReadoutHover>
    )
}

/**
 * The tick at a glance: its status, the overseer's summary, when it started and how long it took, its decisions, what
 * its overseer cost, and what woke the loop for it.
 */
function TickCard({ tick }: { tick: Tick }) {
    const clock = useClock()
    const now = useNow()
    const tokens = tick.new_tokens === null ? '' : `, ${tokenCount(tick.new_tokens)} tokens`
    return (
        <ReadoutCard
            title={tickRef(tick.id)}
            aside={
                <span className={TICK_TONE[tick.status] ?? undefined}>
                    <Word word={tick.status} />
                    {tick.dry_run ? ' · dry run' : ''}
                </span>
            }
        >
            {tick.summary !== null && (
                <p className="line-clamp-4 whitespace-pre-line wrap-break-word text-muted-foreground">
                    <LinkedText text={tick.summary} />
                </p>
            )}
            <CardRows>
                <CardRow label="Started">
                    {stamp(tick.started_at, clock)}
                    {tick.ended_at === null
                        ? `, running for ${age(tick.started_at, now)}`
                        : `, took ${lasted(tick.started_at, tick.ended_at)}`}
                </CardRow>
                <CardRow label="Decisions">{counted(tick.decisions, 'decision')}</CardRow>
                <CardRow label="Overseer">
                    {tick.cost_usd === null ? (
                        'no cost reported'
                    ) : (
                        <span className="readout">{costText(tick.cost_usd)}</span>
                    )}
                    {tokens}
                </CardRow>
                {tick.woken_by !== null && <CardRow label="Woken by">{tick.woken_by}</CardRow>}
            </CardRows>
        </ReadoutCard>
    )
}

/**
 * `memory: recording` while no tier is at `use`, `memory: in use` once one is (DESIGN §28): words, never color alone,
 * so recorded memory is never taken for memory in use. Each tier's mode to a screen reader, and in a card, with what
 * reads it, when hovered or focused; it opens the memory page.
 */
function MemoryReadout({ memory }: { memory: MemoryState }) {
    return (
        <ReadoutHover card={<MemoryCard memory={memory} />} testId="memory-card">
            <Link
                to="/memory"
                className="readout text-xs whitespace-nowrap text-muted-foreground underline-offset-4 hover:underline"
                aria-label={`${memory.readout}: ${memory.tiers}`}
                data-testid="memory-readout"
            >
                {memory.readout}
            </Link>
        </ReadoutHover>
    )
}

/** Agent memory at a glance: each tier's mode and what reads it, and the proposals waiting on the operator. */
function MemoryCard({ memory }: { memory: MemoryState }) {
    return (
        <ReadoutCard title="Agent memory" aside={memory.readout.replace(/^memory: /u, '')}>
            <CardRows>
                <CardRow label="Notes">{memory.ticket_notes.band}</CardRow>
                <CardRow label="Lessons">{memory.lessons.band}</CardRow>
                {memory.proposals_waiting > 0 && (
                    <CardRow label="Proposals">
                        <span className="text-status-blocked">
                            {counted(memory.proposals_waiting, 'proposal')} waiting on you
                        </span>
                    </CardRow>
                )}
            </CardRows>
        </ReadoutCard>
    )
}

/**
 * A wallet's icon and `39%`: the local month's spend against the budget set, muted while on budget, in
 * `status-blocked` once its pace heads over, and in `status-failed` once it is over, said in words to a screen reader
 * and in a card, with the numbers, when hovered or focused. Under `2xl`, the icon alone, in that color, as the host's
 * readout is under `lg`. It opens the spend page.
 */
function BudgetReadout({ month }: { month: SpendMonth }) {
    const state = budgetState(month)
    const said = `${BUDGET_WORD[state]}: ${budgetText(month)}`
    return (
        <ReadoutHover card={<BudgetCard month={month} />} testId="budget-card">
            <Link
                to="/reports/spend"
                className={cn(
                    'readout inline-flex items-center gap-1.5 text-xs whitespace-nowrap underline-offset-4',
                    'hover:underline',
                    BUDGET_TONE[state],
                )}
                aria-label={said}
                data-testid="budget-readout"
                data-state={state}
            >
                <Wallet aria-hidden className="size-3.5 shrink-0" />
                {/* Short of `2xl` the ticker needs the room, or a tick's readout widening as it starts steps it
                out. */}
                <span className="hidden 2xl:inline">{budgetPercent(month)}%</span>
            </Link>
        </ReadoutHover>
    )
}

/** The month against its budget at a glance: what it spent, where its pace takes it, and what the spend is made of. */
function BudgetCard({ month }: { month: SpendMonth }) {
    const clock = useClock()
    const state = budgetState(month)
    return (
        <ReadoutCard title={monthName(month)} aside={<span className={BUDGET_TONE[state]}>{BUDGET_WORD[state]}</span>}>
            <CardRows>
                <CardRow label="Spent">
                    <span className={cn('readout', state !== 'under' && BUDGET_TONE[state])}>
                        {budgetPercent(month)}%
                    </span>
                    {`, ${costText(month.spent_usd ?? 0)} of $${month.budget_usd}`}
                </CardRow>
                <CardRow label="Pace">
                    {month.projected_usd === null
                        ? 'not known yet'
                        : `${costText(month.projected_usd)} by the month's end`}
                </CardRow>
                <CardRow label="Month">{`${Math.round(month.elapsed * 100)}% gone by`}</CardRow>
                <CardRow label="Made of">{budgetPartsText(month, clock)}</CardRow>
            </CardRows>
        </ReadoutCard>
    )
}
