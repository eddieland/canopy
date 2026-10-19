import type { AttentionItem, Message, TicketSummary } from '@/api/types'

/**
 * Whether one of the operator's messages still waits for a tick (DESIGN §22): no `ok` tick has read it, so
 * the overseer has not acted on it and the attention list is from before it. `acknowledged` is the newest message the
 * latest `ok` tick read, null before the first.
 */
export function awaitsTick(message: Pick<Message, 'id' | 'source'>, acknowledged: number | null): boolean {
    return message.source === 'operator' && (acknowledged === null || message.id > acknowledged)
}

/**
 * Whether an item was answered since the tick that listed it: an `awaiting_reply` item's ticket, still started, or
 * public with a planner's question (DESIGN §25), waits on no question now, or a `plan_review` item's plan waits on the
 * operator no more, approved, skipped, or sent back for changes. The list is the latest `ok` tick's (DESIGN §14), so
 * the item stays until the next one.
 */
export function answered(item: AttentionItem, tickets: TicketSummary[] | undefined): boolean {
    if (item.ticket_key === null) {
        return false
    }
    const ticket = tickets?.find((t) => t.key === item.ticket_key)
    if (ticket === undefined) {
        return false
    }
    switch (item.reason) {
        case 'awaiting_reply': {
            return ticket.start !== 'stopped' && ticket.awaiting === null
        }
        case 'plan_review': {
            return !ticket.plan_waits
        }
        default: {
            return false
        }
    }
}
