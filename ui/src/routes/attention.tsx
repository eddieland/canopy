import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ChevronLeft, FileText, GitPullRequest, MessageSquareReply, Sprout } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import type { AnswerTarget } from '@/api/mutations'
import {
    attentionQuery,
    choreQuery,
    pullRequestQuery,
    reviewQuery,
    runQuery,
    taskQuery,
    tasksQuery,
    ticketPlansQuery,
    ticketQuery,
    ticketsQuery,
} from '@/api/queries'
import type { AttentionItem, Draft, Run, RunCard, TicketSummary, Unit, WaitingFeedbackPlan } from '@/api/types'
import { Age } from '@/components/age'
import { EmptyAttention } from '@/components/all-clear'
import { ChoreFindingText } from '@/components/chore-finding'
import { ChoreLink } from '@/components/chore-link'
import { ChoreNotes } from '@/components/chore-notes'
import { Code } from '@/components/code'
import { Copyable } from '@/components/copy-button'
import { Counters } from '@/components/counters'
import { useDismissFinding } from '@/components/dismiss-finding'
import { FeedbackPlanWaits } from '@/components/feedback-plan-card'
import { GrantLimits } from '@/components/grant-limits'
import { Leaf } from '@/components/leaf'
import { LessonsDue, LessonsWrong, ProposalsWaiting } from '@/components/memory-attention'
import { ModelAttention } from '@/components/model-attention'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PlanCard } from '@/components/plan-card'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReviewLink } from '@/components/review-link'
import { InlineCode } from '@/components/rich-text'
import { RunLink } from '@/components/run-link'
import { ProgressQuestion } from '@/components/run-progress'
import { RunsTable } from '@/components/runs-table'
import { Chip } from '@/components/status'
import { TaskLink } from '@/components/task-link'
import { TicketAnswer, TicketVerbs } from '@/components/ticket-answer'
import { TicketDrafts } from '@/components/ticket-drafts'
import { TicketLink } from '@/components/ticket-link'
import { LinkOutButton } from '@/components/ticket-links'
import { TicketTitle } from '@/components/ticket-title'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/hooks/use-toast'
import { answered } from '@/lib/acknowledged'
import {
    ask,
    bySeverity,
    commandOf,
    feedbackPlanOf,
    modelRefused,
    nextWaiting,
    pullRequestOf,
    reviewOf,
    severity,
    shownDetail,
} from '@/lib/attention'
import type { Ask, Severity } from '@/lib/attention'
import { settled, withLeaving } from '@/lib/leaving'
import type { Listed } from '@/lib/leaving'
import { onGitHub } from '@/lib/links'
import { reasonMeaning } from '@/lib/meanings'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { reviewRef, taskRef } from '@/lib/refs'
import { taskTitle } from '@/lib/tasks'
import type { Tone } from '@/lib/tone'
import { cn } from '@/lib/utils'

interface AttentionSearch {
    item?: string | undefined
}

/** The attention list: what needs the operator, most severe first, with `?item=` selecting one. */
export const Route = createFileRoute('/attention')({
    // `?item=<id>` selects an item by its fingerprint. Every key is returned, undefined when invalid (see runs.tsx).
    validateSearch: (search: Record<string, unknown>): AttentionSearch => {
        const item = search['item']
        return { item: typeof item === 'string' && item.length <= 200 ? item : undefined }
    },
    component: AttentionPage,
})

// A reason chip's tone: what is broken in the failure color, what waits on the operator in theirs, the rest plain.
const TONE: Record<Severity, Tone> = {
    failed: 'failed',
    waiting: 'blocked',
    other: 'plain',
    finding: 'plain',
}

// How long a cleared item's row plays its exit before it is let go: `animate-leave` in src/index.css, and a little
// over, so the row is folded shut before it goes.
const LEAVE_MS = 700

// The page's width under which the list and an item take turns rather than sit side by side: Tailwind's `@3xl`, the
// `@max-3xl:` and `@3xl:` classes below.
const TURNS_REM = 48

// The ids the page moves the focus to: the button back to the list, and an item's row.
const BACK = 'attention-back'
const rowId = (item: string): string => `attention-row-${item}`

// What `canopy models` is for, on an item refused its model about no ticket: it fixes nothing itself, but says what to.
const MODELS_NOTE =
    "Nothing to answer here: it lists the runtime's models and names any in [runtime.models] it lacks. " +
    'Choose one it lists, or set its provider up, and the item leaves when its cause is gone.'

function AttentionPage() {
    const { item: wanted } = Route.useSearch()
    const navigate = Route.useNavigate()
    const toast = useToast()
    const { data } = useQuery(attentionQuery)
    const tickets = useQuery(ticketsQuery).data
    const tasks = useQuery(tasksQuery).data
    const items = data === undefined ? undefined : bySeverity(data)
    const rows = useLeavingRows(data, items)
    // The item asked for while it is listed; else the most severe one about a ticket, which has a thread to show.
    const selected = items?.find((i) => i.id === wanted) ?? items?.find((i) => i.ticket_key !== null) ?? items?.[0]
    // Narrow, the item chosen is open in the list's place, as a page of its own, until the operator goes back to the
    // list, which then shows it chosen: `listFor` is the item they went back from.
    const [listFor, setListFor] = useState<string | undefined>(undefined)
    const open = wanted !== undefined && selected?.id === wanted && listFor !== wanted
    const pane = useRef<HTMLDivElement>(null)
    const focusOnce = useFocusOnce(wanted)

    function choose(item: string) {
        setListFor(undefined)
        // Narrow, the row is gone with the list: the focus goes to the item's first stop, the way back.
        if (narrow(pane.current)) {
            focusOnce(item, BACK)
        }
    }

    function back() {
        if (selected !== undefined) {
            setListFor(selected.id)
            focusOnce(selected.id, rowId(selected.id))
        }
    }

    function isDone(item: AttentionItem): boolean {
        return answered(item, tickets, tasks)
    }

    // A reply that answers its item moves on to the next that waits on the operator, its row chosen and focused, the
    // list in view; a toast says what the reply did, as the form that said it goes with its item.
    function moveOn(from: AttentionItem, said: string) {
        const next = items === undefined || ask(from) !== 'reply' ? null : nextWaiting(items, from.id, isDone)
        if (next === null) {
            return
        }
        toast({ title: said, tone: 'done' })
        setListFor(next.id)
        focusOnce(next.id, rowId(next.id))
        void navigate({ search: { item: next.id } })
    }

    return (
        <>
            <PageHeader title="Attention">
                What needs you, as <Code>canopy status</Code> lists it, most severe first. An item leaves when its cause
                is gone.
            </PageHeader>
            <Counters />
            {items !== undefined && items.length === 0 ? (
                <EmptyAttention />
            ) : (
                // Side by side from 48rem of the page's width; under it, the list and the item take turns, full width.
                <div ref={pane} className="@container">
                    <div className="flex items-start gap-6 @max-3xl:flex-col @max-3xl:items-stretch">
                        <div
                            className={cn(
                                'flex max-w-md min-w-0 flex-[1_1_22rem] flex-col gap-6 2xl:max-w-lg 2xl:basis-md',
                                '@max-3xl:max-w-none @max-3xl:flex-none',
                                open && '@max-3xl:hidden',
                            )}
                        >
                            {/* What is working now is the rail's, on every page: this column is the list alone. */}
                            <Panel data-testid="attention-list">
                                <PanelHeader label="Attention">
                                    <span className="readout text-xs text-muted-foreground">{items?.length}</span>
                                </PanelHeader>
                                {items === undefined ? (
                                    <PanelSkeleton className="min-h-40" />
                                ) : (
                                    <ul className="stagger flex flex-col gap-0.5 p-1.5">
                                        {rows.map(({ item, leaving }) =>
                                            leaving ? (
                                                <Leaving
                                                    key={item.id}
                                                    item={item}
                                                    done={answered(item, tickets, tasks)}
                                                />
                                            ) : (
                                                <Row
                                                    key={item.id}
                                                    item={item}
                                                    selected={item.id === selected?.id}
                                                    done={answered(item, tickets, tasks)}
                                                    onChoose={choose}
                                                />
                                            ),
                                        )}
                                    </ul>
                                )}
                            </Panel>
                        </div>
                        <div
                            className={cn(
                                'flex min-w-0 flex-[999_1_28rem] flex-col gap-2 @max-3xl:flex-none',
                                !open && '@max-3xl:hidden',
                            )}
                        >
                            <Button variant="ghost" id={BACK} onClick={back} className="self-start @3xl:hidden">
                                <ChevronLeft />
                                Back to the list
                            </Button>
                            {selected === undefined ? (
                                <Panel>
                                    <PanelSkeleton rows={1} className="min-h-72" />
                                </Panel>
                            ) : (
                                <Detail
                                    key={selected.id}
                                    item={selected}
                                    ticket={tickets?.find((t) => t.key === selected.ticket_key)}
                                    done={answered(selected, tickets, tasks)}
                                    onReplied={(said) => moveOn(selected, said)}
                                />
                            )}
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}

/**
 * The list's rows as the stream changes it: an item that leaves keeps its row a moment, leaving, so it can go with a
 * small reward rather than vanish (ui/DESIGN.md, "Fun"). Each list from the query is compared once, by identity, as it
 * arrives; the leaving rows are let go together once the last to leave has played its exit.
 */
function useLeavingRows(data: AttentionItem[] | undefined, items: AttentionItem[] | undefined) {
    const [listed, setListed] = useState(() => ({ from: data, rows: withLeaving([], items ?? []) }))
    if (listed.from !== data) {
        setListed({ from: data, rows: withLeaving(listed.rows, items ?? []) })
    }
    // Which rows are leaving, so one more leaving starts the wait again and every exit plays in full.
    const leaving = listed.rows
        .filter((row) => row.leaving)
        .map((row) => row.item.id)
        .join(' ')
    useEffect(() => {
        if (leaving === '') {
            return
        }
        const timer = globalThis.setTimeout(
            () => setListed((now) => ({ from: now.from, rows: settled(now.rows) })),
            LEAVE_MS,
        )
        return () => globalThis.clearTimeout(timer)
    }, [leaving])
    return listed.rows satisfies Listed<AttentionItem>[]
}

/**
 * Whether the page is too narrow for the list and an item side by side (`TURNS_REM`), measured as the operator acts,
 * since where the focus goes then depends on it. Unmeasured, as in a unit test, it is wide.
 */
function narrow(pane: HTMLElement | null): boolean {
    if (pane === null) {
        return false
    }
    const rem = Number.parseFloat(getComputedStyle(document.documentElement).fontSize)
    const { width } = pane.getBoundingClientRect()
    return width > 0 && width < TURNS_REM * rem
}

/**
 * Moves the focus once the page shows an item: `focusOnce(item, id)` focuses the element with `id` after the first
 * render that has `item` chosen and the element on screen, so a row or button the same change brings back is the one
 * focused, once.
 */
function useFocusOnce(wanted: string | undefined): (item: string, id: string) => void {
    const pending = useRef<{ item: string; id: string } | null>(null)
    // After every render: the change that brings the element back may be the URL's or the page's own.
    useEffect(() => {
        const want = pending.current
        if (want === null || want.item !== wanted) {
            return
        }
        const target = document.querySelector<HTMLElement>(`#${CSS.escape(want.id)}`)
        if (target !== null && target.getClientRects().length > 0) {
            pending.current = null
            target.focus()
        }
    })
    return (item, id) => {
        pending.current = { item, id }
    }
}

/**
 * A cleared item's row on its way out: the row as it was, fading and folding shut, while one of the empty inbox's
 * leaves drifts off it. It is only for the eye: no link, out of the tab order, hidden from a screen reader, which hears
 * the list's count change instead. Under reduced motion it is not shown at all, and the item is simply gone.
 */
function Leaving({ item, done }: { item: AttentionItem; done: boolean }) {
    return (
        // Not the list's arrival (`stagger`), which would hold a new element hidden through its delay: it is leaving.
        <li aria-hidden inert data-leaving className="relative animate-none! motion-reduce:hidden">
            <div className="animate-leave grid">
                <div className="min-h-0 overflow-hidden">
                    <div className="flex flex-col gap-1 rounded-sm px-2.5 py-2">
                        <RowContent item={item} done={done} />
                    </div>
                </div>
            </div>
            <Leaf className="top-2 right-10" />
        </li>
    )
}

function Row({
    item,
    selected,
    done,
    onChoose,
}: {
    item: AttentionItem
    selected: boolean
    done: boolean
    onChoose: (item: string) => void
}) {
    return (
        <li>
            <Link
                to="/attention"
                search={{ item: item.id }}
                id={rowId(item.id)}
                onClick={() => onChoose(item.id)}
                aria-current={selected ? 'page' : undefined}
                data-testid={`attention-item-${item.id}`}
                className={cn(
                    'flex flex-col gap-1 rounded-sm px-2.5 py-2 hover:bg-surface-raised',
                    selected && 'bg-accent/14 hover:bg-accent/14',
                )}
            >
                <RowContent item={item} done={done} />
            </Link>
        </li>
    )
}

/** What a row of the list says: the item's reason, its subject and age, its ticket's or task's title, its detail. */
function RowContent({ item, done }: { item: AttentionItem; done: boolean }) {
    return (
        <>
            <span className="flex items-center gap-2">
                <ReasonChip item={item} />
                {done && <Answered />}
                <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                    {/* A PR no ticket owns is named as the PR is everywhere, not by its URL behind `pr:`. */}
                    {item.pr === null ? item.subject : pullRequestLabel(item.pr)}
                    {item.finding ? ` ${item.reason}` : ''}
                </span>
                <Age at={item.since} className="ml-auto" />
            </span>
            {/* The title is the row's name and the detail its preview, as an inbox's subject over its first line. */}
            {item.ticket_key !== null && <TicketTitle title={item.ticket_title} className="font-semibold" />}
            {item.task !== null && <TaskTitle id={item.task} />}
            <span className="line-clamp-2 text-sm break-words text-muted-foreground">
                <InlineCode text={shownDetail(item)} links={false} />
            </span>
        </>
    )
}

/**
 * The item's reason as a chip. A chore's finding has the agent's own id for its reason, which is journal text, so its
 * chip says `finding` and the head line names the id beside its chore.
 */
function ReasonChip({ item }: { item: AttentionItem }) {
    return item.finding ? (
        <Chip>finding</Chip>
    ) : (
        <Chip tone={TONE[severity(item)]} word={item.reason} meaning={reasonMeaning(item.reason)} />
    )
}

/** On an `awaiting_reply` or `plan_review` item the operator has answered: it stays until a tick reads the answer. */
function Answered() {
    return <Chip tone="running">answered</Chip>
}

/**
 * The selected item. Its reason picks the first block under its head, what it asks of the operator (`ask`, ui/DESIGN.md
 * "The attention detail"): a broken run's row, the PR's link out, the plan's card, a feedback plan's line and the link
 * to its PR's page, the proposals or lessons memory's items name, the ticket's models for a run refused its own, or the
 * command to run. A ticket's item then shows its answer: its conversation and the reply form, with the ticket's own
 * actions and grants under them, or ahead of them when the reason asks for nothing else; a chore's item its notes and
 * the form for another, and for a finding the button to dismiss it; a review's draft's item the review's page, where
 * the draft is read and published; a running run's question, by letter, as its page answers it, before its ticket's
 * conversation when it has a ticket; a task's item the task's page, where it is read and answered; a PR's other item
 * its review limit and its grant, for a PR no ticket owns; an item about none of them, what it says. `ticket` is the
 * item's ticket as the tickets list has it, which tells a feedback plan's `plan_review` from a ticket plan's.
 * `onReplied` hears each reply sent from it, with what the form said of it.
 */
function Detail({
    item,
    ticket,
    done,
    onReplied,
}: {
    item: AttentionItem
    ticket: TicketSummary | undefined
    done: boolean
    onReplied: (said: string) => void
}) {
    const asks = ask(item, ticket)
    const command = asks === 'command' ? commandOf(item) : null
    const toast = useToast()
    // An answer takes the question off the list at once, and the item with it: a toast says what the answer did.
    const onAnswered = (said: string) => toast({ title: said, tone: 'done' })
    return (
        <Panel data-testid="attention-detail">
            <ItemHead item={item} asks={asks} done={done} />
            {/* First, as what the item asks: a chore's item refused its model shows its notes after it. */}
            {command !== null && (
                <RunCommand
                    command={command}
                    note={modelRefused(item) ? MODELS_NOTE : undefined}
                    className={cn((item.chore !== null || item.pr !== null) && 'border-b')}
                />
            )}
            {asks === 'plan' && item.ticket_key !== null && <PlanReview ticketKey={item.ticket_key} />}
            {asks === 'feedback-plan' && <FeedbackPlanReview item={item} plan={ticket?.feedback_plan ?? null} />}
            {asks === 'question' && <RunQuestion item={item} onAnswered={onAnswered} />}
            {item.reason === 'memory_proposal' && item.ticket_key !== null && (
                <ProposalsWaiting ticketKey={item.ticket_key} />
            )}
            {item.reason === 'lesson_review' && <LessonsDue />}
            {item.reason === 'lesson_wrong' && <LessonsWrong />}
            {item.ticket_key !== null && (
                <Thread item={item} ticketKey={item.ticket_key} asks={asks} onReplied={onReplied} />
            )}
            {item.chore !== null && <ChoreThread name={item.chore} />}
            {asks === 'review' && <ReviewAction item={item} />}
            {item.task !== null && <TaskAction item={item} task={item.task} />}
            {item.pr !== null && asks !== 'review' && <PullRequestLimits url={item.pr} />}
            {asks === 'none' && item.ticket_key === null && item.chore === null && item.pr === null && (
                <NothingToAnswer />
            )}
        </Panel>
    )
}

/**
 * The item's head, by what it is: a finding's, with its dismiss button; a question's, naming it rather than saying it;
 * or any other's. A PR waiting on someone else is linked once, as the item's action under the head, so its head names
 * it as text.
 */
function ItemHead({ item, asks, done }: { item: AttentionItem; asks: Ask; done: boolean }) {
    if (item.finding && item.chore !== null) {
        return <FindingHead item={item} chore={item.chore} done={done} />
    }
    if (item.reason === 'awaiting_reply' && item.ticket_key !== null) {
        return <AwaitingHead item={item} ticketKey={item.ticket_key} done={done} />
    }
    if (item.reason === 'awaiting_reply' && item.task !== null) {
        return <TaskAwaitingHead item={item} task={item.task} done={done} />
    }
    if (asks === 'question') {
        return <QuestionHead item={item} done={done} />
    }
    return <Head item={item} done={done} asks={asks} links={asks !== 'pull-request'} />
}

/**
 * A plan waiting on the operator: its card, as the ticket's page shows it (`PlanCard`), with Approve and the link to
 * its page, where it is read, commented on, and sent back (DESIGN §25). It is what the item asks for, so it comes
 * before the ticket's actions and conversation.
 */
function PlanReview({ ticketKey }: { ticketKey: string }) {
    const { data, error } = useQuery(ticketPlansQuery(ticketKey))
    if (error instanceof ApiError) {
        return <Notice error={error} className="border-b p-3" />
    }
    if (data === undefined) {
        return <PanelSkeleton rows={2} className="min-h-44 border-b" />
    }
    return <PlanCard ticketKey={ticketKey} plans={data} bare />
}

/**
 * A feedback plan waiting on the operator (DESIGN §32), as `FeedbackPlanWaits` says it: it is what the item asks for,
 * so it comes before the ticket's actions and conversation. Once it waits no more, the PR the item's detail names is
 * still linked.
 */
function FeedbackPlanReview({ item, plan }: { item: AttentionItem; plan: WaitingFeedbackPlan | null }) {
    const named = pullRequestOf(item)
    return (
        <FeedbackPlanWaits
            which={plan?.id ?? feedbackPlanOf(item)}
            urls={plan?.pr_urls ?? (named === null ? [] : [named])}
            plan={plan}
            className="border-b p-3"
            data-testid="attention-feedback-plan"
        />
    )
}

/**
 * What the item says: its reason, subject, and age, an action beside them, and its detail, or a `body` in its place,
 * with any notice below. Its detail's URLs and runs are linked unless `links` is false. `asks`, what the item asks
 * of the operator, words the line an answered item shows.
 */
function Head({
    item,
    done,
    asks,
    action,
    notice,
    body,
    links = true,
}: {
    item: AttentionItem
    done: boolean
    asks?: Ask
    action?: ReactNode
    notice?: ReactNode
    body?: ReactNode
    links?: boolean
}) {
    return (
        <div className="flex flex-col gap-2 border-b p-3">
            <div className="flex flex-wrap items-center gap-2">
                <ReasonChip item={item} />
                {done && <Answered />}
                <Subject item={item} />
                <Age at={item.since} className="ml-auto" />
                {action}
            </div>
            {body ?? (
                <p className="text-sm break-words whitespace-pre-wrap">
                    <InlineCode text={shownDetail(item)} links={links} />
                </p>
            )}
            {done && (
                <p className="text-sm text-muted-foreground" data-testid="answered-note">
                    {answeredNote(item, asks)}
                </p>
            )}
            {notice}
        </div>
    )
}

// What an answered item's head says under its detail: that it leaves at the next tick, which reads the answer.
function answeredNote(item: AttentionItem, asks: Ask | undefined): string {
    if (asks === 'feedback-plan') {
        return 'You answered the feedback plan. The item leaves at the next tick, when the loop reads your answer.'
    }
    return item.reason === 'plan_review'
        ? 'You answered the plan. The item leaves at the next tick, when the loop reads your answer.'
        : 'You answered it. The item leaves at the next tick, when the loop reads your reply.'
}

/**
 * A chore's finding's head: as any item's, with the button that dismisses it beside its age, and the finding as its
 * chore's page shows it: the item's detail runs its title and link together and leaves out what it says of itself.
 * Until the chore's page is read, or once the finding is gone from it, the item's detail stands in.
 */
function FindingHead({ item, chore, done }: { item: AttentionItem; chore: string; done: boolean }) {
    const { button, notice } = useDismissFinding(chore, item.reason, false)
    const { data } = useQuery(choreQuery(chore))
    const finding = data?.chore.findings.find((f) => f.id === item.reason)
    const body = finding === undefined ? undefined : <ChoreFindingText finding={finding} />
    return <Head item={item} done={done} action={button} notice={notice} body={body} />
}

/**
 * A question's head: as any item's, but naming the question by its message and when it was asked rather than saying
 * it, since the conversation under it holds the question, marked `waiting on you` (ui/DESIGN.md, "One home per fact").
 * Until the ticket is read the line is reserved; once nothing waits on the ticket, the item's detail stands in.
 */
function AwaitingHead({ item, ticketKey, done }: { item: AttentionItem; ticketKey: string; done: boolean }) {
    const { data } = useQuery(ticketQuery(ticketKey))
    if (data === undefined) {
        return <Head item={item} done={done} body={<Skeleton className="h-5 w-72 max-w-full" />} />
    }
    const waiting = data.messages.find((message) => message.id === data.ticket.awaiting)
    if (waiting === undefined) {
        return <Head item={item} done={done} />
    }
    const body = (
        <p className="text-sm" data-testid="awaiting-line">
            Waits on your answer to message {waiting.id}, asked <Age at={waiting.at} variant="ago" />.
        </p>
    )
    return <Head item={item} done={done} body={body} />
}

/**
 * A task's question's head: as a ticket's, naming the question by its message and when it was asked, since the task's
 * page holds it. Until the task is read the line is reserved; once nothing waits on it, the item's detail stands in.
 */
function TaskAwaitingHead({ item, task, done }: { item: AttentionItem; task: number; done: boolean }) {
    const { data } = useQuery(taskQuery(task))
    if (data === undefined) {
        return <Head item={item} done={done} body={<Skeleton className="h-5 w-72 max-w-full" />} />
    }
    const waiting = data.messages.find((message) => message.id === data.task.question_id)
    if (waiting === undefined) {
        return <Head item={item} done={done} />
    }
    const body = (
        <p className="text-sm" data-testid="awaiting-line">
            Waits on your answer to message {waiting.id}, asked <Age at={waiting.at} variant="ago" />.
        </p>
    )
    return <Head item={item} done={done} body={body} />
}

/**
 * A running run's question's head: as any item's, but naming whose question it is and when it was asked rather than
 * saying it, as a ticket's question's does, since the question is under it with its options (ui/DESIGN.md, "One home
 * per fact").
 */
function QuestionHead({ item, done }: { item: AttentionItem; done: boolean }) {
    const body = (
        <p className="text-sm" data-testid="question-line">
            Waits on your answer to {item.run !== null && <RunLink id={item.run} />}
            {item.review !== null && <ReviewLink id={item.review} />}&apos;s question, asked{' '}
            <Age at={item.since} variant="ago" />.
        </p>
    )
    return <Head item={item} done={done} body={body} />
}

/**
 * A running run's question (DESIGN §41), as its page shows it (`ProgressQuestion`): the question and each option by
 * its letter, each one a button that answers with it, as `canopy reply run:ID LETTER` does. It is what the item asks
 * for, so it comes before the ticket's conversation. The run's progress is read as its page reads it; once it asks
 * nothing, as after an answer, the item leaves the list.
 */
function RunQuestion({ item, onAnswered }: { item: AttentionItem; onAnswered: (said: string) => void }) {
    if (item.run !== null) {
        return <WorkerQuestion id={item.run} onAnswered={onAnswered} />
    }
    if (item.review !== null) {
        return <ReviewQuestion id={item.review} onAnswered={onAnswered} />
    }
    return null
}

/** A worker's or a planner's run's question, from the run as its page reads it. */
function WorkerQuestion({ id, onAnswered }: { id: number; onAnswered: (said: string) => void }) {
    const { data, error } = useQuery(runQuery(id))
    return (
        <QuestionBlock
            card={data?.card}
            running={data?.state === 'running'}
            error={error}
            answers={{ kind: 'run', id }}
            onAnswered={onAnswered}
        />
    )
}

/** A review's question, from the review as its page reads it. */
function ReviewQuestion({ id, onAnswered }: { id: number; onAnswered: (said: string) => void }) {
    const { data, error } = useQuery(reviewQuery(id))
    return (
        <QuestionBlock
            card={data?.card}
            running={data?.review.state === 'running'}
            error={error}
            answers={{ kind: 'review', id }}
            onAnswered={onAnswered}
        />
    )
}

/** The question a run's progress asks, `card` undefined until it is read; nothing once it asks none. */
function QuestionBlock({
    card,
    running,
    error,
    answers,
    onAnswered,
}: {
    card: RunCard | null | undefined
    running: boolean
    error: Error | null
    answers: AnswerTarget
    onAnswered: (said: string) => void
}) {
    if (error instanceof ApiError) {
        return <Notice error={error} className="border-b p-3" />
    }
    if (card === undefined) {
        return <PanelSkeleton rows={2} className="min-h-44 border-b" />
    }
    const question = card?.question ?? null
    if (question === null) {
        return null
    }
    return (
        <div className="border-b p-3" data-testid="attention-question">
            <ProgressQuestion
                key={question.asked_at}
                question={question}
                running={running}
                answers={answers}
                onAnswered={onAnswered}
            />
        </div>
    )
}

function Subject({ item }: { item: AttentionItem }) {
    if (item.ticket_key !== null) {
        return (
            <>
                <TicketLink ticketKey={item.ticket_key} className="shrink-0" />
                <TicketTitle title={item.ticket_title} className="font-semibold" />
            </>
        )
    }
    if (item.chore !== null) {
        return (
            <>
                <ChoreLink name={item.chore} />
                {item.finding && <span className="font-mono text-xs text-muted-foreground">{item.reason}</span>}
            </>
        )
    }
    if (item.pr !== null) {
        return <PullRequestLink url={item.pr} />
    }
    if (item.task !== null) {
        return (
            <>
                <TaskLink id={item.task} className="shrink-0" />
                <TaskTitle id={item.task} />
            </>
        )
    }
    if (item.review !== null) {
        return <ReviewLink id={item.review} />
    }
    return <span className="font-mono text-xs">{item.subject}</span>
}

function NothingToAnswer() {
    return <Empty>nothing to answer here: it leaves when its cause is gone</Empty>
}

/**
 * An item whose fix is a command for the operator to run, such as `repo_missing`'s: the command, to copy, and `note`,
 * what running it does, for a command that does not fix the item itself.
 */
function RunCommand({ command, note, className }: { command: string; note?: string; className?: string }) {
    return (
        <div className={cn('flex flex-col items-start gap-2 p-3', className)} data-testid="attention-command">
            <Copyable
                text={command}
                label="command"
                className="rounded-sm bg-surface-raised px-2 py-1 font-mono text-xs"
            >
                {command}
            </Copyable>
            <p className="text-xs text-muted-foreground">
                {note ?? 'Nothing to answer here: run it, and the item leaves when its cause is gone.'}
            </p>
        </div>
    )
}

/** A PR's item: a grant of one more review when the PR is at its review limit (DESIGN §21), else nothing to answer. */
function PullRequestLimits({ url }: { url: string }) {
    const { data, error } = useQuery(pullRequestQuery(url))
    if (error instanceof ApiError) {
        return <Notice error={error} className="p-3" />
    }
    if (data === undefined) {
        return <PanelSkeleton rows={1} className="min-h-24" />
    }
    const limits = data.review_limit === null ? [] : [data.review_limit]
    return limits.some((limit) => limit.runs >= limit.limit) ? (
        <GrantLimits limits={limits} ticketKey={null} />
    ) : (
        <NothingToAnswer />
    )
}

/** A chore's item: the chore's notes, which its next runs read, and the form for another (DESIGN §19). */
function ChoreThread({ name }: { name: string }) {
    const { data, error } = useQuery(choreQuery(name))
    if (error instanceof ApiError) {
        return <Notice error={error} className="p-3" />
    }
    if (data === undefined) {
        return <PanelSkeleton className="min-h-60" />
    }
    return <ChoreNotes detail={data} />
}

/**
 * A ticket's item under its head: what its reason asks first (a broken run's row and any grant it is stuck at, the
 * PR's link out, or the ticket's models for a run refused its own), then the ticket's answer (`TicketAnswer`): its
 * conversation, the reply form (`ReplyForm`), and the ticket's verbs and any other grant as a quiet row under them. On
 * a reason that asks for nothing else, the verbs lead instead, as what the item asks for.
 */
function Thread({
    item,
    ticketKey,
    asks,
    onReplied,
}: {
    item: AttentionItem
    ticketKey: string
    asks: Ask
    onReplied: (said: string) => void
}) {
    const { data, error } = useQuery(ticketQuery(ticketKey))
    if (error instanceof ApiError) {
        return <Notice error={error} className="p-3" />
    }
    if (data === undefined) {
        return <PanelSkeleton className="min-h-60" />
    }
    const { ticket } = data
    const leads = asks === 'ticket'
    return (
        <>
            {asks === 'run' && <LatestRun runs={data.runs} />}
            {/* A run that broke at its limit: another try is what it asks, beside the run that says why. */}
            {asks === 'run' && (
                <GrantLimits
                    key={`limits-${ticket.key}`}
                    limits={data.limits}
                    ticketKey={ticket.key}
                    className="border-b"
                />
            )}
            {asks === 'pull-request' && <PullRequestAction item={item} units={data.units} />}
            {asks === 'drafts' && <DraftsAction item={item} ticketKey={ticket.key} drafts={data.drafts} />}
            {asks === 'model' && <ModelAttention ticketKey={ticket.key} models={data.models} />}
            {leads && <TicketVerbs ticket={ticket} limits={data.limits} place="lead" testId="attention-actions" />}
            <TicketAnswer
                detail={data}
                item
                leaf={false}
                onReplied={(_, said) => onReplied(said)}
                after={
                    !leads && (
                        <TicketVerbs
                            ticket={ticket}
                            limits={asks === 'run' ? null : data.limits}
                            place="after"
                            quiet
                            testId="attention-actions"
                        />
                    )
                }
            />
        </>
    )
}

/**
 * A run that broke: the ticket's latest run as its page's Runs list shows it, its state, `run:N`, what it said, and its
 * cost, so why it failed is read here and its page is one click away.
 */
function LatestRun({ runs }: { runs: Run[] }) {
    const [latest] = runs
    if (latest === undefined) {
        return null
    }
    return (
        <div className="border-b" data-testid="attention-run">
            <RunsTable runs={[latest]} ticket={false} />
        </div>
    )
}

/**
 * Replies a run drafted (DESIGN §29): for a PR, its page, where each sits on its thread to read, edit, drop, or send;
 * for the ticket itself, the ticket's own drafts that wait, here, with their verbs.
 */
function DraftsAction({ item, ticketKey, drafts }: { item: AttentionItem; ticketKey: string; drafts: Draft[] }) {
    const url = pullRequestOf(item)
    if (url === null) {
        const open = drafts.filter((d) => d.status === 'waiting')
        return <TicketDrafts ticketKey={ticketKey} drafts={open} bare className="border-b" />
    }
    return (
        <div className="flex flex-wrap items-center gap-2 border-b p-3" data-testid="attention-drafts">
            <Button asChild variant="outline">
                <Link to="/pull-requests/pr" search={{ url }}>
                    <MessageSquareReply />
                    Read the drafts on {pullRequestLabel(url)}
                </Link>
            </Button>
        </div>
    )
}

/**
 * A review's draft that waits on the operator (DESIGN §34): the review's page, where the draft is read, edited, and
 * published or staged; for one staged or of unknown outcome, where it says how it stands until a read settles it.
 */
function ReviewAction({ item }: { item: AttentionItem }) {
    const id = reviewOf(item)
    if (id === null) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-2 border-b p-3" data-testid="attention-review">
            <Button asChild variant="outline">
                <Link to="/pull-requests/reviews/$id" params={{ id: String(id) }}>
                    <FileText />
                    {item.reason === 'review_waiting' ? 'Read the draft of' : 'See the draft of'} {reviewRef(id)}
                </Link>
            </Button>
        </div>
    )
}

/**
 * A task's title, the first line of the operator's text, as the tasks list names it: the item's name beside `task:N`,
 * as a ticket's title is. Its line is reserved until the list is read.
 */
function TaskTitle({ id }: { id: number }) {
    const { data } = useQuery(tasksQuery)
    if (data === undefined) {
        return <Skeleton className="h-5 w-48 max-w-full" />
    }
    const task = data.find((t) => t.id === id)
    return <TicketTitle title={task === undefined ? null : taskTitle(task.text)} className="font-semibold" />
}

/**
 * A one-off task's item (DESIGN §36): its page, where its conversation and report are read and it is answered. A
 * question's is the way to answer it; any other's, such as tickets its run reported that canopy did not record, opens
 * the task, which a reply or a stop clears.
 */
function TaskAction({ item, task }: { item: AttentionItem; task: number }) {
    const answer = item.reason === 'awaiting_reply'
    return (
        <div className="flex flex-wrap items-center gap-2 border-b p-3" data-testid="attention-task">
            <Button asChild variant="outline">
                <Link to="/tasks/$id" params={{ id: String(task) }}>
                    {answer ? <MessageSquareReply /> : <Sprout />}
                    {answer ? 'Answer on' : 'Open'} {taskRef(task)}
                </Link>
            </Button>
        </div>
    )
}

/**
 * A PR waiting on someone else, a reviewer or its merge: the PR on its host is what the item asks for, the one place
 * the detail links it. It is the PR the item's detail names, else the ticket's one PR.
 */
function PullRequestAction({ item, units }: { item: AttentionItem; units: Unit[] }) {
    const prs = units.flatMap((unit) => (unit.pr_url === null ? [] : [unit.pr_url]))
    const url = pullRequestOf(item) ?? (prs.length === 1 ? (prs[0] ?? null) : null)
    if (url === null) {
        return null
    }
    const label = pullRequestLabel(url)
    return (
        <div className="flex flex-wrap items-center gap-2 border-b p-3" data-testid="attention-pull-request">
            <LinkOutButton
                href={url}
                label={`${label} on ${onGitHub(url) ? 'GitHub' : 'its host'}`}
                icon={GitPullRequest}
                hint={item.reason === 'ready_to_merge' ? 'Merge it there: canopy never merges' : 'Review it there'}
            />
        </div>
    )
}
