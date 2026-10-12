import type { TicketSummary } from '@/api/types'

/** A ticket's phase as the operator reads it, in the CLI's words: the recorded one, else what the last tick decided
 * about it, else that no tick has seen it. The overseer records a decision for every ticket it looks at, but not
 * always a phase. */
export function phaseLabel(ticket: Pick<TicketSummary, 'phase' | 'last_decision'>): string {
    if (ticket.phase !== null) return ticket.phase
    if (ticket.last_decision !== null) return `not recorded, last decision ${ticket.last_decision}`
    return 'not seen by a tick yet'
}
