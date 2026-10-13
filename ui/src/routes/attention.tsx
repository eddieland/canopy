import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { attentionQuery, choreQuery, runsQuery, ticketQuery, ticketsQuery } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { AllClear } from '@/components/all-clear'
import { Age } from '@/components/age'
import { ChoreLink } from '@/components/chore-link'
import { ChoreNotes } from '@/components/chore-notes'
import { Conversation } from '@/components/conversation'
import { Counters } from '@/components/counters'
import { LinkedText } from '@/components/linked-text'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { ReplyForm } from '@/components/reply-form'
import { Chip, RunDot } from '@/components/status'
import { TicketActions } from '@/components/ticket-actions'
import { TicketLink } from '@/components/ticket-link'
import { Skeleton } from '@/components/ui/skeleton'
import { answered } from '@/lib/acknowledged'
import { bySeverity, severity, type Severity } from '@/lib/attention'
import { cn } from '@/lib/utils'
import { phaseLabel } from '@/lib/phase'

interface AttentionSearch {
    item?: string | undefined
}

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
            <PageHeader label="Inbox" title="Attention">
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
                                <div className="flex flex-col gap-2 p-3">
                                    <Skeleton className="h-4 w-2/3" />
                                    <Skeleton className="h-4 w-1/2" />
                                </div>
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
                            <Panel className="min-h-72 p-3">
                                <Skeleton className="h-4 w-1/2" />
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
                    selected && 'bg-surface-raised',
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
    return <Chip className={TONE[severity(item)]}>{item.reason}</Chip>
}

/** On an `awaiting_reply` item the operator has answered: it stays until a tick reads the answer. */
function Answered() {
    return <Chip className="border-status-running/40 text-status-running">answered</Chip>
}

/**
 * The selected item: its ticket's conversation and the reply form; a chore's notes and the form for another; or for an
 * item about neither, what it says.
 */
function Detail({ item, done }: { item: AttentionItem; done: boolean }) {
    return (
        <Panel data-testid="attention-detail">
            <div className="flex flex-col gap-2 border-b p-3">
                <div className="flex flex-wrap items-center gap-2">
                    <ReasonChip item={item} />
                    {done && <Answered />}
                    <Subject item={item} />
                    <Age at={item.since} className="ml-auto" />
                </div>
                <p className="text-sm break-words whitespace-pre-wrap">
                    <LinkedText text={item.detail} />
                </p>
                {done && (
                    <p className="text-sm text-muted-foreground" data-testid="answered-note">
                        You answered it. The item leaves at the next tick, when the loop reads your reply.
                    </p>
                )}
            </div>
            {item.ticket_key !== null && <Thread ticketKey={item.ticket_key} />}
            {item.chore !== null && <ChoreThread name={item.chore} />}
            {item.ticket_key === null && item.chore === null && (
                <Placeholder className="min-h-24">
                    Nothing to answer here: it leaves when its cause is gone.
                </Placeholder>
            )}
        </Panel>
    )
}

function Subject({ item }: { item: AttentionItem }) {
    if (item.ticket_key !== null) return <TicketLink ticketKey={item.ticket_key} />
    if (item.chore !== null) return <ChoreLink name={item.chore} />
    return <span className="font-mono text-xs">{item.subject}</span>
}

/** A chore's item: the chore's notes, which its next runs read, and the form for another (DESIGN §19). */
function ChoreThread({ name }: { name: string }) {
    const { data, error } = useQuery(choreQuery(name))
    if (error instanceof ApiError) return <Placeholder className="min-h-40">{error.message}</Placeholder>
    if (data === undefined) {
        return (
            <div className="flex min-h-60 flex-col gap-2 p-3">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
            </div>
        )
    }
    return <ChoreNotes detail={data} />
}

function Thread({ ticketKey }: { ticketKey: string }) {
    const { data, error } = useQuery(ticketQuery(ticketKey))
    if (error instanceof ApiError) return <Placeholder className="min-h-40">{error.message}</Placeholder>
    if (data === undefined) {
        return (
            <div className="flex min-h-60 flex-col gap-2 p-3">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
            </div>
        )
    }
    const { ticket, messages } = data
    return (
        <>
            <PanelHeader label="Conversation">
                <span className="readout text-xs text-muted-foreground">
                    {phaseLabel(ticket)} · {messages.length}
                </span>
            </PanelHeader>
            {messages.length === 0 ? (
                <Placeholder className="min-h-20">no messages yet</Placeholder>
            ) : (
                <Conversation messages={messages} waiting={ticket.awaiting} />
            )}
            <ReplyForm
                key={ticket.key}
                target={{ kind: 'ticket', key: ticket.key, isPublic: !ticket.private }}
                waiting={ticket.awaiting}
            />
            <div className="border-t">
                <TicketActions key={ticket.key} ticket={ticket} />
            </div>
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
                <div className="p-3">
                    <Skeleton className="h-4 w-1/2" />
                </div>
            ) : running.length === 0 ? (
                <Placeholder className="min-h-16">no worker running</Placeholder>
            ) : (
                <ul className="stagger divide-y">
                    {running.map((run) => (
                        <li
                            key={run.id}
                            className="flex items-center gap-2.5 px-3 py-2"
                            data-testid={`worker-${run.id}`}
                        >
                            <RunDot state={run.state} />
                            <TicketLink ticketKey={run.ticket_key} className="w-20 truncate" />
                            <Chip>{run.kind}</Chip>
                            <span className="ml-auto flex items-center gap-3">
                                <span className="readout text-xs text-muted-foreground">
                                    {run.cost_usd === null ? '' : `$${run.cost_usd.toFixed(2)}`}
                                </span>
                                <Age at={run.started_at} className="w-8 text-right" />
                            </span>
                        </li>
                    ))}
                </ul>
            )}
        </Panel>
    )
}
