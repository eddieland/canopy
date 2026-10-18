import { useState } from 'react'

import type { Message, TicketDetail } from '@/api/types'
import { Age } from '@/components/age'
import { Conversation } from '@/components/conversation'
import type { Pending } from '@/components/conversation'
import { Disclosure } from '@/components/disclosure'
import { Empty } from '@/components/panel'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { WorkingNow } from '@/components/working-now'
import { sinceForget } from '@/lib/forgotten'
import { ordered } from '@/lib/list-order'
import type { Order } from '@/lib/list-order'

// A message from before a forget waits on no tick: the loop never reads it again.
const HISTORY: Pending = { label: '', title: '', test: () => false }

/**
 * A ticket's conversation inside its `ThreadScroll`, in the operator's order, ending on the run working it now. The
 * messages from before its work was forgotten fold away at the oldest end, under a line saying when, so the thread
 * reads as the loop does; `Show N earlier messages` opens them, for the history they still are.
 */
export function TicketThread({ detail, order }: { detail: TicketDetail; order: Order }) {
    const { ticket, messages, forgotten_at: forgottenAt } = detail
    const current = sinceForget(detail)
    const earlier = messages.slice(0, messages.length - current.length)
    const fold =
        forgottenAt !== null && earlier.length > 0 ? (
            <Forgotten at={forgottenAt} earlier={ordered('conversation', order, earlier)} />
        ) : null
    let body
    if (current.length > 0) {
        body = <Conversation messages={ordered('conversation', order, current)} waiting={ticket.awaiting} />
    } else if (fold === null) {
        body = <Empty>no messages yet: what you and its workers say shows here</Empty>
    } else {
        body = <Empty>no messages since its work was forgotten: what you and its workers say next shows here</Empty>
    }
    return (
        <>
            {/* The run working the ticket now is its newest word, so it sits at the newest end. */}
            {order === 'newest' && <WorkingNow ticketKey={ticket.key} />}
            {order === 'oldest' && fold}
            {body}
            {order === 'newest' && fold}
            {order === 'oldest' && <WorkingNow ticketKey={ticket.key} />}
        </>
    )
}

/** The line where a ticket's work was forgotten, and the messages from before it, folded under it until opened. */
function Forgotten({ at, earlier }: { at: string; earlier: Message[] }) {
    const [open, setOpen] = useState(false)
    const what = `${earlier.length} earlier ${earlier.length === 1 ? 'message' : 'messages'}`
    return (
        <Collapsible open={open} onOpenChange={setOpen} data-testid="forgotten">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 pt-3 text-xs text-muted-foreground">
                <span>
                    work forgotten <Age at={at} variant="ago" />: the loop reads only what came after
                </span>
                <Disclosure open={open} what={what} className="ml-auto" />
            </div>
            <CollapsibleContent className="opacity-70">
                <Conversation messages={earlier} pending={HISTORY} />
            </CollapsibleContent>
        </Collapsible>
    )
}
