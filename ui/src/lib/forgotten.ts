import type { Message, TicketDetail, TicketForget } from '@/api/types'

/** One forget of a ticket's work, and the messages of the attempt it ended: after the forget before it, if any. */
export interface Attempt {
    /** Its place among the ticket's attempts, from 1. */
    number: number
    /** The forget that ended it. */
    forget: TicketForget
    /** What was said in it, oldest first. */
    messages: Message[]
}

type Forgotten = Pick<TicketDetail, 'messages' | 'forgets'>

/**
 * The messages of a ticket's conversation since the operator last forgot its work (DESIGN §22), which are the ones
 * the loop still reads; every message when it was never forgotten.
 */
export function sinceForget(detail: Forgotten): Message[] {
    const before = detail.forgets.at(-1)?.message_id ?? 0
    return detail.messages.filter((message) => message.id > before)
}

/** Each attempt a forget ended, oldest first, with the messages said in it that the conversation holds. */
export function attempts(detail: Forgotten): Attempt[] {
    let after = 0
    return detail.forgets.map((forget, index) => {
        const upTo = forget.message_id ?? after
        const messages = detail.messages.filter((message) => message.id > after && message.id <= upTo)
        after = Math.max(after, upTo)
        return { number: index + 1, forget, messages }
    })
}
