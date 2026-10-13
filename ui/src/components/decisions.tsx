import { ExternalLink } from 'lucide-react'

import type { Decision } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreLink } from '@/components/chore-link'
import { PullRequestLink } from '@/components/pull-request-link'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { TicketLink } from '@/components/ticket-link'
import { actionTone } from '@/lib/decisions'
import type { ActionTone } from '@/lib/decisions'
import { cn } from '@/lib/utils'

// Written out so Tailwind finds them.
const TONE: Record<ActionTone, string> = {
    refused: 'border-status-failed/40 text-status-failed',
    attention: 'border-status-blocked/40 text-status-blocked',
    other: '',
}

/**
 * Decisions, one row each: what it was about (or, on a ticket's page, which tick), the action, and the rationale. A
 * rationale is the overseer's text: untrusted, laid out as `RichText`, which renders it as text.
 */
export function Decisions({ decisions, byTick = false }: { decisions: Decision[]; byTick?: boolean }) {
    return (
        <ul className="divide-y" data-testid="decisions">
            {decisions.map((decision) => (
                <li
                    key={decision.id}
                    className="flex flex-col gap-1 px-3 py-2.5"
                    data-testid={`decision-${decision.id}`}
                >
                    <div className="flex items-center gap-3">
                        {byTick ? (
                            <TickLink id={decision.tick_id} className="w-16 shrink-0" />
                        ) : (
                            <Subject decision={decision} />
                        )}
                        <Chip className={TONE[actionTone(decision.action)]} word={decision.action} />
                        {decision.pr && (
                            <a
                                href={decision.pr}
                                target="_blank"
                                rel="noreferrer noopener"
                                className={cn(
                                    'inline-flex min-w-0 items-center gap-1 truncate',
                                    'font-mono text-xs text-accent underline-offset-4 hover:underline',
                                )}
                            >
                                {decision.pr.replace(/^https:\/\//u, '')}
                                <ExternalLink className="size-3 shrink-0" />
                            </a>
                        )}
                        {byTick && <Age at={decision.at} className="ml-auto" />}
                    </div>
                    <RichText text={decision.rationale} lines={SUMMARY_LINES} />
                </li>
            ))}
        </ul>
    )
}

/** A ticket, a chore, or a PR no ticket owns as a link to its page; a repository or the whole tick as the CLI says. */
function Subject({ decision }: { decision: Decision }) {
    const cell = 'w-36 shrink-0 truncate'
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
        return (
            <PullRequestLink url={decision.pr} className={cell}>
                pr
            </PullRequestLink>
        )
    }
    return (
        <span className={cn(cell, 'font-mono text-xs text-muted-foreground')} title={decision.subject}>
            {decision.subject}
        </span>
    )
}
