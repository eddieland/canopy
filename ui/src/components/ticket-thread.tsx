import { Fragment, useState } from 'react'

import type { TicketDetail, TicketForget } from '@/api/types'
import { Age } from '@/components/age'
import { Conversation } from '@/components/conversation'
import type { Pending } from '@/components/conversation'
import { Disclosure } from '@/components/disclosure'
import { Empty } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { WorkingNow } from '@/components/working-now'
import { attempts, sinceForget } from '@/lib/forgotten'
import type { Attempt } from '@/lib/forgotten'
import { ordered } from '@/lib/list-order'
import type { Order } from '@/lib/list-order'

// A message from before a forget waits on no tick: the loop never reads it again.
const HISTORY: Pending = { label: '', title: '', test: () => false }

/**
 * A ticket's conversation inside its `ThreadScroll`, in the operator's order, ending on the run working it now. Each
 * time its work was forgotten heads the attempt it ended, at the oldest end: when, how, and the branch and PRs it
 * dropped, with that attempt's messages folded under it, so the thread reads as the loop does; `Show N earlier
 * messages` opens them, for the history they still are.
 */
export function TicketThread({ detail, order }: { detail: TicketDetail; order: Order }) {
    const { ticket, forgets } = detail
    const current = sinceForget(detail)
    const ended = ordered('conversation', order, attempts(detail))
    const latest = forgets.at(-1)
    const folds = ended.map((attempt) => (
        <Forgotten key={attempt.number} attempt={attempt} order={order} latest={attempt.forget === latest} />
    ))
    let body
    if (current.length > 0) {
        body = <Conversation messages={ordered('conversation', order, current)} waiting={ticket.awaiting} />
    } else if (latest === undefined) {
        body = <Empty>no messages yet: what you and its workers say shows here</Empty>
    } else {
        body = <Empty>no messages since its work was forgotten: what you and its workers say next shows here</Empty>
    }
    return (
        <>
            {/* The run working the ticket now is its newest word, so it sits at the newest end. */}
            {order === 'newest' && <WorkingNow ticketKey={ticket.key} />}
            {order === 'oldest' && folds}
            {body}
            {order === 'newest' && folds}
            {order === 'oldest' && <WorkingNow ticketKey={ticket.key} />}
        </>
    )
}

/** One forget, heading the messages of the attempt it ended, folded under it until opened. */
function Forgotten({ attempt, order, latest }: { attempt: Attempt; order: Order; latest: boolean }) {
    const [open, setOpen] = useState(false)
    const { forget, messages } = attempt
    const what = `${messages.length} earlier ${messages.length === 1 ? 'message' : 'messages'}`
    return (
        <Collapsible open={open} onOpenChange={setOpen} data-testid="forgotten">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 pt-3 text-xs text-muted-foreground">
                <span>
                    work forgotten <Age at={forget.at} variant="ago" />
                    {forget.channel === null ? '' : ` via ${forget.channel}`}
                    {latest ? ': the loop reads only what came after' : ''}
                </span>
                {messages.length > 0 && <Disclosure open={open} what={what} className="ml-auto" />}
                <Dropped forget={forget} />
            </div>
            <CollapsibleContent className="opacity-70">
                <Conversation messages={ordered('conversation', order, messages)} pending={HISTORY} />
            </CollapsibleContent>
        </Collapsible>
    )
}

/** The branch and PRs a forget dropped, which are the operator's to delete and close; nothing for one unrecorded. */
function Dropped({ forget }: { forget: TicketForget }) {
    const prs = forget.prs ?? []
    if (forget.branch === null && prs.length === 0) {
        return null
    }
    // Words between them, so the line reads as one sentence, to a screen reader too.
    return (
        <span className="basis-full">
            dropped
            {forget.branch !== null && (
                <>
                    {' branch '}
                    <span className="font-mono">{forget.branch}</span>
                </>
            )}
            {prs.map((url, index) => (
                <Fragment key={url}>
                    {index > 0 || forget.branch !== null ? ', ' : ' '}
                    <PullRequestLink url={url} />
                </Fragment>
            ))}
        </span>
    )
}
