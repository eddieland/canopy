import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { attentionQuery, choreQuery, pullRequestQuery, runsQuery, ticketQuery, ticketsQuery } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { AllClear } from '@/components/all-clear'
import { Age } from '@/components/age'
import { ChoreLink } from '@/components/chore-link'
import { ChoreNotes } from '@/components/chore-notes'
import { Conversation } from '@/components/conversation'
import { Counters } from '@/components/counters'
import { useDismissFinding } from '@/components/dismiss-finding'
import { GrantLimits } from '@/components/grant-limits'
import { LinkedText } from '@/components/linked-text'
import { Notice } from '@/components/notice'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { ListRow } from '@/components/rows'
import { ReplyForm } from '@/components/reply-form'
import { Chip, RunDot } from '@/components/status'
import { TicketActions } from '@/components/ticket-actions'
import { TicketLink } from '@/components/ticket-link'
import { WorkingNow } from '@/components/working-now'
import { answered } from '@/lib/acknowledged'
import { bySeverity, severity } from '@/lib/attention'
import type { Severity } from '@/lib/attention'
import { ordered, useListOrder } from '@/lib/list-order'
import { cn } from '@/lib/utils'
import { phaseLabel } from '@/lib/phase'

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

function AttentionPage() {
    const { item: wanted } = Route.useSearch()
    const { data } = useQuery(attentionQuery)
    const tickets = useQuery(ticketsQuery).data
    const items = data === undefined ? undefined : bySeverity(data)
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
                <>
                    <Panel>
                        <AllClear />
                    </Panel>
                    <Workers />
                </>
            ) : (
                <div className="flex flex-wrap items-start gap-6">
                    <div className="flex max-w-md min-w-0 flex-[1_1_22rem] flex-col gap-6 2xl:max-w-lg 2xl:basis-md">
                        <Panel data-testid="attention-list">
                            <PanelHeader label="Needs you">
                                <span className="readout text-xs text-muted-foreground">{items?.length}</span>
                            </PanelHeader>
                            {items === undefined ? (
                                <PanelSkeleton />
                            ) : (
                                <ul className="stagger flex flex-col gap-0.5 p-1.5">
                                    {items.map((item) => (
                                        <Row
                                            key={item.id}
                                            item={item}
                                            selected={item.id === selected?.id}
                                            done={answered(item, tickets)}
                                        />
                                    ))}
                                </ul>
                            )}
                        </Panel>
                        <Workers />
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
                <span className="flex items-center gap-2">
                    <ReasonChip item={item} />
                    {done && <Answered />}
                    <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{item.subject}</span>
                    <Age at={item.since} className="ml-auto" />
                </span>
                <span className="line-clamp-2 text-sm break-words">{item.detail}</span>
            </Link>
        </li>
    )
}

function ReasonChip({ item }: { item: AttentionItem }) {
    return <Chip className={TONE[severity(item)]} word={item.reason} />
}

/** On an `awaiting_reply` item the operator has answered: it stays until a tick reads the answer. */
function Answered() {
    return <Chip className="border-status-running/40 text-status-running">answered</Chip>
}

/**
 * The selected item: its ticket's conversation, the reply form, and the ticket's actions, with a grant for each limit
 * it is stuck at; a chore's notes and the form for another, and for a finding the button to dismiss it; a PR's review
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
                <LinkedText text={item.detail} />
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
        return <ChoreLink name={item.chore} />
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
            <PanelHeader label="Conversation">
                <span className="flex items-center gap-2">
                    {messages.length > 1 && <OrderToggle list="conversation" />}
                    <span className="readout text-xs text-muted-foreground">
                        {phaseLabel(ticket)} · {messages.length}
                    </span>
                </span>
            </PanelHeader>
            {/* The run working the ticket now is its newest word, so it sits at the newest end. */}
            {order === 'newest' && <WorkingNow ticketKey={ticket.key} />}
            {messages.length === 0 ? (
                <Empty>no messages yet: what you and its workers say shows here</Empty>
            ) : (
                <Conversation messages={ordered('conversation', order, messages)} waiting={ticket.awaiting} />
            )}
            {order === 'oldest' && <WorkingNow ticketKey={ticket.key} />}
            <ReplyForm
                key={ticket.key}
                target={{ kind: 'ticket', key: ticket.key, isPublic: !ticket.private }}
                waiting={ticket.awaiting}
            />
            <div className="border-t">
                <TicketActions key={ticket.key} ticket={ticket} />
            </div>
            <GrantLimits
                key={`limits-${ticket.key}`}
                limits={data.limits}
                ticketKey={ticket.key}
                className="border-t"
            />
        </>
    )
}

/** The runs working now, under the list: which ticket, what kind of run, for how long, and what it has cost so far. */
function Workers() {
    const { data } = useQuery(runsQuery)
    const running = data?.filter((r) => r.state === 'running')
    return (
        <Panel data-testid="workers">
            <PanelHeader label="Working">
                <span className="readout text-xs text-muted-foreground">{running?.length}</span>
            </PanelHeader>
            {running === undefined ? (
                <PanelSkeleton rows={1} />
            ) : running.length === 0 ? (
                <Empty>no runs working now: the overseer starts them at a tick</Empty>
            ) : (
                <ul className="stagger divide-y">
                    {running.map((run) => (
                        <ListRow key={run.id} kind="worker" className="py-2" data-testid={`worker-${run.id}`}>
                            <RunDot state={run.state} />
                            <TicketLink ticketKey={run.ticket_key} className="truncate" />
                            <span className="flex">
                                <Chip word={run.kind} />
                            </span>
                            <span className="readout text-xs text-muted-foreground">
                                {run.cost_usd === null ? '' : `$${run.cost_usd.toFixed(2)}`}
                            </span>
                            <Age at={run.started_at} className="text-right" />
                        </ListRow>
                    ))}
                </ul>
            )}
        </Panel>
    )
}
