import type { RunCard } from '@/api/types'
import { Age } from '@/components/age'
import { Clipped } from '@/components/tip'
import { LinkedText } from '@/components/linked-text'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/**
 * Where a worker's, planner's, or reviewer's work stands, in its own words: its card (DESIGN §41), whole. How old it
 * is leads, in tool calls and time; while the run runs, a card that has gone too long without an update is marked
 * stale in the blocked color rather than going quiet. Then its summary, what it does now, what is done with the proof
 * of each, what is next, and what is in its way. Agent text, rendered as text.
 */
export function RunCardView({ card, running }: { card: RunCard; running: boolean }) {
    const stale = isStale(card, useNow())
    return (
        <div
            className={cn('flex flex-col gap-1.5 border-l-2 pl-3', stale ? 'border-status-blocked' : 'border-border')}
            data-testid="run-card"
        >
            <CardAge card={card} running={running} stale={stale} />
            <p className="text-sm">
                <LinkedText text={card.summary} />
            </p>
            <CardLine label="now">
                <LinkedText text={card.now} />
            </CardLine>
            {card.done.map((done, i) => (
                <CardLine key={`done-${i}`} label="done">
                    <LinkedText text={done.step} />
                    <span className="font-mono text-xs text-muted-foreground">
                        {' '}
                        <LinkedText text={done.proof} />
                    </span>
                </CardLine>
            ))}
            {card.next.map((step, i) => (
                <CardLine key={`next-${i}`} label="next">
                    <LinkedText text={step} />
                </CardLine>
            ))}
            {card.stuck !== null && (
                <CardLine label="stuck" labelClassName="text-status-blocked">
                    <LinkedText text={card.stuck} />
                </CardLine>
            )}
        </div>
    )
}

/**
 * A running run's card on one line, for a row: what it says it does now, and how old the card is, marked stale as
 * `RunCardView` marks it.
 */
export function RunCardNow({ card, className }: { card: RunCard; className?: string }) {
    const stale = isStale(card, useNow())
    return (
        <span className={cn('flex min-w-0 items-center gap-2 text-xs', className)} data-testid="run-card-now">
            <span className={cn('shrink-0', stale ? 'text-status-blocked' : 'text-muted-foreground')}>
                {stale ? 'stale card' : 'now'}
            </span>
            <Clipped text={card.now} className="min-w-0" />
            <Age at={card.at} variant="ago" className="shrink-0" />
        </span>
    )
}

/**
 * Whether a running run's card is stale at `now`: it has gone too many tool calls without an update, as the server
 * says, or its time to go stale has come. An ended run's never is.
 */
function isStale(card: RunCard, now: number): boolean {
    return card.stale || (card.stale_at !== null && now >= Date.parse(card.stale_at))
}

function CardAge({ card, running, stale }: { card: RunCard; running: boolean; stale: boolean }) {
    const calls = card.calls_since === 1 ? '1 tool call' : `${card.calls_since} tool calls`
    return (
        <p className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
            <span>{running ? 'card' : 'last card'}</span>
            <Age at={card.at} variant="ago" />
            <span>{running ? `${calls} since` : `${calls} before the run ended`}</span>
            {stale && <span className="text-status-blocked">stale</span>}
        </p>
    )
}

function CardLine({
    label,
    labelClassName,
    children,
}: {
    label: string
    labelClassName?: string
    children: React.ReactNode
}) {
    return (
        <p className="flex gap-2 text-sm">
            <span className={cn('w-10 shrink-0 font-mono text-xs leading-5 text-muted-foreground', labelClassName)}>
                {label}
            </span>
            <span className="min-w-0 break-words">{children}</span>
        </p>
    )
}
