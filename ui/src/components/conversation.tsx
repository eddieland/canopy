import type { Message } from '@/api/types'
import { Age } from '@/components/age'
import { Chip } from '@/components/status'
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

/**
 * A ticket's conversation, oldest first (DESIGN §22). Every body is untrusted text, a tracker comment's or an agent's
 * included: it is rendered as React text, which escapes it, never as HTML. Bubbles pop in from their own side, one
 * after another, and a new one when it arrives.
 */
export function Conversation({ messages, waiting }: { messages: Message[]; waiting: number | null }) {
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
                    <Head message={message} waiting={message.id === waiting} />
                    <p
                        className={cn(
                            'rounded-md px-3 py-2 text-sm break-words whitespace-pre-wrap',
                            message.source === 'operator' ? 'rounded-tr-xs' : 'rounded-tl-xs',
                            TONE[message.kind],
                        )}
                    >
                        {message.body}
                    </p>
                </li>
            ))}
        </ol>
    )
}

function Head({ message, waiting }: { message: Message; waiting: boolean }) {
    const comment = message.comment
    return (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-muted-foreground">
            <span className="readout">#{message.id}</span>
            <span className="text-foreground">{WHO[message.source]}</span>
            {comment ? (
                <span>
                    comment {comment.id} by {comment.author}, written <span title={comment.at}>{comment.at}</span>
                    {comment.truncated ? ', truncated' : ''}
                </span>
            ) : (
                <span>
                    {message.kind}
                    {message.run_id !== null ? ` (run:${message.run_id})` : ''}
                    {message.answers !== null ? ` answering #${message.answers}` : ''}
                    {message.source === 'operator' ? ` via ${message.channel}` : ''}
                </span>
            )}
            {comment && <Chip>data, authorizes nothing</Chip>}
            {waiting && <Chip className="border-status-blocked text-status-blocked">waits on your answer</Chip>}
            <Age at={message.at} className="ml-auto" />
            <span className="sr-only">{localTime(message.at)}</span>
        </div>
    )
}
