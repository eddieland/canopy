import { Check, MessageSquarePlus, Reply, RotateCcw, Send, Trash2 } from 'lucide-react'
import { useId, useState } from 'react'
import type { KeyboardEvent, SubmitEvent } from 'react'

import { Age } from '@/components/age'
import { Textarea } from '@/components/input'
import { LinkedText } from '@/components/linked-text'
import { Empty } from '@/components/panel'
import { Chip } from '@/components/status'
import { Disclosure } from '@/components/disclosure'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { changeRequest, MAX_COMMENT, MAX_REQUEST } from '@/lib/plan-threads'
import type { PlanThread } from '@/lib/plan-threads'
import { sends, useSendKey } from '@/lib/send-key'
import { cn } from '@/lib/utils'

/** A comment being written: the passage it is on and what it says so far. */
export interface Draft {
    /** The passage, quoted. */
    quote: string
    /** What the comment says so far. */
    body: string
    /** Counts each time the operator asks to comment, so the form opens again, and takes the focus, on each. */
    opened: number
}

/** What the operator can do with a plan's threads, from its comments column. */
export interface ThreadActions {
    /** Shows a thread's passage in the plan and marks it the one open. */
    onActivate: (id: string) => void
    /** Adds a reply to a thread. */
    onReply: (id: string, body: string) => void
    /** Resolves a thread, or reopens it. */
    onResolve: (id: string, resolved: boolean) => void
    /** Deletes a thread and its replies. */
    onDelete: (id: string) => void
}

/**
 * A plan's comments, as a column beside it: the comment being written, if any, then each open thread in the order the
 * plan reads, those whose passage is gone last with a chip saying so, then the resolved ones folded under a
 * `Disclosure`. A thread is its passage, quoted, the comment and its replies, and its actions; the open one, whose
 * passage the plan shows highlighted, sits on the accent's tint. Every comment is the operator's, but it is journal
 * text all the same, so it is rendered as text with its URLs linked (D113).
 */
export function PlanThreads({
    threads,
    found,
    active,
    draft,
    editable,
    onDraftChange,
    onDraftSubmit,
    onDraftCancel,
    ...actions
}: ThreadActions & {
    /** The threads, in the plan's order. */
    threads: PlanThread[]
    /** The ids of the threads whose passage is in the plan. */
    found: ReadonlySet<string>
    /** The thread open, if any. */
    active: string | undefined
    /** The comment being written, if one is. */
    draft: Draft | undefined
    /** Whether the operator can comment, reply, and resolve; without it the threads are read only. */
    editable: boolean
    /** Called with what the comment being written says, as the operator types it. */
    onDraftChange: (body: string) => void
    /** Adds the comment being written. */
    onDraftSubmit: (body: string) => void
    /** Drops the comment being written. */
    onDraftCancel: () => void
}) {
    const [showResolved, setShowResolved] = useState(false)
    const open = threads.filter((thread) => !thread.resolved)
    const resolved = threads.filter((thread) => thread.resolved)
    return (
        <div className="flex flex-col">
            {draft !== undefined && (
                <div className="border-b bg-accent/14 px-3 py-2.5">
                    <Quote text={draft.quote} />
                    <CommentForm
                        key={draft.opened}
                        label="Comment"
                        submit="Comment"
                        value={draft.body}
                        onValueChange={onDraftChange}
                        onSubmit={onDraftSubmit}
                        onCancel={onDraftCancel}
                    />
                </div>
            )}
            {open.length === 0 && draft === undefined && (
                <Empty>
                    {editable ? 'no open comments yet: select text in the plan, then Comment' : 'no open comments now'}
                </Empty>
            )}
            {open.map((thread) => (
                <ThreadCard
                    key={thread.id}
                    thread={thread}
                    lost={!found.has(thread.id)}
                    active={thread.id === active}
                    editable={editable}
                    {...actions}
                />
            ))}
            {resolved.length > 0 && (
                <Collapsible open={showResolved} onOpenChange={setShowResolved} className="border-t px-1 py-1">
                    <Disclosure open={showResolved} what={`${resolved.length} resolved`} />
                    <CollapsibleContent className="-mx-1 mt-1 border-t">
                        {resolved.map((thread) => (
                            <ThreadCard
                                key={thread.id}
                                thread={thread}
                                lost={!found.has(thread.id)}
                                active={false}
                                editable={editable}
                                {...actions}
                            />
                        ))}
                    </CollapsibleContent>
                </Collapsible>
            )}
        </div>
    )
}

/**
 * Asks the planner for a new plan, as M44's Ask for changes does: the open threads, each on its passage, and a note on
 * the whole plan, as one message (`changeRequest`). Disabled with nothing to ask, and over a reply's bound, which it
 * says rather than cut the message.
 */
export function AskForChanges({
    threads,
    starts,
    onAsk,
}: {
    /** The plan's threads. */
    threads: PlanThread[]
    /** Where each found thread's passage starts, for their order. */
    starts: ReadonlyMap<string, number>
    /** Sends the message. */
    onAsk: (message: string) => void
}) {
    const id = useId()
    const [note, setNote] = useState('')
    const message = changeRequest(threads, starts, note)
    const open = threads.filter((thread) => !thread.resolved).length
    const over = message.length > MAX_REQUEST

    function send(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (message && !over) {
            onAsk(message)
            setNote('')
        }
    }

    return (
        <form onSubmit={send} aria-label="Ask for changes" className="flex flex-col gap-2 border-t p-3">
            <div className="flex flex-col gap-1.5">
                <label htmlFor={id} className="panel-label">
                    On the whole plan
                </label>
                <Textarea
                    id={id}
                    name="note"
                    value={note}
                    maxLength={MAX_REQUEST}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="Optional. The planner reads it with every open comment and the passage it is on."
                    className="min-h-16"
                />
            </div>
            <div className="flex items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground">
                    {over
                        ? `${message.length - MAX_REQUEST} characters over a reply's bound: resolve or shorten some`
                        : `${open} open ${open === 1 ? 'comment goes' : 'comments go'} with it`}
                </span>
                <Button type="submit" disabled={!message || over}>
                    <Send aria-hidden />
                    Ask for changes
                </Button>
            </div>
        </form>
    )
}

function ThreadCard({
    thread,
    lost,
    active,
    editable,
    onActivate,
    onReply,
    onResolve,
    onDelete,
}: ThreadActions & { thread: PlanThread; lost: boolean; active: boolean; editable: boolean }) {
    const [replying, setReplying] = useState(false)
    return (
        <article
            data-thread={thread.id}
            data-active={active}
            aria-label={`Comment on “${thread.anchor.quote}”`}
            className={cn(
                'flex flex-col gap-1.5 border-b px-3 py-2.5 last:border-b-0',
                active && 'bg-accent/14',
                thread.resolved && 'text-muted-foreground',
            )}
        >
            <div className="flex items-start gap-2">
                <Quote text={thread.anchor.quote} onClick={lost ? undefined : () => onActivate(thread.id)} />
                {lost && <Chip className="mt-0.5">passage gone</Chip>}
                {thread.resolved && <Chip className="mt-0.5">resolved</Chip>}
            </div>
            <Said body={thread.body} at={thread.at} />
            {thread.replies.map((reply) => (
                <div key={reply.id} className="ml-3 border-l pl-2">
                    <Said body={reply.body} at={reply.at} />
                </div>
            ))}
            {replying && (
                <CommentForm
                    label="Reply"
                    submit="Reply"
                    onSubmit={(body) => {
                        onReply(thread.id, body)
                        setReplying(false)
                    }}
                    onCancel={() => setReplying(false)}
                />
            )}
            {editable && !replying && (
                <div className="-ml-2 flex flex-wrap items-center gap-0.5">
                    {!thread.resolved && (
                        <Button variant="ghost" size="xs" onClick={() => setReplying(true)}>
                            <Reply aria-hidden />
                            Reply
                        </Button>
                    )}
                    <Button variant="ghost" size="xs" onClick={() => onResolve(thread.id, !thread.resolved)}>
                        {thread.resolved ? <RotateCcw aria-hidden /> : <Check aria-hidden />}
                        {thread.resolved ? 'Reopen' : 'Resolve'}
                    </Button>
                    <Button variant="ghost" size="xs" onClick={() => onDelete(thread.id)}>
                        <Trash2 aria-hidden />
                        Delete
                    </Button>
                </div>
            )}
        </article>
    )
}

// A passage quoted, two lines at most, the whole on hover; a button that shows it in the plan when it is there.
function Quote({ text, onClick }: { text: string; onClick?: (() => void) | undefined }) {
    const css = cn(
        'line-clamp-2 min-w-0 flex-1 border-l-2 border-accent/60 pl-2 text-left text-xs text-muted-foreground',
        'break-words',
    )
    if (onClick === undefined) {
        return (
            <span title={text} className={css}>
                {text}
            </span>
        )
    }
    return (
        <button
            type="button"
            title={text}
            onClick={onClick}
            className={cn(
                css,
                'rounded-xs outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50',
            )}
        >
            {text}
        </button>
    )
}

function Said({ body, at }: { body: string; at: string }) {
    return (
        <div className="flex flex-col gap-0.5">
            <p className="text-sm break-words whitespace-pre-wrap">
                <LinkedText text={body} />
            </p>
            <Age at={at} variant="ago" className="text-2xs" />
        </div>
    )
}

// A comment or a reply being written. It sends on the key Settings names, as a reply to a ticket does, and Escape
// drops it. It keeps its own words, or the caller's through `value` and `onValueChange`, which outlive the form.
function CommentForm({
    label,
    submit,
    value,
    onValueChange,
    onSubmit,
    onCancel,
}: {
    label: string
    submit: string
    value?: string
    onValueChange?: (body: string) => void
    onSubmit: (body: string) => void
    onCancel: () => void
}) {
    const sendKey = useSendKey()
    const [own, setOwn] = useState('')
    const body = value ?? own
    const setBody = onValueChange ?? setOwn

    function send(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (body.trim()) {
            onSubmit(body.trim())
        }
    }

    function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
        if (event.key === 'Escape') {
            event.preventDefault()
            onCancel()
            return
        }
        const { key, shiftKey, ctrlKey, metaKey } = event
        if (sends(sendKey, { key, shiftKey, ctrlKey, metaKey, isComposing: event.nativeEvent.isComposing })) {
            event.preventDefault()
            event.currentTarget.form?.requestSubmit()
        }
    }

    return (
        <form onSubmit={send} aria-label={label} className="mt-1.5 flex flex-col gap-1.5">
            <Textarea
                aria-label={label}
                value={body}
                maxLength={MAX_COMMENT}
                onChange={(event) => setBody(event.target.value)}
                onKeyDown={onKey}
                // The form opens on a click that asks for it, so the field takes the focus at once, after any words it
                // holds already.
                ref={(field) => {
                    field?.focus()
                    field?.setSelectionRange(field.value.length, field.value.length)
                }}
                className="min-h-16"
            />
            <div className="flex items-center justify-end gap-1">
                <Button type="button" variant="ghost" size="xs" onClick={onCancel}>
                    Cancel
                </Button>
                <Button type="submit" size="xs" disabled={!body.trim()}>
                    <MessageSquarePlus aria-hidden />
                    {submit}
                </Button>
            </div>
        </form>
    )
}
