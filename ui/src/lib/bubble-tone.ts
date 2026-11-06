import type { Message } from '@/api/types'

/**
 * Each kind of message's bubble, written out so Tailwind finds them: the operator's own words on the right in the
 * accent's tint, a worker's on the raised surface, a tracker comment quoted, a hairline on the panel's own surface,
 * since it is data from outside the loop, and canopy's note on what a tick did as a muted dashed outline, since it is
 * about the loop rather than the work. A question is on the raised surface once answered; the one still open is
 * `OPEN_QUESTION`.
 */
export const BUBBLE_TONE: Record<Message['kind'], string> = {
    report: 'bg-surface-raised',
    question: 'bg-surface-raised',
    reply: 'bg-accent/18',
    comment: 'border bg-surface',
    note: 'border border-dashed text-muted-foreground',
}

/** The question still waiting on the operator, in the tint and hairline of what waits on a person: the amber bubble. */
export const OPEN_QUESTION = 'border border-status-blocked/40 bg-status-blocked/8'
