import { useQuery } from '@tanstack/react-query'

import { tickQuery } from '@/api/queries'
import type { Message } from '@/api/types'
import { Age } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { Timestamp } from '@/components/timestamp'
import { awaitsTick } from '@/lib/acknowledged'
import { messageRef } from '@/lib/refs'
import { localTime } from '@/lib/time'
import { cn } from '@/lib/utils'

const WHO: Record<Message['source'], string> = {
    worker: 'worker',
    operator: 'you',
    tracker: 'tracker',
}

// Written out so Tailwind finds them. Each message is a bubble: the operator's own words on the right in the accent's
// tint, a question in the tint of what waits on a person, anything else on the raised surface.
const TONE: Record<Message['kind'], string> = {
    report: 'bg-surface-raised',
    question: 'bg-status-blocked/12',
    reply: 'bg-accent/12',
    comment: 'bg-surface-raised',
}

const UNREAD = 'No tick has read it yet. The loop acts on it, and the attention list catches up, at the next tick.'

/** Which of the operator's messages nothing has read yet, and what the chip on each says and explains. */
export interface Pending {
    /** The chip's text. */
    label: string
    /** The chip's tooltip: what the state means for the message. */
    title: string
    /** Whether a message is in this state. */
    test: (message: Message) => boolean
}

/**
 * A ticket's conversation, or a chore's notes, in the order given: oldest first unless flipped (DESIGN §22). Every
 * body is untrusted text, a tracker comment's or an agent's included: it is rendered as React text, which escapes it,
 * never as HTML. Bubbles pop in from their own side, one after another, and a new one when it arrives. The operator's
 * own messages that no `ok` tick has read yet say so: the loop acts on them, and the attention list catches up, at the
 * next tick. A chore's notes say instead which its next run reads (`pending`).
 */
export function Conversation({
    messages,
    waiting = null,
    pending,
}: {
    messages: Message[]
    waiting?: number | null
    pending?: Pending
}) {
    const acknowledged = useQuery(tickQuery).data?.acknowledged
    const unread: Pending = pending ?? {
        label: 'waiting for the next tick',
        title: UNREAD,
        test: (message) => acknowledged !== undefined && awaitsTick(message, acknowledged),
    }
    return (
        <ol className="stagger flex flex-col gap-3 p-3" data-testid="conversation">
            {messages.map((message) => (
                <li
                    key={message.id}
                    data-testid={`message-${message.id}`}
                    data-source={message.source}
                    className={cn(
                        'flex w-full max-w-2xl flex-col gap-1 [--enter:pop]',
                        message.source === 'operator' ? 'origin-top-right self-end' : 'origin-top-left',
                    )}
                >
                    <Head
                        message={message}
                        waiting={message.id === waiting}
                        unread={unread.test(message) ? unread : null}
                    />
                    <p
                        className={cn(
                            'rounded-md px-3 py-2 text-sm break-words whitespace-pre-wrap',
                            message.source === 'operator' ? 'rounded-tr-xs' : 'rounded-tl-xs',
                            TONE[message.kind],
                        )}
                    >
                        <LinkedText text={message.body} chips />
                    </p>
                </li>
            ))}
        </ol>
    )
}

function Head({ message, waiting, unread }: { message: Message; waiting: boolean; unread: Pending | null }) {
    const comment = message.comment
    return (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-muted-foreground">
            <span className="readout">{messageRef(message.id)}</span>
            <span className="text-foreground">{WHO[message.source]}</span>
            {comment ? (
                <span>
                    comment {comment.id} by {comment.author}, written <Timestamp at={comment.at} />
                    {comment.truncated ? ', truncated' : ''}
                </span>
            ) : (
                <span>
                    {message.kind}
                    {message.run_id !== null && (
                        <>
                            {' ('}
                            <RunLink id={message.run_id} />)
                        </>
                    )}
                    {message.answers === null ? '' : ` answering ${messageRef(message.answers)}`}
                    {message.source === 'operator' ? ` via ${message.channel}` : ''}
                </span>
            )}
            {comment && <Chip>data, authorizes nothing</Chip>}
            {waiting && <Chip className="border-status-blocked text-status-blocked">waiting on you</Chip>}
            {unread && (
                <span title={unread.title}>
                    <Chip className="border-status-running/40 text-status-running">{unread.label}</Chip>
                </span>
            )}
            <Age at={message.at} variant="ago" className="ml-auto" />
            <span className="sr-only">{localTime(message.at)}</span>
        </div>
    )
}
