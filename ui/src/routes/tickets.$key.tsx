import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'

import { ApiError } from '@/api/client'
import { ticketQuery } from '@/api/queries'
import type { TicketDetail } from '@/api/types'
import { Conversation } from '@/components/conversation'
import { Decisions } from '@/components/decisions'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { ReplyForm } from '@/components/reply-form'
import { RunsTable } from '@/components/runs-table'
import { StartTicket } from '@/components/start-ticket'
import { TicketActions } from '@/components/ticket-actions'
import { Skeleton } from '@/components/ui/skeleton'
import { age, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'
import { phaseLabel } from '@/lib/phase'

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
                <PageHeader label="Ticket" title={key} />
                <Panel>
                    <Placeholder className="min-h-40">{error.message}</Placeholder>
                </Panel>
            </>
        )
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader label="Ticket" title={key} />
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
    const how = ticket.private
        ? `Private, ${ticket.start ?? 'started'}. Its conversation stays in canopy; nothing reaches the ticket.`
        : 'Public: its queue label authorizes it. Its conversation is on the ticket, and copied here.'
    return (
        <>
            <PageHeader label={ticket.private ? 'Private ticket' : 'Public ticket'} title={ticket.key}>
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
                            <span className="readout text-xs text-muted-foreground">{runs.length}</span>
                        </PanelHeader>
                        {runs.length === 0 ? (
                            <Placeholder className="min-h-20">none</Placeholder>
                        ) : (
                            <RunsTable runs={runs} ticket={false} />
                        )}
                    </Panel>
                    <Panel data-testid="ticket-decisions">
                        <PanelHeader label="Decisions">
                            <span className="readout text-xs text-muted-foreground">{decisions.length}</span>
                        </PanelHeader>
                        {decisions.length === 0 ? (
                            <Placeholder className="min-h-20">no tick has decided anything about it yet</Placeholder>
                        ) : (
                            <Decisions decisions={decisions} byTick />
                        )}
                    </Panel>
                </div>
                <Panel>
                    <PanelHeader label="Conversation">
                        <span className="readout text-xs text-muted-foreground">{messages.length}</span>
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
    return (
        <>
            <PageHeader label="Ticket" title={ticketKey}>
                canopy has no record of it. Start it to work it privately.
            </PageHeader>
            <Panel>
                <PanelHeader label="Start a ticket" />
                <StartTicket />
            </Panel>
        </>
    )
}
