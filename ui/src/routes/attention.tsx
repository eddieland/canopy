import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ChevronLeft, FileText, GitPullRequest, MessageSquareReply, Sprout } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'

import { ApiError } from '@/api/client'
import type { AnswerTarget } from '@/api/mutations'
import {
    attentionQuery,
    choreQuery,
    epicPlansQuery,
    epicQuery,
    epicsQuery,
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
import { Copyable } from '@/components/copy-button'
import { useDismissFinding } from '@/components/dismiss-finding'
import { EpicLink } from '@/components/epic-link'
import { FeedbackPlanWaits } from '@/components/feedback-plan-card'
import { GrantLimits } from '@/components/grant-limits'
import { Leaf } from '@/components/leaf'
import { LessonsDue, LessonsWrong, ProposalsWaiting } from '@/components/memory-attention'
import { ModelAttention } from '@/components/model-attention'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import type { PanelRead } from '@/components/panel'
import { PlanCard } from '@/components/plan-card'
import { DecisionsCount } from '@/components/plan-decisions'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReviewLink } from '@/components/review-link'
import { InlineCode } from '@/components/rich-text'
import { RunLink } from '@/components/run-link'
import { ProgressQuestion } from '@/components/run-progress'
import { RunsTable } from '@/components/runs-table'
import { Starburst } from '@/components/starburst'
import { Chip } from '@/components/status'
import { TaskLink } from '@/components/task-link'
import { TicketAnswer, TicketVerbs } from '@/components/ticket-answer'
import { TicketDrafts } from '@/components/ticket-drafts'
import { TicketLink } from '@/components/ticket-link'
import { LinkOutButton } from '@/components/ticket-links'
import { TicketTitle } from '@/components/ticket-title'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAttention } from '@/hooks/use-attention'
import { useLeavingRows } from '@/hooks/use-leaving-rows'
import { useToast } from '@/hooks/use-toast'
import { answered } from '@/lib/acknowledged'
import {
    ask,
    bySeverity,
    commandOf,
    feedbackPlanOf,
    modelRefused,
    nextWaiting,
    oldestWaiting,
    pullRequestOf,
    reviewOf,
    severity,
    shownDetail,
} from '@/lib/attention'
import type { Ask, Severity } from '@/lib/attention'
import { useFindingsHidden } from '@/lib/attention-findings'
import { counted } from '@/lib/descriptions'
import { epicTitle } from '@/lib/epics'
import { onGitHub } from '@/lib/links'
import { reasonMeaning } from '@/lib/meanings'
import { epicOpenDecisions, openDecisions } from '@/lib/plan-state'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { epicRef, reviewRef, taskRef } from '@/lib/refs'
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

// What the page shows, the same on every visit, on its title's hover (ui/DESIGN.md, "A detail page leads with what it
// is about").
const HELP = 'What needs you, as canopy status lists it, most severe first. An item leaves when its cause is gone.'

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
    const attention = useAttention()
    const { data } = attention
    const tickets = useQuery(ticketsQuery).data
    const tasks = useQuery(tasksQuery).data
    const items = data === undefined ? undefined : bySeverity(data)
    const { rows, clearing, cleared, burst } = useLeavingRows(data, items)
    const selected = useSelected(items, wanted)
    // Narrow, the item chosen is open in the list's place, as a page of its own, until the operator goes back to the
    // list, which then shows it chosen: `listFor` is the item they went back from.
    const [listFor, setListFor] = useState<string | undefined>(undefined)
    const open = wanted !== undefined && selected?.id === wanted && listFor !== wanted
    const pane = useRef<HTMLDivElement>(null)
    const focusOnce = useFocusOnce(wanted)
    const scroller = useRef<HTMLElement>(null)
    useNamedRowInView(scroller, selected?.id === wanted ? wanted : undefined)

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

    // What an item asks, its ticket as the tickets list has it telling a feedback plan's review from a ticket plan's.
    function askOf(item: AttentionItem): Ask {
        return ask(
            item,
            tickets?.find((t) => t.key === item.ticket_key),
        )
    }

    const oldest = items === undefined ? null : oldestWaiting(items, isDone)

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
            <PageHeader title="Attention" help={HELP} />
            <HiddenFindings />
            {items !== undefined && items.length === 0 && !clearing ? (
                // The page's arrival (`stagger`) brings the all clear in only after the last item's exit, which earned
                // it: a read that finds the list empty just shows it.
                <div className={cn(!cleared && 'animate-none!')}>
                    <EmptyAttention />
                </div>
            ) : (
                // Side by side from 48rem of the page's width; under it, the list and the item take turns, full width.
                <div ref={pane} className="@container">
                    <div className="flex items-start gap-6 @max-3xl:flex-col @max-3xl:items-stretch">
                        <div
                            className={cn(
                                'flex max-w-md min-w-0 flex-[1_1_22rem] flex-col gap-6 2xl:max-w-lg 2xl:basis-md',
                                '@max-3xl:max-w-none @max-3xl:flex-none',
                                '@3xl:sticky @3xl:top-6 @3xl:print:static',
                                open && '@max-3xl:hidden',
                            )}
                        >
                            {/* What is working now is the rail's, on every page: this column is the list alone. Side
                            by side it stays put and scrolls in itself, so choosing a low row keeps it in view while
                            the page, which only the item scrolls, opens the item at its top. Its height fits the window
                            under the shell's header, the page's title, and the main pane's padding: 10.75rem. */}
                            <Panel
                                data-testid="attention-list"
                                className={cn(
                                    'flex flex-col @3xl:max-h-[max(20rem,calc(100dvh-10.75rem))]',
                                    '@3xl:print:max-h-none',
                                )}
                            >
                                <PanelHeader label="Attention">
                                    <span className="text-xs whitespace-nowrap text-muted-foreground">
                                        {oldest !== null && (
                                            <span data-testid="attention-oldest">
                                                oldest waiting <Age at={oldest} className="inline" />
                                                {' · '}
                                            </span>
                                        )}
                                        <span className="readout" data-testid="attention-count">
                                            {items?.length}
                                        </span>
                                    </span>
                                </PanelHeader>
                                {items === undefined ? (
                                    <PanelLoading query={attention} className="min-h-40" />
                                ) : (
                                    <PanelScroll ref={scroller} label="Attention items" className="max-h-none min-h-0">
                                        <ul className="stagger flex flex-col gap-0.5 p-1.5">
                                            {rows.map(({ item, leaving }) =>
                                                leaving ? (
                                                    <Leaving
                                                        key={item.id}
                                                        item={item}
                                                        asks={askOf(item)}
                                                        done={answered(item, tickets, tasks)}
                                                        burst={item.id === burst}
                                                    />
                                                ) : (
                                                    <Row
                                                        key={item.id}
                                                        item={item}
                                                        asks={askOf(item)}
                                                        selected={item.id === selected?.id}
                                                        done={answered(item, tickets, tasks)}
                                                        onChoose={choose}
                                                    />
                                                ),
                                            )}
                                        </ul>
                                    </PanelScroll>
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
                                // Only while the list is read: a list that failed says so once, in its own panel, and
                                // one read empty, its last row on its way out, has nothing to load.
                                items === undefined &&
                                attention.error === null && (
                                    <Panel>
                                        <PanelSkeleton rows={1} className="min-h-72" />
                                    </Panel>
                                )
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
 * The item the page shows: the one asked for while it is listed. Once it leaves, the row that took its place, so a
 * long list is worked down where the operator stands. With none asked for, or one never seen listed, as on an old link,
 * the most severe item about a ticket, which has a thread to show.
 */
function useSelected(items: AttentionItem[] | undefined, wanted: string | undefined): AttentionItem | undefined {
    const [place, setPlace] = useState<{ item: string; index: number } | undefined>(undefined)
    const index = items?.findIndex((i) => i.id === wanted) ?? -1
    if (wanted !== undefined && index !== -1 && (place?.item !== wanted || place.index !== index)) {
        setPlace({ item: wanted, index })
    }
    if (index !== -1) {
        return items?.[index]
    }
    const successor = place !== undefined && place.item === wanted ? (items?.[place.index] ?? items?.at(-1)) : undefined
    return successor ?? items?.find((i) => i.ticket_key !== null) ?? items?.[0]
}

/**
 * Brings the row of the item the URL names into view in the list that scrolls in itself, when none of it shows, as on a
 * reload or a notification's link: the list alone moves, never the page, and a row the operator can see stays put.
 * Named again only when `item` changes, so the stream never takes a list they scrolled away.
 */
function useNamedRowInView(scroller: RefObject<HTMLElement | null>, item: string | undefined) {
    useLayoutEffect(() => {
        const list = scroller.current
        const row = item === undefined ? null : (list?.querySelector('[aria-current=page]') ?? null)
        if (list === null || row === null) {
            return
        }
        const shown = list.getBoundingClientRect()
        const { top, bottom } = row.getBoundingClientRect()
        if (list.scrollHeight > list.clientHeight && (bottom <= shown.top || top >= shown.bottom)) {
            list.scrollBy({ top: (top + bottom - shown.top - shown.bottom) / 2, behavior: 'instant' })
        }
    }, [scroller, item])
}

/**
 * While Settings hides chores' findings from the list, how many it leaves out, so a hidden finding is never mistaken
 * for none: a muted line linking to the setting. Nothing while none is hidden.
 */
function HiddenFindings() {
    const hidden = useFindingsHidden()
    const findings = useQuery(attentionQuery).data?.filter((item) => item.finding).length ?? 0
    if (!hidden || findings === 0) {
        return null
    }
    return (
        <p className="text-sm text-muted-foreground" data-testid="attention-findings-hidden">
            {counted(findings, 'chore finding')} hidden from this list, as your{' '}
            <Link to="/settings" hash="attention" className="text-accent underline-offset-4 hover:underline">
                settings
            </Link>{' '}
            ask. Each chore&apos;s page still lists its own.
        </p>
    )
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
 * leaves drifts off it. The row given the list's one `burst` may go off instead, where the palette shows a starburst
 * in the leaf's place, inside the row's own room, which folds shut over it. It is only for the eye: no link, out of the
 * tab order, hidden from a screen reader, which hears the list's count change instead. Under reduced motion it is not
 * shown at all, and the item is simply gone.
 */
function Leaving({ item, asks, done, burst }: { item: AttentionItem; asks: Ask; done: boolean; burst: boolean }) {
    return (
        // Not the list's arrival (`stagger`), which would hold a new element hidden through its delay: it is leaving.
        <li aria-hidden inert data-leaving className="relative animate-none! motion-reduce:hidden">
            <div className="animate-leave grid">
                <div className="min-h-0 overflow-hidden">
                    <div className="flex flex-col gap-1 rounded-sm px-2.5 py-2">
                        <RowContent item={item} asks={asks} done={done} />
                    </div>
                </div>
            </div>
            {burst ? (
                <>
                    <span className="burst-leaf">
                        <Leaf className="top-2 right-10" />
                    </span>
                    <span className="pointer-events-none absolute inset-0 overflow-hidden">
                        <Starburst id={item.id} className="top-2.5 right-8" />
                    </span>
                </>
            ) : (
                <Leaf className="top-2 right-10" />
            )}
        </li>
    )
}

function Row({
    item,
    asks,
    selected,
    done,
    onChoose,
}: {
    item: AttentionItem
    asks: Ask
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
                    'motion-safe:transition-[translate,box-shadow] motion-safe:duration-150',
                    // Selected, it wears its palette's ink, if it draws one: lifted off the list onto a hard drop, in
                    // front of the row below it. A shadow and a transform, so nothing moves around it.
                    selected && 'relative z-1 bg-accent/14 shadow-selected hover:bg-accent/14',
                    selected && 'translate-x-(--lift-x) translate-y-(--lift-y)',
                )}
            >
                <RowContent item={item} asks={asks} done={done} />
            </Link>
        </li>
    )
}

/**
 * What a row of the list says: the item's reason, its subject and age, its ticket's or task's title or its epic's goal,
 * its detail. A plan that waits on the operator says beside its subject how many decisions it leaves open to them, so
 * a plan that asks something is told from one that only wants its approval before either is opened.
 */
function RowContent({ item, asks, done }: { item: AttentionItem; asks: Ask; done: boolean }) {
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
                {asks === 'plan' && item.ticket_key !== null && <TicketPlanDecisions ticketKey={item.ticket_key} />}
                {asks === 'epic' && item.epic !== null && <EpicPlanDecisions epic={item.epic} />}
                <Age at={item.since} className="ml-auto" />
            </span>
            {/* The title is the row's name and the detail its preview, as an inbox's subject over its first line. */}
            {item.ticket_key !== null && <TicketTitle title={item.ticket_title} className="font-semibold" />}
            {item.task !== null && <TaskTitle id={item.task} />}
            {item.epic !== null && <EpicGoal id={item.epic} />}
            <span className="line-clamp-2 text-sm break-words text-muted-foreground">
                <InlineCode text={shownDetail(item)} links={false} />
            </span>
        </>
    )
}

/**
 * How many decisions a ticket's plan waiting on the operator leaves open, from its plans as its card reads them.
 * Nothing until they are read, or for a plan that asks none.
 */
function TicketPlanDecisions({ ticketKey }: { ticketKey: string }) {
    const { data } = useQuery(ticketPlansQuery(ticketKey))
    return <DecisionsCount count={data === undefined ? 0 : openDecisions(data).length} />
}

/** The same for an epic's plan, from its plans as its page reads them. */
function EpicPlanDecisions({ epic }: { epic: number }) {
    const { data } = useQuery(epicPlansQuery(epic))
    return <DecisionsCount count={data === undefined ? 0 : epicOpenDecisions(data).length} />
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
 * conversation when it has a ticket; a task's item the task's page, where it is read and answered; an epic's plan its
 * plan's page, where it is read, approved, or sent back; a PR's other item
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
            {asks === 'epic' && item.epic !== null && <EpicAction epic={item.epic} />}
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
    if (asks === 'epic' && item.epic !== null) {
        return <EpicPlanHead item={item} epic={item.epic} done={done} />
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
    const query = useQuery(ticketPlansQuery(ticketKey))
    const { data, error } = query
    if (error instanceof ApiError) {
        return <Notice error={error} className="border-b p-3" />
    }
    if (data === undefined) {
        return <PanelLoading query={query} rows={2} className="min-h-44 border-b" />
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
                {/* Its own group, which shrinks and cuts a long title or goal rather than wrap the age onto a line of
                its own: it wraps whole only once fewer than its basis's columns are left beside the chip. */}
                <span className="flex min-w-0 flex-1 basis-40 items-center gap-2" data-testid="attention-subject">
                    <Subject item={item} />
                </span>
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
 * An epic's plan's head: as a task's question's, naming the plan and when it was written rather than the `canopy`
 * commands its detail names, since its page holds the plan and its answers. Until the epic is read the line is
 * reserved; once its plan waits no more, the item's detail stands in.
 */
function EpicPlanHead({ item, epic, done }: { item: AttentionItem; epic: number; done: boolean }) {
    const { data } = useQuery(epicQuery(epic))
    if (data === undefined) {
        return <Head item={item} done={done} body={<Skeleton className="h-5 w-72 max-w-full" />} />
    }
    const plan = data.plan
    if (plan?.status !== 'proposed') {
        return <Head item={item} done={done} />
    }
    const body = (
        <p className="text-sm" data-testid="epic-plan-line">
            Its plan {plan.id} waits on your approval, written <Age at={plan.created_at} variant="ago" />.
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
    const query = useQuery(runQuery(id))
    const { data } = query
    return (
        <QuestionBlock
            card={data?.card}
            running={data?.state === 'running'}
            query={query}
            answers={{ kind: 'run', id }}
            onAnswered={onAnswered}
        />
    )
}

/** A review's question, from the review as its page reads it. */
function ReviewQuestion({ id, onAnswered }: { id: number; onAnswered: (said: string) => void }) {
    const query = useQuery(reviewQuery(id))
    const { data } = query
    return (
        <QuestionBlock
            card={data?.card}
            running={data?.review.state === 'running'}
            query={query}
            answers={{ kind: 'review', id }}
            onAnswered={onAnswered}
        />
    )
}

/** The question a run's progress asks, `card` undefined until it is read; nothing once it asks none. */
function QuestionBlock({
    card,
    running,
    query,
    answers,
    onAnswered,
}: {
    card: RunCard | null | undefined
    running: boolean
    /** The read of the run or review that carries the card. */
    query: PanelRead
    answers: AnswerTarget
    onAnswered: (said: string) => void
}) {
    if (query.error instanceof ApiError) {
        return <Notice error={query.error} className="border-b p-3" />
    }
    if (card === undefined) {
        return <PanelLoading query={query} rows={2} className="min-h-44 border-b" />
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
    if (item.epic !== null) {
        return (
            <>
                <EpicLink id={item.epic} className="shrink-0" />
                <EpicGoal id={item.epic} />
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
    const query = useQuery(pullRequestQuery(url))
    const { data, error } = query
    if (error instanceof ApiError) {
        return <Notice error={error} className="p-3" />
    }
    if (data === undefined) {
        return <PanelLoading query={query} rows={1} className="min-h-24" />
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
    const query = useQuery(choreQuery(name))
    const { data, error } = query
    if (error instanceof ApiError) {
        return <Notice error={error} className="p-3" />
    }
    if (data === undefined) {
        return <PanelLoading query={query} className="min-h-60" />
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
    const query = useQuery(ticketQuery(ticketKey))
    const { data, error } = query
    if (error instanceof ApiError) {
        return <Notice error={error} className="p-3" />
    }
    if (data === undefined) {
        return <PanelLoading query={query} className="min-h-60" />
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

/** An epic's goal's first line, as its row in the epics list names it, from that list. */
function EpicGoal({ id }: { id: number }) {
    const { data } = useQuery(epicsQuery)
    if (data === undefined) {
        return <Skeleton className="h-5 w-48 max-w-full" />
    }
    const epic = data.find((e) => e.id === id)
    return <TicketTitle title={epic === undefined ? null : epicTitle(epic.text)} className="font-semibold" />
}

/**
 * An epic's plan waiting on the operator (DESIGN §43): its plan's page, where its text is read, commented on, and
 * approved or sent back. Only the operator approves an epic's plan, so it is one tab stop from here. A plan that leaves
 * decisions open says so beside the link, since its page is where they are answered.
 */
function EpicAction({ epic }: { epic: number }) {
    const { data } = useQuery(epicPlansQuery(epic))
    const decisions = data === undefined ? 0 : epicOpenDecisions(data).length
    return (
        <div className="flex flex-wrap items-center gap-2 border-b p-3" data-testid="attention-epic">
            <Button asChild variant="outline">
                <Link to="/epics/$id/plan" params={{ id: String(epic) }}>
                    <FileText />
                    Open {epicRef(epic)}&apos;s plan
                </Link>
            </Button>
            {decisions > 0 && (
                <span className="text-xs text-muted-foreground">
                    {decisions === 1 ? '1 open decision' : `${decisions} open decisions`}: its page asks{' '}
                    {decisions === 1 ? 'it' : 'each'}, the planner&apos;s choice picked.
                </span>
            )}
        </div>
    )
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
