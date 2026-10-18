import type { Message, TicketDetail } from '@/api/types'

/**
 * The messages of a ticket's conversation since the operator last forgot its work (DESIGN §22), which are the ones
 * the loop still reads; every message when it was never forgotten.
 */
export function sinceForget(detail: Pick<TicketDetail, 'messages' | 'forgotten_message_id'>): Message[] {
    const before = detail.forgotten_message_id
    return before === null ? detail.messages : detail.messages.filter((message) => message.id > before)
}
