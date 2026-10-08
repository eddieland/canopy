import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { attentionQuery, runsQuery, ticketQuery } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { Age } from '@/components/age'
import { Conversation } from '@/components/conversation'
import { Counters } from '@/components/counters'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { ReplyForm } from '@/components/reply-form'
import { Chip, RunDot } from '@/components/status'
import { TicketActions } from '@/components/ticket-actions'
import { TicketLink } from '@/components/ticket-link'
import { Skeleton } from '@/components/ui/skeleton'
import { bySeverity, severity, type Severity } from '@/lib/attention'
import { cn } from '@/lib/utils'

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
                        <Placeholder className="min-h-40">Nothing needs you.</Placeholder>
                    </Panel>
                    <Workers />
                </>
            ) : (
                <div className="flex flex-wrap items-start gap-6">
                    <div className="flex max-w-md min-w-0 flex-[1_1_22rem] flex-col gap-6">
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
                                <ul className="flex flex-col gap-0.5 p-1.5">
                                    {items.map((item) => (
                                        <Row key={item.id} item={item} selected={item.id === selected?.id} />
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
                            <Detail key={selected.id} item={selected} />
                        )}
                    </div>
                </div>
            )}
        </>
    )
}

function Row({ item, selected }: { item: AttentionItem; selected: boolean }) {
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

/** The selected item: its ticket's conversation and the reply form, or for an item about no ticket, what it says. */
function Detail({ item }: { item: AttentionItem }) {
    return (
        <Panel data-testid="attention-detail">
            <div className="flex flex-col gap-2 border-b p-3">
                <div className="flex flex-wrap items-center gap-2">
                    <ReasonChip item={item} />
                    {item.ticket_key !== null ? (
                        <TicketLink ticketKey={item.ticket_key} />
                    ) : (
                        <span className="font-mono text-xs">{item.subject}</span>
                    )}
                    <Age at={item.since} className="ml-auto" />
                </div>
                <p className="text-sm break-words whitespace-pre-wrap">{item.detail}</p>
            </div>
            {item.ticket_key !== null ? (
                <Thread ticketKey={item.ticket_key} />
            ) : (
                <Placeholder className="min-h-24">
                    Nothing to answer here: it leaves when its cause is gone.
                </Placeholder>
            )}
        </Panel>
    )
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
                    {ticket.phase ?? 'not seen by a tick yet'} · {messages.length}
                </span>
            </PanelHeader>
            {messages.length === 0 ? (
                <Placeholder className="min-h-20">no messages yet</Placeholder>
            ) : (
                <Conversation messages={messages} waiting={ticket.awaiting} />
            )}
            <ReplyForm key={ticket.key} ticketKey={ticket.key} waiting={ticket.awaiting} isPublic={!ticket.private} />
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
                <ul className="divide-y">
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
