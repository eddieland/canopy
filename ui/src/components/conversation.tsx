import { useQuery } from '@tanstack/react-query'

import { tickQuery } from '@/api/queries'
import type { Message } from '@/api/types'
import { Age } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { TaskRunLink } from '@/components/task-link'
import { Timestamp } from '@/components/timestamp'
import { awaitsTick } from '@/lib/acknowledged'
import { messageRef } from '@/lib/refs'
import { useClock } from '@/lib/clock'
import { localTime } from '@/lib/time'
import { cn } from '@/lib/utils'

const WHO: Record<Message['source'], string> = {
    worker: 'worker',
    operator: 'you',
    tracker: 'tracker',
    canopy: 'canopy',
}

// Written out so Tailwind finds them. Each message is a bubble: the operator's own words on the right in the accent's
// tint, a question in the tint of what waits on a person, canopy's note on what a tick did as a muted outline, since
// it is about the loop rather than the work, anything else on the raised surface.
const TONE: Record<Message['kind'], string> = {
    report: 'bg-surface-raised',
    question: 'bg-status-blocked/12',
    reply: 'bg-accent/12',
    comment: 'bg-surface-raised',
    note: 'border border-dashed text-muted-foreground',
}

const UNREAD = 'No tick has read it yet. The loop acts on it, and the attention list catches up, at the next tick.'
const SEEN = 'A tick has read it: the loop is acting on it.'

/** Which of the operator's messages nothing has read yet, and what the chip on each says and explains. */
export interface Pending {
    /** The chip's text. */
    label: string
    /** The chip's tooltip: what the state means for the message. */
    title: string
    /** Whether a message is in this state. */
    test: (message: Message) => boolean
}

/** The operator's own words that started a task, which head its conversation as its instruction (DESIGN §36). */
export interface Instruction {
    /** What it is named by: the task's reference, `task:4`. */
    ref: string
    /** When the operator submitted it. */
    at: string
    /** The operator's text, line breaks kept. */
    body: string
    /** Where they submitted it: cli or web. */
    channel: string
}

/**
 * A ticket's conversation, a task's, or a chore's notes, in the order given: oldest first unless flipped (DESIGN §22).
 * Every body is untrusted text, a tracker comment's or an agent's included: it is rendered as React text, which escapes
 * it, never as HTML. Bubbles pop in from their own side, one after another, and a new one when it arrives. The
 * operator's own messages that no `ok` tick has read yet say so: the loop acts on them, and the attention list catches
 * up, at the next tick. Once one has, they say `seen`, so the operator knows they landed. A chore's notes say instead
 * which its next run reads (`pending`), and say nothing once read. A task's conversation is headed by its
 * `instruction`, the operator's text, at its oldest end (the last, `newestFirst`), and names each message's run within
 * the `task`; no tick reads a task's conversation, only its next run does, so its replies carry no tick's chip.
 */
export function Conversation({
    messages,
    waiting = null,
    pending,
    task,
    instruction,
    newestFirst = false,
}: {
    messages: Message[]
    waiting?: number | null
    pending?: Pending
    task?: number
    instruction?: Instruction
    newestFirst?: boolean
}) {
    const acknowledged = useQuery(tickQuery).data?.acknowledged
    const ticked = task === undefined
    const unread: Pending = pending ?? {
        label: 'waiting for the next tick',
        title: UNREAD,
        test: (message) => ticked && acknowledged !== undefined && awaitsTick(message, acknowledged),
    }
    const lead = instruction && <InstructionBubble instruction={instruction} />
    return (
        <ol className="stagger flex flex-col gap-3 p-3" data-testid="conversation">
            {!newestFirst && lead}
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
                        task={task}
                        waiting={message.id === waiting}
                        unread={unread.test(message) ? unread : null}
                        seen={
                            ticked &&
                            pending === undefined &&
                            message.source === 'operator' &&
                            acknowledged !== undefined &&
                            !awaitsTick(message, acknowledged)
                        }
                    />
                    <p
                        className={cn(
                            'rounded-md px-3 py-2 text-sm break-words whitespace-pre-wrap',
                            message.source === 'operator' ? 'rounded-tr-xs' : 'rounded-tl-xs',
                            TONE[message.kind],
                        )}
                    >
                        <LinkedText text={message.body} pullRequests />
                    </p>
                </li>
            ))}
            {newestFirst && lead}
        </ol>
    )
}

/** A task's instruction, as the operator's own words are drawn: on their side, in the accent's tint. */
function InstructionBubble({ instruction }: { instruction: Instruction }) {
    const clock = useClock()
    return (
        <li
            data-testid="instruction"
            data-source="operator"
            className="flex w-full max-w-2xl origin-top-right flex-col gap-1 self-end [--enter:pop]"
        >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-muted-foreground">
                <span className="readout">{instruction.ref}</span>
                <span className="text-foreground">you</span>
                <span>instruction via {instruction.channel}</span>
                <Age at={instruction.at} variant="ago" className="ml-auto" />
                <span className="sr-only">{localTime(instruction.at, clock)}</span>
            </div>
            <p className="rounded-md rounded-tr-xs bg-accent/12 px-3 py-2 text-sm break-words whitespace-pre-wrap">
                <LinkedText text={instruction.body} pullRequests />
            </p>
        </li>
    )
}

function Head({
    message,
    task,
    waiting,
    unread,
    seen,
}: {
    message: Message
    task: number | undefined
    waiting: boolean
    unread: Pending | null
    seen: boolean
}) {
    const clock = useClock()
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
                    {task !== undefined && message.task_run_id !== null && (
                        <>
                            {' ('}
                            <TaskRunLink task={task} run={message.task_run_id} />)
                        </>
                    )}
                    {message.answers === null ? '' : ` answering ${messageRef(message.answers)}`}
                    {message.source === 'operator' ? ` via ${message.channel}` : ''}
                </span>
            )}
            {comment && <Chip>data, authorizes nothing</Chip>}
            {waiting && <Chip tone="blocked">waiting on you</Chip>}
            {unread && (
                <span title={unread.title}>
                    <Chip tone="running">{unread.label}</Chip>
                </span>
            )}
            {seen && (
                <span title={SEEN}>
                    <Chip>seen</Chip>
                </span>
            )}
            <Age at={message.at} variant="ago" className="ml-auto" />
            <span className="sr-only">{localTime(message.at, clock)}</span>
        </div>
    )
}
