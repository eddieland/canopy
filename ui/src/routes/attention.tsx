import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ChevronLeft, GitPullRequest, MessageSquareReply } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import {
    attentionQuery,
    choreQuery,
    pullRequestQuery,
    ticketPlansQuery,
    ticketQuery,
    ticketsQuery,
} from '@/api/queries'
import type { AttentionItem, Draft, Run, Unit } from '@/api/types'
import { EmptyAttention } from '@/components/all-clear'
import { Age } from '@/components/age'
import { ChoreFindingText } from '@/components/chore-finding'
import { ChoreLink } from '@/components/chore-link'
import { ChoreNotes } from '@/components/chore-notes'
import { Copyable } from '@/components/copy-button'
import { Counters } from '@/components/counters'
import { useDismissFinding } from '@/components/dismiss-finding'
import { GrantLimits } from '@/components/grant-limits'
import { Leaf } from '@/components/leaf'
import { Notice } from '@/components/notice'
import { PlanCard } from '@/components/plan-card'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { LessonsDue, LessonsWrong, ProposalsWaiting } from '@/components/memory-attention'
import { InlineCode } from '@/components/rich-text'
import { RunsTable } from '@/components/runs-table'
import { Chip } from '@/components/status'
import { TicketAnswer, TicketVerbs } from '@/components/ticket-answer'
import { TicketDrafts } from '@/components/ticket-drafts'
import { TicketLink } from '@/components/ticket-link'
import { LinkOutButton } from '@/components/ticket-links'
import { TicketTitle } from '@/components/ticket-title'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/hooks/use-toast'
import { answered } from '@/lib/acknowledged'
import { ask, bySeverity, commandOf, nextWaiting, pullRequestOf, severity, shownDetail } from '@/lib/attention'
import type { Ask, Severity } from '@/lib/attention'
import { settled, withLeaving } from '@/lib/leaving'
import type { Listed } from '@/lib/leaving'
import { onGitHub } from '@/lib/links'
import { cn } from '@/lib/utils'
import { pullRequestLabel } from '@/lib/pull-request-label'
import type { Tone } from '@/lib/tone'

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

function AttentionPage() {
    const { item: wanted } = Route.useSearch()
    const navigate = Route.useNavigate()
    const toast = useToast()
    const { data } = useQuery(attentionQuery)
    const tickets = useQuery(ticketsQuery).data
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
        return answered(item, tickets)
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
                What needs you, as <code className="font-mono text-xs">canopy status</code> lists it, most severe first.
                An item leaves when its cause is gone.
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
                                                <Leaving key={item.id} item={item} done={answered(item, tickets)} />
                                            ) : (
                                                <Row
                                                    key={item.id}
                                                    item={item}
                                                    selected={item.id === selected?.id}
                                                    done={answered(item, tickets)}
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
                                    done={answered(selected, tickets)}
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

/** What a row of the list says: the item's reason, its subject and age, its ticket's title, and its detail. */
function RowContent({ item, done }: { item: AttentionItem; done: boolean }) {
    return (
        <>
            <span className="flex items-center gap-2">
                <ReasonChip item={item} />
                {done && <Answered />}
                <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                    {item.subject}
                    {item.finding ? ` ${item.reason}` : ''}
                </span>
                <Age at={item.since} className="ml-auto" />
            </span>
            {/* The title is the row's name and the detail its preview, as an inbox's subject over its first line. */}
            {item.ticket_key !== null && <TicketTitle title={item.ticket_title} className="font-semibold" />}
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
    return item.finding ? <Chip>finding</Chip> : <Chip tone={TONE[severity(item)]} word={item.reason} />
}

/** On an `awaiting_reply` item the operator has answered: it stays until a tick reads the answer. */
function Answered() {
    return <Chip tone="running">answered</Chip>
}

/**
 * The selected item. Its reason picks the first block under its head, what it asks of the operator (`ask`, ui/DESIGN.md
 * "The attention detail"): a broken run's row, the PR's link out, the plan's card, the proposals or lessons memory's
 * items name, or the command to run. A ticket's item then shows its answer: its conversation and the reply form, with
 * the ticket's own actions and grants under them, or ahead of them when the reason asks for nothing else; a chore's
 * item its notes and the form for another, and for a finding the button to dismiss it; a PR's item its review limit
 * and its grant, for a PR no ticket owns; an item about none of them, what it says. `onReplied` hears each reply sent
 * from it, with what the form said of it.
 */
function Detail({ item, done, onReplied }: { item: AttentionItem; done: boolean; onReplied: (said: string) => void }) {
    const asks = ask(item)
    const command = asks === 'command' ? commandOf(item) : null
    return (
        <Panel data-testid="attention-detail">
            <ItemHead item={item} asks={asks} done={done} />
            {asks === 'plan' && item.ticket_key !== null && <PlanReview ticketKey={item.ticket_key} />}
            {item.reason === 'memory_proposal' && item.ticket_key !== null && (
                <ProposalsWaiting ticketKey={item.ticket_key} />
            )}
            {item.reason === 'lesson_review' && <LessonsDue />}
            {item.reason === 'lesson_wrong' && <LessonsWrong />}
            {item.ticket_key !== null && (
                <Thread item={item} ticketKey={item.ticket_key} asks={asks} onReplied={onReplied} />
            )}
            {item.chore !== null && <ChoreThread name={item.chore} />}
            {item.pr !== null && <PullRequestLimits url={item.pr} />}
            {command !== null && <RunCommand command={command} />}
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
    return <Head item={item} done={done} links={asks !== 'pull-request'} />
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
 * What the item says: its reason, subject, and age, an action beside them, and its detail, or a `body` in its place,
 * with any notice below. Its detail's URLs and runs are linked unless `links` is false.
 */
function Head({
    item,
    done,
    action,
    notice,
    body,
    links = true,
}: {
    item: AttentionItem
    done: boolean
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
                    You answered it. The item leaves at the next tick, when the loop reads your reply.
                </p>
            )}
            {notice}
        </div>
    )
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
    return <span className="font-mono text-xs">{item.subject}</span>
}

function NothingToAnswer() {
    return <Empty>nothing to answer here: it leaves when its cause is gone</Empty>
}

/** An item whose fix is a command for the operator to run, such as `repo_missing`'s: the command, to copy. */
function RunCommand({ command }: { command: string }) {
    return (
        <div className="flex flex-col items-start gap-2 p-3" data-testid="attention-command">
            <Copyable
                text={command}
                label="command"
                className="rounded-sm bg-surface-raised px-2 py-1 font-mono text-xs"
            >
                {command}
            </Copyable>
            <p className="text-xs text-muted-foreground">
                Nothing to answer here: run it, and the item leaves when its cause is gone.
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
 * A ticket's item under its head: what its reason asks first (a broken run's row and any grant it is stuck at, or the
 * PR's link out), then the ticket's answer (`TicketAnswer`): its conversation, the reply form (`ReplyForm`), and the
 * ticket's verbs and any other grant as a quiet row under them. On a reason that asks for nothing else, the verbs lead
 * instead, as what the item asks for.
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
