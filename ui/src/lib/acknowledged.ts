import type { AttentionItem, Message, TaskSummary, TicketSummary } from '@/api/types'

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
 * operator no more, approved, skipped, or sent back for changes. The overseer raises a waiting feedback plan as
 * `plan_review` too (DESIGN §32), so that item is answered only once neither the ticket's plan nor its feedback plan
 * waits. A task's `awaiting_reply` item is answered once its
 * task waits on no reply, replied to or stopped (DESIGN §36). The list is the latest `ok` tick's (DESIGN §14), so the
 * item stays until the next one.
 */
export function answered(
    item: AttentionItem,
    tickets: TicketSummary[] | undefined,
    tasks?: readonly TaskSummary[],
): boolean {
    if (item.task !== null) {
        const task = tasks?.find((t) => t.id === item.task)
        return item.reason === 'awaiting_reply' && task !== undefined && task.standing !== 'awaiting_reply'
    }
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
            return !ticket.plan_waits && ticket.feedback_plan === null
        }
        default: {
            return false
        }
    }
}
