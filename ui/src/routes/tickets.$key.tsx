import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'

import { ApiError } from '@/api/client'
import { ticketQuery } from '@/api/queries'
import type { TicketDetail } from '@/api/types'
import { Conversation } from '@/components/conversation'
import { Decisions } from '@/components/decisions'
import { OrderToggle } from '@/components/order-toggle'
import { PageHeader, Panel, PanelHeader, PanelScroll, Placeholder } from '@/components/panel'
import { ReplyForm } from '@/components/reply-form'
import { RunsTable } from '@/components/runs-table'
import { StartTicket } from '@/components/start-ticket'
import { Chip } from '@/components/status'
import { TicketActions } from '@/components/ticket-actions'
import { TicketLinks } from '@/components/ticket-links'
import { Skeleton } from '@/components/ui/skeleton'
import { WorkingNow } from '@/components/working-now'
import { useBranchUrls } from '@/hooks/use-branch-urls'
import { useTicketUrl } from '@/hooks/use-ticket-url'
import { ordered, useListOrder } from '@/lib/list-order'
import { age, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'
import { phaseLabel } from '@/lib/phase'

/** One ticket: the operator's actions on it, its work, its recent runs and decisions, and its conversation. */
export const Route = createFileRoute('/tickets/$key')({
    component: TicketPage,
})

function TicketPage() {
    const { key } = Route.useParams()
    const { data, error } = useQuery(ticketQuery(key))
    if (error instanceof ApiError && error.status === 404) return <Unknown ticketKey={key} />
    if (error instanceof ApiError && error.status === 409) {
        return (
            <>
                <PageHeader title={key} />
                <Panel>
                    <Placeholder className="min-h-40">{error.message}</Placeholder>
                </Panel>
            </>
        )
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={key} />
                <Panel className="min-h-72 p-3">
                    <Skeleton className="h-4 w-1/2" />
                </Panel>
            </>
        )
    }
    return <Ticket detail={data} />
}

function Ticket({ detail }: { detail: TicketDetail }) {
    const { ticket, units, runs, messages, decisions } = detail
    const now = useNow()
    const tracker = useTicketUrl(ticket.key)
    const branchUrl = useBranchUrls()
    const branch = ticket.branch
    const branches = units.flatMap((u) => {
        const href = branch === null ? undefined : branchUrl(u.repo, branch)
        return u.repo !== null && href !== undefined ? [{ repo: u.repo, href }] : []
    })
    const runsOrder = useListOrder('ticket-runs')
    const decisionsOrder = useListOrder('ticket-decisions')
    const conversationOrder = useListOrder('conversation')
    const how = ticket.private
        ? `Private, ${ticket.start ?? 'started'}. Its conversation stays in canopy; nothing reaches the ticket.`
        : 'Public: its queue label authorizes it. Its conversation is on the ticket, and copied here.'
    return (
        <>
            <PageHeader
                chips={<Chip>{ticket.private ? 'private' : 'public'}</Chip>}
                title={
                    ticket.title === null ? (
                        ticket.key
                    ) : (
                        // The key in its data face, quieter, so the title reads as the page's name (DESIGN §7).
                        <>
                            <span className="font-mono font-normal text-muted-foreground">{ticket.key}</span>{' '}
                            {ticket.title}
                        </>
                    )
                }
                links={<TicketLinks tracker={tracker} units={units} branches={branches} />}
            >
                {how}
            </PageHeader>
            {/* On a wide screen the conversation sits beside what the ticket is and did, as in the inbox. */}
            <div
                className={cn(
                    'flex flex-col gap-6',
                    '2xl:grid 2xl:grid-cols-[minmax(0,36rem)_minmax(0,1fr)] 2xl:items-start',
                )}
            >
                <div className="stagger flex flex-col gap-6">
                    <Panel>
                        <PanelHeader label="Actions" />
                        <TicketActions ticket={ticket} />
                    </Panel>
                    <Panel>
                        <PanelHeader label="Work">
                            <span className="readout text-xs text-muted-foreground">
                                active {age(ticket.active_at, now)} ago
                            </span>
                        </PanelHeader>
                        <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 p-3 text-sm">
                            <dt className="panel-label self-center">phase</dt>
                            <dd className="font-mono text-xs">
                                {phaseLabel(ticket)}
                                {ticket.done ? ', done' : ''}
                            </dd>
                            <dt className="panel-label self-center">branch</dt>
                            <dd className="font-mono text-xs">{ticket.branch ?? 'none yet'}</dd>
                            {units.map((unit) => (
                                <Unit key={unit.repo ?? ''} repo={unit.repo} pr={unit.pr_url} phase={unit.phase} />
                            ))}
                        </dl>
                    </Panel>
                    <Panel>
                        <PanelHeader label="Recent runs">
                            <span className="flex items-center gap-2">
                                {runs.length > 1 && <OrderToggle list="ticket-runs" />}
                                <span className="readout text-xs text-muted-foreground">{runs.length}</span>
                            </span>
                        </PanelHeader>
                        {runs.length === 0 ? (
                            <Placeholder className="min-h-20">none</Placeholder>
                        ) : (
                            <PanelScroll label="Recent runs">
                                <RunsTable runs={ordered('ticket-runs', runsOrder, runs)} ticket={false} />
                            </PanelScroll>
                        )}
                    </Panel>
                    <Panel data-testid="ticket-decisions">
                        <PanelHeader label="Decisions">
                            <span className="flex items-center gap-2">
                                {decisions.length > 1 && <OrderToggle list="ticket-decisions" />}
                                <span className="readout text-xs text-muted-foreground">{decisions.length}</span>
                            </span>
                        </PanelHeader>
                        {decisions.length === 0 ? (
                            <Placeholder className="min-h-20">no tick has decided anything about it yet</Placeholder>
                        ) : (
                            <PanelScroll label="Decisions">
                                <Decisions decisions={ordered('ticket-decisions', decisionsOrder, decisions)} byTick />
                            </PanelScroll>
                        )}
                    </Panel>
                </div>
                <Panel>
                    <PanelHeader label="Conversation">
                        <span className="flex items-center gap-2">
                            {messages.length > 1 && <OrderToggle list="conversation" />}
                            <span className="readout text-xs text-muted-foreground">{messages.length}</span>
                        </span>
                    </PanelHeader>
                    {/* The run working the ticket now is its newest word, so it sits at the newest end. */}
                    {conversationOrder === 'newest' && <WorkingNow ticketKey={ticket.key} />}
                    {messages.length === 0 ? (
                        <Placeholder className="min-h-20">no messages yet</Placeholder>
                    ) : (
                        <Conversation
                            messages={ordered('conversation', conversationOrder, messages)}
                            waiting={ticket.awaiting}
                        />
                    )}
                    {conversationOrder === 'oldest' && <WorkingNow ticketKey={ticket.key} />}
                    <ReplyForm
                        key={ticket.key}
                        target={{ kind: 'ticket', key: ticket.key, isPublic: !ticket.private }}
                        waiting={ticket.awaiting}
                    />
                </Panel>
            </div>
        </>
    )
}

function Unit({ repo, pr, phase }: { repo: string | null; pr: string | null; phase: string | null }) {
    return (
        <>
            <dt className="panel-label self-center">{repo ? `PR in ${repo}` : 'PR'}</dt>
            <dd className="flex items-center gap-3 font-mono text-xs">
                {pr ? (
                    <a
                        href={pr}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="inline-flex items-center gap-1 text-accent underline-offset-4 hover:underline"
                    >
                        {pr.replace(/^https:\/\//, '')}
                        <ExternalLink className="size-3" />
                    </a>
                ) : (
                    'none recorded'
                )}
                {phase && <span className="text-muted-foreground">{phase}</span>}
            </dd>
        </>
    )
}

function Unknown({ ticketKey }: { ticketKey: string }) {
    const tracker = useTicketUrl(ticketKey)
    return (
        <>
            <PageHeader title={ticketKey} links={<TicketLinks tracker={tracker} />}>
                canopy has no record of it. Start it to work it privately.
            </PageHeader>
            <Panel>
                <PanelHeader label="Start a ticket" />
                <StartTicket />
            </Panel>
        </>
    )
}
