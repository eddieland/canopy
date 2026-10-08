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

// Written out so Tailwind finds them. The operator's own words are marked with the accent; a question with the color
// of what waits on a person.
const TONE: Record<Message['kind'], string> = {
    report: 'border-l-border',
    question: 'border-l-status-blocked bg-status-blocked/8',
    reply: 'border-l-accent bg-accent/6',
    comment: 'border-l-border',
}

/**
 * A ticket's conversation, oldest first (DESIGN §22). Every body is untrusted text, a tracker comment's or an agent's
 * included: it is rendered as React text, which escapes it, never as HTML.
 */
export function Conversation({ messages, waiting }: { messages: Message[]; waiting: number | null }) {
    return (
        <ol className="flex flex-col gap-2 p-3" data-testid="conversation">
            {messages.map((message) => (
                <li
                    key={message.id}
                    data-testid={`message-${message.id}`}
                    data-source={message.source}
                    className={cn('flex flex-col gap-1 rounded-sm border-l-2 py-1.5 pr-2 pl-3', TONE[message.kind])}
                >
                    <Head message={message} waiting={message.id === waiting} />
                    <p className="text-sm break-words whitespace-pre-wrap">{message.body}</p>
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
