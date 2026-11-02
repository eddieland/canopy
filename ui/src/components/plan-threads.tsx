import { MessageSquarePlus, Send, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode, Ref, SubmitEvent } from 'react'

import { Age } from '@/components/age'
import { Disclosure } from '@/components/disclosure'
import { Textarea } from '@/components/input'
import { MarkdownField } from '@/components/markdown-field'
import { Empty } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { SendKeycap } from '@/components/send-keycap'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { usePending } from '@/hooks/use-pending'
import { changeRequest, MAX_COMMENT, MAX_REQUEST } from '@/lib/plan-threads'
import type { PlanThread } from '@/lib/plan-threads'
import { useSendKeys } from '@/lib/send-key'
import { cn } from '@/lib/utils'

// A change request that answers none of the plan's decisions.
const NO_ANSWERS: readonly string[] = []

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
    /** Marks a thread the one open, its passage drawn so, without moving the plan: when its card takes the focus. */
    onOpen: (id: string) => void
    /** Adds a reply to a thread. */
    onReply: (id: string, body: string) => void
    /** Resolves a thread, or reopens it. */
    onResolve: (id: string, resolved: boolean) => void
    /** Deletes a thread and its replies. */
    onDelete: (id: string) => void
    /** Has a thread's comment, or with `replyId` one of its replies, say `body` instead. */
    onEdit: (id: string, body: string, replyId?: string) => void
    /** Puts the cursor back in the plan at a thread's passage, when a form on its card closes or is left. */
    onBack: (id: string) => void
}

/**
 * A plan's comments, as a column beside it: each open thread in the order the plan reads, with the comment being
 * written, if any, in its place among them; then those whose passage is gone, with a chip saying so; then the resolved
 * ones folded under a `Disclosure`. The open threads and the comment being written carry `data-align`, so that
 * `alignComments` (`src/lib/plan-margin.ts`) can set each beside its passage; `listRef` is the list they sit in. A
 * thread is its passage, quoted, the comment and its replies, and its actions; the open one, whose passage the plan
 * shows highlighted, sits on the accent's tint. Every comment is the operator's, but it is journal text all the same,
 * so it is rendered as text with its URLs linked (D113).
 */
export function PlanThreads({
    threads,
    found,
    active,
    draft,
    draftAt,
    hidden,
    listRef,
    editable,
    onDraftChange,
    onDraftSubmit,
    onDraftCancel,
    onDraftLeave,
    onResolveGone,
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
    /** How many of the open threads found in the plan come before the comment being written, in the plan's order. */
    draftAt: number
    /** A thread shown elsewhere, at its passage (`floatUnder`), so not in the list as well. */
    hidden?: string | undefined
    /** The list of comments, for `alignComments`. */
    listRef?: Ref<HTMLDivElement>
    /** Whether the operator can comment, reply, and resolve; without it the threads are read only. */
    editable: boolean
    /** Called with what the comment being written says, as the operator types it. */
    onDraftChange: (body: string) => void
    /** Adds the comment being written. */
    onDraftSubmit: (body: string) => void
    /** Drops the comment being written. */
    onDraftCancel: () => void
    /** Puts the cursor back in the plan, the comment being written left open with its words. */
    onDraftLeave: () => void
    /** Resolves every open thread whose passage is gone from the plan, at once. */
    onResolveGone: () => void
}) {
    const [showResolved, setShowResolved] = useState(false)
    const open = threads.filter((thread) => !thread.resolved)
    const placed = open.filter((thread) => found.has(thread.id))
    const lost = open.filter((thread) => !found.has(thread.id))
    const resolved = threads.filter((thread) => thread.resolved)
    const card = (thread: PlanThread) =>
        thread.id === hidden ? undefined : (
            <ThreadCard
                key={thread.id}
                thread={thread}
                lost={!found.has(thread.id)}
                active={thread.id === active}
                editable={editable}
                {...actions}
            />
        )
    return (
        <div ref={listRef} className="plan-margin flex flex-col">
            {placed.slice(0, draftAt).map((thread) => card(thread))}
            {draft !== undefined && (
                <div data-align="draft" className="border-b bg-accent/14 px-3 py-2.5">
                    <DraftForm
                        draft={draft}
                        onDraftChange={onDraftChange}
                        onDraftSubmit={onDraftSubmit}
                        onDraftCancel={onDraftCancel}
                        onDraftLeave={onDraftLeave}
                    />
                </div>
            )}
            {open.length === 0 && draft === undefined && (
                <Empty>
                    {editable ? 'no open comments yet: select text in the plan, then Comment' : 'no open comments now'}
                </Empty>
            )}
            {placed.slice(draftAt).map((thread) => card(thread))}
            {editable && lost.length > 1 && (
                // A new plan rewrites what it was asked to change, so the comments on it lose their passages
                // together: once read, they are resolved together, rather than one by one.
                <div className="flex items-center justify-between gap-2 border-t px-3 py-1.5">
                    <span className="text-xs text-muted-foreground">{lost.length} on passages gone from the plan</span>
                    <Button variant="ghost" size="xs" className="-my-1 text-muted-foreground" onClick={onResolveGone}>
                        resolve all {lost.length}
                    </Button>
                </div>
            )}
            {lost.map((thread) => card(thread))}
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
 * Asks the planner for a new plan, as M44's Ask for changes does: the open threads, each on its passage, the answers to
 * the plan's decisions, and a note on the whole plan, as one message (`changeRequest`). Disabled with nothing to ask,
 * and over a reply's bound, which it says rather than cut the message. It sits in a plan's foot, in the line of the
 * caller's actions: its form lays out nothing of its own, so the note field and the button take their places in that
 * line, and the note takes a line of its own while it is focused or holds words. How many open comments go with it,
 * then the caller's `note`, take the line under them.
 */
export function AskForChanges({
    threads,
    starts,
    edited,
    asked = false,
    answers = NO_ANSWERS,
    line: said,
    note,
    onAsk,
    onNoteChange,
}: {
    /** The plan's threads. */
    threads: PlanThread[]
    /** Where each found thread's passage starts, for their order. */
    starts: ReadonlyMap<string, number>
    /** Whether the operator edited the plan's text, which the message then says. */
    edited: boolean
    /** Whether they asked already and no planner has read it, so another request is asking again. */
    asked?: boolean
    /** The answers to the plan's open decisions (`decisionAnswers`), a line each, which go with the comments. */
    answers?: readonly string[]
    /** What the caller says of its own actions, after how many comments go with this one, on the line under them. */
    line?: ReactNode
    /** The note on the whole plan, the caller's state, so its own actions, such as Approve, can send it too. */
    note: string
    /** Sends the message. */
    onAsk: (message: string) => void
    /** Called with the note on the whole plan as the operator writes it, and with nothing once it is sent. */
    onNoteChange: (note: string) => void
}) {
    const setNote = onNoteChange
    usePending(note.trim() !== '')
    const message = changeRequest(threads, starts, note, edited, answers)
    const open = threads.filter((thread) => !thread.resolved).length
    const over = message.length > MAX_REQUEST

    function send(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (message && !over) {
            onAsk(message)
            setNote('')
        }
    }

    const comments = `${open} open ${open === 1 ? 'comment' : 'comments'}`
    // Once asked, what Ask again sends, not that the open comments are still to go: some went with the first request.
    const goes = asked
        ? `Ask again sends the ${comments} again.`
        : `${comments} ${open === 1 ? 'goes' : 'go'} with Ask for changes.`
    const told = over
        ? `${message.length - MAX_REQUEST} characters over a reply's bound: resolve or shorten some.`
        : open > 0 && goes

    return (
        // `contents`, so its field and button are items of the caller's line, beside its own actions.
        <form onSubmit={send} aria-label="Ask for changes" className="contents">
            <Textarea
                name="note"
                aria-label="On the whole plan"
                rows={1}
                value={note}
                maxLength={MAX_REQUEST}
                onChange={(event) => setNote(event.target.value)}
                placeholder="A note on the whole plan"
                className={cn(
                    'field-sizing-content max-h-32 min-h-8 min-w-32 flex-1 resize-none py-1',
                    // Empty in the actions' line, one line, its prompt cut to fit rather than grow the line taller.
                    'placeholder-shown:truncate',
                    // Being written, it takes the line under the actions, the whole width of the foot.
                    'focus:order-1 focus:basis-full',
                    note !== '' && 'order-1 basis-full',
                )}
            />
            <Button type="submit" variant="outline" disabled={!message || over}>
                <Send aria-hidden />
                {asked ? 'Ask again' : 'Ask for changes'}
            </Button>
            {(told !== false || said !== undefined) && (
                <p className="order-2 basis-full text-xs text-muted-foreground">
                    {told} {said}
                </p>
            )}
        </form>
    )
}

/** The comment being written: the passage it is on, quoted, and its form. */
export function DraftForm({
    draft,
    onDraftChange,
    onDraftSubmit,
    onDraftCancel,
    onDraftLeave,
}: {
    /** The comment being written. */
    draft: Draft
    /** Called with what it says, as the operator types it. */
    onDraftChange: (body: string) => void
    /** Adds it. */
    onDraftSubmit: (body: string) => void
    /** Drops it. */
    onDraftCancel: () => void
    /** Puts the cursor back in the plan, the comment left open with its words. */
    onDraftLeave: () => void
}) {
    return (
        <>
            <Quote text={draft.quote} />
            <CommentForm
                key={draft.opened}
                label="Comment"
                submit="Comment"
                value={draft.body}
                onValueChange={onDraftChange}
                onSubmit={onDraftSubmit}
                onCancel={onDraftCancel}
                onLeave={onDraftLeave}
            />
        </>
    )
}

// What `ThreadCard` edits when it edits the comment rather than a reply.
const COMMENT = 'comment'

/**
 * A thread's card: its passage quoted, the comment and its replies, and what can be done with it. The open one sits
 * on the accent's tint; `lost` marks one whose passage is gone from the plan.
 */
export function ThreadCard({
    thread,
    lost,
    active,
    editable,
    onActivate,
    onOpen,
    onReply,
    onResolve,
    onDelete,
    onEdit,
    onBack,
}: ThreadActions & {
    /** The thread. */
    thread: PlanThread
    /** Whether its passage is gone from the plan. */
    lost: boolean
    /** Whether it is the thread open. */
    active: boolean
    /** Whether the operator can reply, edit, resolve, and delete. */
    editable: boolean
}) {
    const [replying, setReplying] = useState(false)
    // What is being edited: the comment, or a reply by its id.
    const [editing, setEditing] = useState<string | undefined>(undefined)
    const [deleting, setDeleting] = useState(false)
    // Nothing in the card is open: no reply, edit, or question being answered.
    const idle = editable && editing === undefined && !replying && !deleting
    // An open thread's words can be edited while nothing else in its card is open.
    const startEdit = idle && !thread.resolved
    // Reply shows on the card that is open, as a shared document's does, so the rest stay short and near their
    // passages; on one whose passage is gone too, which cannot be opened from the plan.
    const canReply = idle && !thread.resolved && (active || lost)
    // Keep gives the focus back to Delete, which opened the question, rather than drop it to the page's top.
    const [kept, setKept] = useState(false)
    const deleteAction = useRef<HTMLButtonElement>(null)
    useEffect(() => {
        if (kept) {
            deleteAction.current?.focus()
        }
    }, [kept])

    function open() {
        if (!active && !lost && !thread.resolved) {
            onOpen(thread.id)
        }
    }
    return (
        // A click anywhere on an open thread's card, or Tab into it, opens the thread, as in a shared document. The
        // plan stays where it is, so a card below a narrow plan never pulls the page away from the reply being typed.
        // By the click, not the focus a press gives, for a mouse: an open card moves to its passage, and moved between
        // press and release, the release would miss the button pressed. By the focus for the keyboard, which a click
        // does not show (`:focus-visible`). Either only marks the thread open: no interaction a keyboard lacks.
        // oxlint-disable-next-line no-noninteractive-element-interactions, click-events-have-key-events
        <article
            data-thread={thread.id}
            data-active={active}
            data-align={lost || thread.resolved ? undefined : thread.id}
            aria-label={`Comment on “${thread.anchor.quote}”`}
            tabIndex={-1}
            onClick={open}
            onFocus={(event) => {
                if (event.target.matches(':focus-visible')) {
                    open()
                }
            }}
            className={cn(
                'flex flex-col gap-1.5 border-b px-3 py-2.5 outline-none last:border-b-0',
                active && 'bg-accent/14',
                thread.resolved && 'text-muted-foreground',
            )}
        >
            <div className="flex items-start gap-2">
                <Quote text={thread.anchor.quote} onClick={lost ? undefined : () => onActivate(thread.id)} />
                {idle && (
                    // A row's own actions, in words, as a finding's `dismiss` is: an icon alone would say less, and a
                    // tick reads as accepted rather than resolved.
                    <div className="-my-1 -mr-2 flex shrink-0 items-center">
                        <Button
                            variant="ghost"
                            size="xs"
                            className="text-muted-foreground"
                            onClick={() => onResolve(thread.id, !thread.resolved)}
                        >
                            {thread.resolved ? 'reopen' : 'resolve'}
                        </Button>
                        <Button
                            ref={deleteAction}
                            variant="ghost"
                            size="xs"
                            className="text-muted-foreground"
                            onClick={() => {
                                setKept(false)
                                setDeleting(true)
                            }}
                        >
                            delete
                        </Button>
                    </div>
                )}
            </div>
            {(lost || thread.resolved) && (
                // On a line of their own, so the quote keeps the width the actions leave it.
                <div className="flex gap-1.5">
                    {lost && <Chip>passage gone</Chip>}
                    {thread.resolved && <Chip>resolved</Chip>}
                </div>
            )}
            {editing === COMMENT ? (
                <CommentForm
                    label="Edit comment"
                    submit="Save"
                    initial={thread.body}
                    onSubmit={(body) => {
                        onEdit(thread.id, body)
                        setEditing(undefined)
                    }}
                    onCancel={() => {
                        setEditing(undefined)
                        onBack(thread.id)
                    }}
                    onLeave={() => onBack(thread.id)}
                />
            ) : (
                <Said
                    body={thread.body}
                    at={thread.at}
                    what="comment"
                    onEdit={startEdit ? () => setEditing(COMMENT) : undefined}
                />
            )}
            {thread.replies.map((reply) => (
                <div key={reply.id} className="ml-3 border-l pl-2">
                    {editing === reply.id ? (
                        <CommentForm
                            label="Edit reply"
                            submit="Save"
                            initial={reply.body}
                            onSubmit={(body) => {
                                onEdit(thread.id, body, reply.id)
                                setEditing(undefined)
                            }}
                            onCancel={() => {
                                setEditing(undefined)
                                onBack(thread.id)
                            }}
                            onLeave={() => onBack(thread.id)}
                        />
                    ) : (
                        <Said
                            body={reply.body}
                            at={reply.at}
                            what="reply"
                            onEdit={startEdit ? () => setEditing(reply.id) : undefined}
                        />
                    )}
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
                    onCancel={() => {
                        setReplying(false)
                        onBack(thread.id)
                    }}
                    onLeave={() => onBack(thread.id)}
                />
            )}
            {editable && deleting && (
                <ConfirmDelete
                    replies={thread.replies.length}
                    onDelete={() => onDelete(thread.id)}
                    onKeep={() => {
                        setDeleting(false)
                        setKept(true)
                    }}
                />
            )}
            {canReply && (
                <div className="-ml-2">
                    <Button
                        variant="ghost"
                        size="xs"
                        className="text-muted-foreground"
                        onClick={() => setReplying(true)}
                    >
                        reply
                    </Button>
                </div>
            )}
        </article>
    )
}

// Deleting a thread asks first, in its place, as a shared document does, since nothing brings a thread back: Delete or
// Keep. The focus goes to Keep, the choice that loses nothing, and Escape keeps it too.
function ConfirmDelete({ replies, onDelete, onKeep }: { replies: number; onDelete: () => void; onKeep: () => void }) {
    const keep = useRef<HTMLButtonElement>(null)
    useEffect(() => {
        keep.current?.focus()
    }, [])
    const what = replies > 0 ? 'this comment and its replies' : 'this comment'
    function onKey(event: KeyboardEvent<HTMLButtonElement>) {
        if (event.key === 'Escape') {
            event.preventDefault()
            onKeep()
        }
    }
    return (
        <fieldset className="flex flex-wrap items-center justify-between gap-2">
            <legend className="float-left text-xs text-muted-foreground">Delete {what}?</legend>
            <div className="flex items-center gap-1">
                <Button ref={keep} type="button" variant="ghost" size="xs" onClick={onKeep} onKeyDown={onKey}>
                    Keep
                </Button>
                <Button type="button" variant="destructive" size="xs" onClick={onDelete} onKeyDown={onKey}>
                    <Trash2 aria-hidden />
                    Delete
                </Button>
            </div>
        </fieldset>
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

// What a comment or a reply says, and when; with `onEdit`, its own `edit` beside its age, so the card's actions stay on
// one line.
function Said({
    body,
    at,
    what,
    onEdit,
}: {
    body: string
    at: string
    what: 'comment' | 'reply'
    onEdit?: (() => void) | undefined
}) {
    return (
        <div className="flex flex-col gap-0.5">
            <RichText text={body} />
            <div className="flex items-center gap-1">
                <Age at={at} variant="ago" className="text-2xs" />
                {onEdit !== undefined && (
                    // In line with the age, no taller than its line.
                    <Button
                        variant="ghost"
                        size="xs"
                        className="-my-1 text-muted-foreground"
                        aria-label={`Edit ${what}`}
                        onClick={onEdit}
                    >
                        edit
                    </Button>
                )}
            </div>
        </div>
    )
}

// A comment or a reply being written. It sends on the key Settings names, as a reply to a ticket does. Escape drops it
// while it holds nothing new; with words of the operator's own in it, Escape leaves it open, words and all, and goes
// back to the plan (`onLeave`), so one key never loses what was typed: Cancel drops it. It keeps its own words, or the
// caller's through `value` and `onValueChange`, which outlive the form.
function CommentForm({
    label,
    submit,
    initial = '',
    value,
    onValueChange,
    onSubmit,
    onCancel,
    onLeave,
}: {
    label: string
    submit: string
    initial?: string
    value?: string
    onValueChange?: (body: string) => void
    onSubmit: (body: string) => void
    onCancel: () => void
    onLeave: () => void
}) {
    const sendKeys = useSendKeys()
    const field = useRef<HTMLTextAreaElement>(null)
    const [own, setOwn] = useState(initial)
    const body = value ?? own
    const setBody = onValueChange ?? setOwn
    usePending(body.trim() !== '' && body !== initial)

    // The form opens on a click that asks for it, so the field takes the focus as it opens, once, after any words it
    // holds already; the page scrolls to it a frame on, once the comments are placed beside the plan. Only then: a
    // render as the operator types leaves the cursor and the page where they are.
    useEffect(() => {
        const element = field.current
        if (element === null) {
            return
        }
        element.focus({ preventScroll: true })
        element.setSelectionRange(element.value.length, element.value.length)
        const frame = requestAnimationFrame(() => element.scrollIntoView({ block: 'nearest' }))
        return () => cancelAnimationFrame(frame)
    }, [])

    function send(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (body.trim()) {
            onSubmit(body.trim())
        }
    }

    function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
        if (event.key === 'Escape') {
            event.preventDefault()
            if (body.trim() === '' || body === initial) {
                onCancel()
            } else {
                onLeave()
            }
            return
        }
        sendKeys.onKeyDown(event)
    }

    return (
        <form onSubmit={send} aria-label={label} className="mt-1.5 flex flex-col gap-1.5">
            <MarkdownField
                aria-label={label}
                value={body}
                maxLength={MAX_COMMENT}
                onValueChange={setBody}
                onKeyDown={onKey}
                ref={field}
            />
            <div className="flex items-center justify-end gap-1">
                <Button type="button" variant="ghost" size="xs" onClick={onCancel}>
                    Cancel
                </Button>
                <Button type="submit" size="xs" disabled={!body.trim()} aria-keyshortcuts={sendKeys.shortcut}>
                    <MessageSquarePlus aria-hidden />
                    {submit}
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
            </div>
        </form>
    )
}
