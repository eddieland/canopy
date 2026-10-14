import type { Decision } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreLink } from '@/components/chore-link'
import { PullRequestLink } from '@/components/pull-request-link'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { ListRow } from '@/components/rows'
import { Chip } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { TicketLink } from '@/components/ticket-link'
import { actionTone } from '@/lib/decisions'
import type { ActionTone } from '@/lib/decisions'
import { rowLineFrom } from '@/lib/rows'
import { cn } from '@/lib/utils'

// Written out so Tailwind finds them.
const TONE: Record<ActionTone, string> = {
    refused: 'border-status-failed/40 text-status-failed',
    attention: 'border-status-blocked/40 text-status-blocked',
    other: '',
}

/**
 * Decisions, one row each: what it was about (or, on its subject's page, which tick), the action, and under it the
 * rationale. A rationale is the overseer's text: untrusted, laid out as `RichText`, which renders it as text.
 */
export function Decisions({ decisions, byTick = false }: { decisions: Decision[]; byTick?: boolean }) {
    return (
        <ul className="divide-y" data-testid="decisions">
            {decisions.map((decision) => (
                <ListRow
                    key={decision.id}
                    kind={byTick ? 'own-decision' : 'decision'}
                    data-testid={`decision-${decision.id}`}
                >
                    {byTick ? <TickLink id={decision.tick_id} /> : <Subject decision={decision} />}
                    <span className="flex min-w-0 items-center gap-3">
                        <Chip
                            className={cn(TONE[actionTone(decision.action)], 'min-w-0 shrink')}
                            word={decision.action}
                        />
                        {/* A PR that is the row's subject is named there already. */}
                        {decision.pr && (byTick || !prIsSubject(decision)) && <PullRequestLink url={decision.pr} />}
                    </span>
                    {byTick && <Age at={decision.at} variant="ago" className="text-right" />}
                    <RichText text={decision.rationale} lines={SUMMARY_LINES} className={rowLineFrom('action')} />
                </ListRow>
            ))}
        </ul>
    )
}

/** A ticket, a chore, or a PR no ticket owns as a link to its page; a repository or the whole tick as the CLI says. */
function Subject({ decision }: { decision: Decision }) {
    const cell = 'truncate'
    if (decision.chore !== null) {
        return <ChoreLink name={decision.chore} className={cell} />
    }
    if (decision.ticket_key !== null) {
        return (
            <span className={cn(cell, 'font-mono text-xs text-muted-foreground')}>
                <TicketLink ticketKey={decision.ticket_key} />
                {decision.repo === null ? '' : ` (${decision.repo})`}
            </span>
        )
    }
    if (decision.pr !== null) {
        return <PullRequestLink url={decision.pr} className={cell} />
    }
    return (
        <span className={cn(cell, 'font-mono text-xs text-muted-foreground')} title={decision.subject}>
            {decision.subject}
        </span>
    )
}

/** Whether a decision is about a PR no ticket owns, so its subject is the PR. */
function prIsSubject(decision: Decision): boolean {
    return decision.chore === null && decision.ticket_key === null && decision.pr !== null
}
