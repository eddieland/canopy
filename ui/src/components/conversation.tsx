import { useQuery } from '@tanstack/react-query'
import type { ComponentProps, ReactNode } from 'react'

import { tickQuery } from '@/api/queries'
import type { Message } from '@/api/types'
import { Age } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { TaskRunLink } from '@/components/task-link'
import { Timestamp } from '@/components/timestamp'
import { awaitsTick } from '@/lib/acknowledged'
import { messageAnchor, messageRef } from '@/lib/refs'
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
// tint, a worker's on the raised surface, a tracker comment quoted, a hairline on the panel's own surface, since it is
// data from outside the loop, and canopy's note on what a tick did as a muted dashed outline, since it is about the
// loop rather than the work. A question is on the raised surface once answered; the one still open is `OPEN_QUESTION`.
const TONE: Record<Message['kind'], string> = {
    report: 'bg-surface-raised',
    question: 'bg-surface-raised',
    reply: 'bg-accent/18',
    comment: 'border bg-surface',
    note: 'border border-dashed text-muted-foreground',
}

// The question still waiting on the operator, in the tint and hairline of what waits on a person: the one amber bubble.
const OPEN_QUESTION = 'border border-status-blocked/40 bg-status-blocked/8'

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
                <Bubble
                    key={message.id}
                    id={messageAnchor(message.id)}
                    data-testid={messageAnchor(message.id)}
                    data-source={message.source}
                    operator={message.source === 'operator'}
                    tone={message.id === waiting ? OPEN_QUESTION : TONE[message.kind]}
                    body={message.body}
                    head={
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
                    }
                />
            ))}
            {newestFirst && lead}
        </ol>
    )
}

/** A task's instruction, as the operator's own words are drawn: on their side, in the accent's tint. */
function InstructionBubble({ instruction }: { instruction: Instruction }) {
    return (
        <Bubble
            data-testid="instruction"
            data-source="operator"
            operator
            tone={TONE.reply}
            body={instruction.body}
            head={
                <HeadLine at={instruction.at} operator>
                    <span className="readout">{instruction.ref}</span>
                    <span className="text-foreground">you</span>
                    <span>instruction via {instruction.channel}</span>
                </HeadLine>
            }
        />
    )
}

/**
 * One message: its head line over its bubble, which is as wide as its words, up to a measure that leaves the other
 * side a gutter at any panel's width, so the operator's own stay on the right however narrow the panel.
 */
function Bubble({
    operator,
    tone,
    head,
    body,
    ...props
}: { operator: boolean; tone: string; head: ReactNode; body: string } & ComponentProps<'li'>) {
    return (
        <li
            {...props}
            className={cn(
                'flex max-w-[min(42rem,85%)] flex-col gap-1 [--enter:pop]',
                operator ? 'origin-top-right items-end self-end' : 'origin-top-left items-start self-start',
            )}
        >
            {head}
            <p
                className={cn(
                    'w-fit max-w-full rounded-md px-3 py-2 text-sm break-words whitespace-pre-wrap',
                    operator ? 'rounded-tr-xs' : 'rounded-tl-xs',
                    tone,
                )}
            >
                <LinkedText text={body} pullRequests />
            </p>
        </li>
    )
}

/** A bubble's head line: what it says, then its age at the outer edge, mirrored on the operator's side. */
function HeadLine({ at, operator, children }: { at: string; operator: boolean; children: ReactNode }) {
    const clock = useClock()
    return (
        <div
            className={cn(
                'flex w-full flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-muted-foreground',
                operator && 'justify-end',
            )}
        >
            {children}
            <Age at={at} variant="ago" className={operator ? 'order-first mr-auto' : 'ml-auto'} />
            <span className="sr-only">{localTime(at, clock)}</span>
        </div>
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
    const comment = message.comment
    return (
        <HeadLine at={message.at} operator={message.source === 'operator'}>
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
        </HeadLine>
    )
}
