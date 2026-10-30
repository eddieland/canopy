import { useQuery } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useState } from 'react'
import type { ComponentProps, ReactNode } from 'react'

import { tickQuery } from '@/api/queries'
import type { Message } from '@/api/types'
import { Age } from '@/components/age'
import { RichText } from '@/components/rich-text'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { TaskRunLink } from '@/components/task-link'
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
 * Every body is untrusted text, a tracker comment's or an agent's included: `RichText` lays out the few Markdown forms
 * agents write, its line breaks kept, as React text, which escapes it, never as HTML. Bubbles pop in from their
 * own side, one after another, and a new one when it arrives. The operator's own messages that no `ok` tick has read
 * yet say so: the loop acts on them, and the attention list catches up, at the next tick. Once one has, they say
 * `seen`, so the operator knows they landed. A chore's notes say instead which its next run reads (`pending`), and say
 * nothing once read. A task's conversation is headed by its `instruction`, the operator's text, at its oldest end (the
 * last, `newestFirst`), and names each message's run within the `task`; no tick reads a task's conversation, only its
 * next run does, so its replies carry no tick's chip.
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
            {messages.map((message, index) => (
                <Bubble
                    key={message.id}
                    grouped={continues(messages[index - 1], message)}
                    id={messageAnchor(message.id)}
                    data-testid={messageAnchor(message.id)}
                    data-source={message.source}
                    operator={message.source === 'operator'}
                    tone={message.id === waiting ? OPEN_QUESTION : TONE[message.kind]}
                    body={message.body}
                    head={
                        <Head
                            message={message}
                            grouped={continues(messages[index - 1], message)}
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
                <HeadLine name={instruction.ref} at={instruction.at} operator>
                    <Who>you</Who>
                    <span>instruction via {instruction.channel}</span>
                </HeadLine>
            }
        />
    )
}

// How close in time a message follows the one before for the two to read as one turn.
const TURN_MS = 5 * 60 * 1000

/**
 * Whether a message carries on the turn before it, `previous`: the same speaker saying the same kind of thing in the
 * same run and channel, within a few minutes. Its head then drops who and what, as a chat stacks one person's lines.
 * Never a message that answers another, whose head says which, nor a tracker comment: two may be two coworkers'.
 */
function continues(previous: Message | undefined, message: Message): boolean {
    return (
        previous !== undefined &&
        message.source !== 'tracker' &&
        previous.source === message.source &&
        previous.kind === message.kind &&
        previous.channel === message.channel &&
        message.answers === null &&
        previous.run_id === message.run_id &&
        previous.task_run_id === message.task_run_id &&
        Math.abs(Date.parse(message.at) - Date.parse(previous.at)) <= TURN_MS
    )
}

/**
 * One message: its head line over its bubble, which is as wide as its words, up to a measure that leaves the other
 * side a gutter at any panel's width, so the operator's own stay on the right however narrow the panel. A message
 * that carries on the turn before it (`grouped`) sits closer under it.
 */
function Bubble({
    operator,
    tone,
    head,
    body,
    grouped = false,
    ...props
}: { operator: boolean; tone: string; head: ReactNode; body: string; grouped?: boolean } & ComponentProps<'li'>) {
    return (
        <li
            {...props}
            className={cn(
                'flex max-w-[min(42rem,85%)] flex-col gap-1 [--enter:pop]',
                operator ? 'origin-top-right items-end self-end' : 'origin-top-left items-start self-start',
                grouped && '-mt-1.5',
            )}
        >
            {head}
            <div
                className={cn(
                    'w-fit max-w-full rounded-md px-3 py-2',
                    operator ? 'rounded-tr-xs' : 'rounded-tl-xs',
                    tone,
                )}
            >
                <RichText text={body} pullRequests raised className="leading-6" />
            </div>
        </li>
    )
}

/**
 * A bubble's head line: who and what, led by who, then its chips; its name (`#4`) and age a readout at the outer edge,
 * mirrored on the operator's side. The name comes first in the markup, so a screen reader and the page's text read it
 * first, as the message is referred to by it.
 */
function HeadLine({
    name,
    at,
    operator,
    children,
}: {
    name: string
    at: string
    operator: boolean
    children: ReactNode
}) {
    const clock = useClock()
    return (
        <div
            className={cn(
                'flex w-full flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-muted-foreground',
                operator && 'justify-end',
            )}
        >
            <span className={cn('flex items-center gap-1.5', operator ? 'order-first mr-auto' : 'order-last ml-auto')}>
                <span className="readout">{name}</span>
                <span aria-hidden>·</span>
                <Age at={at} variant="ago" />
                <span className="sr-only">{localTime(at, clock)}</span>
            </span>
            {children}
        </div>
    )
}

/** Who wrote a message: the head line's anchor, in the interface's face rather than the data's. */
function Who({ children }: { children: ReactNode }) {
    return <span className="font-sans font-medium text-foreground">{children}</span>
}

function Head({
    message,
    grouped,
    task,
    waiting,
    unread,
    seen,
}: {
    message: Message
    grouped: boolean
    task: number | undefined
    waiting: boolean
    unread: Pending | null
    seen: boolean
}) {
    const clock = useClock()
    const comment = message.comment
    const cut = comment?.truncated === true ? ', truncated' : ''
    return (
        <HeadLine name={messageRef(message.id)} at={message.at} operator={message.source === 'operator'}>
            {grouped ? null : comment ? (
                <>
                    <Who>{comment.author}</Who>
                    <span title={`comment ${comment.id}, written ${localTime(comment.at, clock)}${cut}`}>
                        on the tracker{cut}
                        {/* The tip is the pointer's; a screen reader is told the same. */}
                        <span className="sr-only">
                            , comment {comment.id}, written {localTime(comment.at, clock)}
                        </span>
                    </span>
                </>
            ) : (
                <>
                    <Who>{WHO[message.source]}</Who>
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
                </>
            )}
            {comment && <Chip>data, authorizes nothing</Chip>}
            {waiting && <Chip tone="blocked">waiting on you</Chip>}
            <Receipt unread={unread} seen={seen} />
        </HeadLine>
    )
}

/**
 * Whether a tick has read one of the operator's messages: `waiting for the next tick` until one has, then `seen` with a
 * check, in the accent, the operator's side. A message that was unread while the page showed it pops its `seen` in
 * once, as the tick reads it: a small reward for a real change, never for a page that opens on it already read.
 */
function Receipt({ unread, seen }: { unread: Pending | null; seen: boolean }) {
    const [waited, setWaited] = useState(unread !== null)
    if (unread !== null && !waited) {
        setWaited(true)
    }
    if (unread) {
        return (
            <span title={unread.title}>
                <Chip tone="running">{unread.label}</Chip>
            </span>
        )
    }
    if (!seen) {
        return null
    }
    return (
        <span title={SEEN} className={cn(waited && 'animate-receipt')}>
            <Chip className="border-accent/40 text-accent">
                <Check aria-hidden className="size-3" />
                seen
            </Chip>
        </span>
    )
}
