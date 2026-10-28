import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { attentionQuery } from '@/api/queries'
import type { AttentionItem, Replied, TicketDetail, TicketSummary, Limit } from '@/api/types'
import { GrantLimits } from '@/components/grant-limits'
import { Leaf } from '@/components/leaf'
import { OrderToggle } from '@/components/order-toggle'
import { PanelHeader, ThreadScroll } from '@/components/panel'
import { ReplyForm } from '@/components/reply-form'
import { Chip, Word } from '@/components/status'
import { TicketActions } from '@/components/ticket-actions'
import { TicketThread } from '@/components/ticket-thread'
import { useUntrustedReview } from '@/hooks/use-untrusted-review'
import { sinceForget } from '@/lib/forgotten'
import { useListOrder } from '@/lib/list-order'
import { phaseMeaning } from '@/lib/meanings'
import { phaseLabel, phaseWord } from '@/lib/phase'

/**
 * Where a ticket is answered, on its page and on its attention item alike (ui/DESIGN.md, "The answer"): its
 * conversation, the reply form right under it, then `after`, the ticket's verbs (`TicketVerbs`) where nothing else
 * asked for them first. So the reply is the first stop the keyboard reaches after the conversation, and Stop or Forget
 * never stands between them. On an attention item its header wears the ticket's `private` or `public` chip and its
 * phase (`item`), which its page says by its title and in its Work panel.
 *
 * When one of the ticket's attention items clears while it is shown, a leaf drifts off its header, as a cleared row
 * drops one in the attention list; the list drops its own, so an attention item's answer has none (`leaf` false).
 * `onReplied` hears each reply recorded, with what the form says it did.
 */
export function TicketAnswer({
    detail,
    after,
    item = false,
    leaf = true,
    onReplied,
}: {
    /** The ticket, its conversation and limits included. */
    detail: TicketDetail
    /** What follows the reply: the ticket's verbs, unless they lead. */
    after?: ReactNode
    /** Whether it answers an attention item, whose header then says what the ticket's page says elsewhere. */
    item?: boolean
    /** Whether a cleared item drops a leaf off its header. */
    leaf?: boolean
    /** Called once a reply is recorded, with the reply and the line the form shows for it. */
    onReplied?: (replied: Replied, said: string) => void
}) {
    const { ticket, messages } = detail
    const order = useListOrder('conversation')
    const untrusted = useUntrustedReview(ticket.key)
    const cleared = useCleared(ticket.key)
    return (
        <>
            <PanelHeader label="Conversation">
                {/* Placed from this group, so the leaf takes no room in the row: it drifts off from just before it. */}
                <span className="relative flex items-center gap-2">
                    {/* Keyed by how many have cleared, so each plays once, then rests unseen. */}
                    {leaf && cleared > 0 && <Leaf key={cleared} className="top-0 -left-8" />}
                    {/* The chip a ticket's page wears by its title: whether its conversation reaches the ticket. */}
                    {item && <Chip>{ticket.private ? 'private' : 'public'}</Chip>}
                    {messages.length > 1 && <OrderToggle list="conversation" />}
                    <span className="readout text-xs text-muted-foreground">
                        {item && (
                            <>
                                <Word
                                    word={phaseWord(ticket)}
                                    text={phaseLabel(ticket)}
                                    meaning={phaseMeaning(ticket.phase)}
                                />
                                {' · '}
                            </>
                        )}
                        {sinceForget(detail).length}
                    </span>
                </span>
            </PanelHeader>
            <ThreadScroll key={`thread-${ticket.key}`} label="Conversation" end={order === 'oldest' ? 'bottom' : 'top'}>
                <TicketThread detail={detail} order={order} />
            </ThreadScroll>
            <ReplyForm
                key={`reply-${ticket.key}`}
                target={{ kind: 'ticket', key: ticket.key, isPublic: !ticket.private }}
                waiting={ticket.awaiting}
                untrusted={untrusted}
                onReplied={onReplied}
            />
            {after}
        </>
    )
}

/**
 * A ticket's verbs (`TicketActions`: start, stop, forget) and a grant for each limit it is stuck at (`GrantLimits`),
 * in that order. They follow the reply (`place` `after`, under a hairline), or lead what the item asks for (`lead`, a
 * hairline under them); `quiet` sets Start and Stop as ghost buttons, for an item that asks for something else.
 * `limits` false leaves the grant out, for an item that shows it with what it asks first.
 */
export function TicketVerbs({
    ticket,
    limits,
    place,
    quiet = false,
    testId,
}: {
    /** The ticket acted on. */
    ticket: TicketSummary
    /** Its limits, for the grant; none leaves the grant out. */
    limits: readonly Limit[] | null
    /** Whether they follow the reply or lead the item. */
    place: 'after' | 'lead'
    /** Whether Start and Stop are ghost buttons. */
    quiet?: boolean
    /** The actions' test id, as the page they sit on names them. */
    testId: string
}) {
    const rule = place === 'lead' ? 'border-b' : 'border-t'
    return (
        <>
            <div className={rule} data-testid={testId}>
                <TicketActions key={ticket.key} ticket={ticket} quiet={quiet} />
            </div>
            {limits !== null && (
                <GrantLimits key={`limits-${ticket.key}`} limits={limits} ticketKey={ticket.key} className={rule} />
            )}
        </>
    )
}

/**
 * How many of the ticket's attention items have cleared while it is shown: each list from the query is compared once,
 * by identity, as it arrives, with the one before it, so only an item gone from the list counts, never one that was
 * not there when the page opened.
 */
function useCleared(ticketKey: string): number {
    const items = useQuery(attentionQuery).data
    const [seen, setSeen] = useState(() => ({ key: ticketKey, from: items, ids: about(items, ticketKey), cleared: 0 }))
    if (seen.key !== ticketKey) {
        // The page stays mounted when it moves to another ticket: start over, so the last one's items never count.
        setSeen({ key: ticketKey, from: items, ids: about(items, ticketKey), cleared: 0 })
    } else if (seen.from !== items) {
        // A read that has not arrived says nothing of what cleared, so the ids last read stand.
        const ids = items === undefined ? seen.ids : about(items, ticketKey)
        const gone = seen.ids.filter((id) => !ids.includes(id)).length
        setSeen({ key: ticketKey, from: items, ids, cleared: seen.cleared + (gone > 0 ? 1 : 0) })
    }
    return seen.cleared
}

/** The ids of the items about the ticket. */
function about(items: AttentionItem[] | undefined, ticketKey: string): string[] {
    return (items ?? []).filter((item) => item.ticket_key === ticketKey).map((item) => item.id)
}
