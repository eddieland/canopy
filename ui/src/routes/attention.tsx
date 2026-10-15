import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { attentionQuery, choreQuery, pullRequestQuery, ticketQuery, ticketsQuery } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { AllClear } from '@/components/all-clear'
import { Age } from '@/components/age'
import { ChoreLink } from '@/components/chore-link'
import { ChoreNotes } from '@/components/chore-notes'
import { Conversation } from '@/components/conversation'
import { Counters } from '@/components/counters'
import { useDismissFinding } from '@/components/dismiss-finding'
import { GrantLimits } from '@/components/grant-limits'
import { Notice } from '@/components/notice'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton, ThreadScroll } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReplyForm } from '@/components/reply-form'
import { InlineCode } from '@/components/rich-text'
import { Chip, Word } from '@/components/status'
import { TicketActions } from '@/components/ticket-actions'
import { TicketLink } from '@/components/ticket-link'
import { WorkingNow } from '@/components/working-now'
import { answered } from '@/lib/acknowledged'
import { bySeverity, severity } from '@/lib/attention'
import type { Severity } from '@/lib/attention'
import { settled, withLeaving } from '@/lib/leaving'
import type { Listed } from '@/lib/leaving'
import { ordered, useListOrder } from '@/lib/list-order'
import { cn } from '@/lib/utils'
import { phaseLabel, phaseWord } from '@/lib/phase'

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

// Written out so Tailwind finds them: what is broken in the failure color, what waits on the operator in theirs.
const TONE: Record<Severity, string> = {
    failed: 'border-status-failed/40 bg-status-failed/10 text-status-failed',
    waiting: 'border-status-blocked/40 bg-status-blocked/10 text-status-blocked',
    other: '',
    finding: '',
}

// How long a cleared item's row plays its exit before it is let go: `animate-leave` in src/index.css, and a little
// over, so the row is folded shut before it goes.
const LEAVE_MS = 700

function AttentionPage() {
    const { item: wanted } = Route.useSearch()
    const { data } = useQuery(attentionQuery)
    const tickets = useQuery(ticketsQuery).data
    const items = data === undefined ? undefined : bySeverity(data)
    const rows = useLeavingRows(data, items)
    // The item asked for while it is listed; else the most severe one about a ticket, which has a thread to show.
    const selected = items?.find((i) => i.id === wanted) ?? items?.find((i) => i.ticket_key !== null) ?? items?.[0]
    return (
        <>
            <PageHeader title="Attention">
                What needs you, as <code className="font-mono text-xs">canopy status</code> lists it, most severe first.
                An item leaves when its cause is gone.
            </PageHeader>
            <Counters />
            {items !== undefined && items.length === 0 ? (
                <Panel>
                    <AllClear />
                </Panel>
            ) : (
                <div className="flex flex-wrap items-start gap-6">
                    <div className="flex max-w-md min-w-0 flex-[1_1_22rem] flex-col gap-6 2xl:max-w-lg 2xl:basis-md">
                        {/* The runs working now are the rail's, on every page, so this column is the list alone. */}
                        <Panel data-testid="attention-list">
                            <PanelHeader label="Attention">
                                <span className="readout text-xs text-muted-foreground">{items?.length}</span>
                            </PanelHeader>
                            {items === undefined ? (
                                <PanelSkeleton />
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
                                            />
                                        ),
                                    )}
                                </ul>
                            )}
                        </Panel>
                    </div>
                    <div className="flex min-w-0 flex-[999_1_28rem] flex-col gap-6">
                        {selected === undefined ? (
                            <Panel>
                                <PanelSkeleton rows={1} className="min-h-72" />
                            </Panel>
                        ) : (
                            <Detail key={selected.id} item={selected} done={answered(selected, tickets)} />
                        )}
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
            <svg
                viewBox="0 0 20 20"
                className="pointer-events-none absolute top-2 right-10 size-5 overflow-visible text-accent"
            >
                <ellipse cx="10" cy="10" rx="4.5" ry="2.2" fill="currentColor" className="animate-leaf-off" />
            </svg>
        </li>
    )
}

function Row({ item, selected, done }: { item: AttentionItem; selected: boolean; done: boolean }) {
    return (
        <li>
            <Link
                to="/attention"
                search={{ item: item.id }}
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

/** What a row of the list says: the item's reason, its subject and age, and its detail. */
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
            <span className="line-clamp-2 text-sm break-words">
                <InlineCode text={item.detail} links={false} />
            </span>
        </>
    )
}

/**
 * The item's reason as a chip. A chore's finding has the agent's own id for its reason, which is journal text, so its
 * chip says `finding` and the head line names the id beside its chore.
 */
function ReasonChip({ item }: { item: AttentionItem }) {
    return item.finding ? <Chip>finding</Chip> : <Chip className={TONE[severity(item)]} word={item.reason} />
}

/** On an `awaiting_reply` item the operator has answered: it stays until a tick reads the answer. */
function Answered() {
    return <Chip className="border-status-running/40 text-status-running">answered</Chip>
}

/**
 * The selected item: the ticket's actions and a grant for each limit it is stuck at, then its conversation and the
 * reply form; a chore's notes and the form for another, and for a finding the button to dismiss it; a PR's review
 * limit and its grant, for an item about a PR no ticket owns; or for an item about none of them, what it says.
 */
function Detail({ item, done }: { item: AttentionItem; done: boolean }) {
    return (
        <Panel data-testid="attention-detail">
            {item.finding && item.chore !== null ? (
                <FindingHead item={item} chore={item.chore} done={done} />
            ) : (
                <Head item={item} done={done} />
            )}
            {item.ticket_key !== null && <Thread ticketKey={item.ticket_key} />}
            {item.chore !== null && <ChoreThread name={item.chore} />}
            {item.pr !== null && <PullRequestLimits url={item.pr} />}
            {item.ticket_key === null && item.chore === null && item.pr === null && <NothingToAnswer />}
        </Panel>
    )
}

/** What the item says: its reason, subject, and age, an action beside them, and its detail with any notice below. */
function Head({
    item,
    done,
    action,
    notice,
}: {
    item: AttentionItem
    done: boolean
    action?: ReactNode
    notice?: ReactNode
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
            <p className="text-sm break-words whitespace-pre-wrap">
                <InlineCode text={item.detail} />
            </p>
            {done && (
                <p className="text-sm text-muted-foreground" data-testid="answered-note">
                    You answered it. The item leaves at the next tick, when the loop reads your reply.
                </p>
            )}
            {notice}
        </div>
    )
}

/** A chore's finding's head: as any item's, with the button that dismisses it beside its age. */
function FindingHead({ item, chore, done }: { item: AttentionItem; chore: string; done: boolean }) {
    const { button, notice } = useDismissFinding(chore, item.reason, false)
    return <Head item={item} done={done} action={button} notice={notice} />
}

function Subject({ item }: { item: AttentionItem }) {
    if (item.ticket_key !== null) {
        return <TicketLink ticketKey={item.ticket_key} />
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

function Thread({ ticketKey }: { ticketKey: string }) {
    const { data, error } = useQuery(ticketQuery(ticketKey))
    const order = useListOrder('conversation')
    if (error instanceof ApiError) {
        return <Notice error={error} className="p-3" />
    }
    if (data === undefined) {
        return <PanelSkeleton className="min-h-60" />
    }
    const { ticket, messages } = data
    return (
        <>
            {/* The ticket's actions foot the item, as they foot a ticket page's Work panel, and what holds it up sits
                under them, before its conversation, where it is read first (DESIGN.md, the detail skeleton). */}
            <div className="border-b" data-testid="attention-actions">
                <TicketActions key={ticket.key} ticket={ticket} />
            </div>
            <GrantLimits
                key={`limits-${ticket.key}`}
                limits={data.limits}
                ticketKey={ticket.key}
                className="border-b"
            />
            <PanelHeader label="Conversation">
                <span className="flex items-center gap-2">
                    {messages.length > 1 && <OrderToggle list="conversation" />}
                    <span className="readout text-xs text-muted-foreground">
                        <Word word={phaseWord(ticket)} text={phaseLabel(ticket)} /> · {messages.length}
                    </span>
                </span>
            </PanelHeader>
            <ThreadScroll key={ticket.key} label="Conversation" end={order === 'oldest' ? 'bottom' : 'top'}>
                {/* The run working the ticket now is its newest word, so it sits at the newest end. */}
                {order === 'newest' && <WorkingNow ticketKey={ticket.key} />}
                {messages.length === 0 ? (
                    <Empty>no messages yet: what you and its workers say shows here</Empty>
                ) : (
                    <Conversation messages={ordered('conversation', order, messages)} waiting={ticket.awaiting} />
                )}
                {order === 'oldest' && <WorkingNow ticketKey={ticket.key} />}
            </ThreadScroll>
            <ReplyForm
                key={ticket.key}
                target={{ kind: 'ticket', key: ticket.key, isPublic: !ticket.private }}
                waiting={ticket.awaiting}
            />
        </>
    )
}
