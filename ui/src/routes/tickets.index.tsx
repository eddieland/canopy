import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ticketsQuery } from '@/api/queries'
import type { TicketSummary } from '@/api/types'
import { Age } from '@/components/age'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { StartTicket } from '@/components/start-ticket'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Skeleton } from '@/components/ui/skeleton'
import { phaseLabel } from '@/lib/phase'

export const Route = createFileRoute('/tickets/')({
    component: TicketsPage,
})

function TicketsPage() {
    const { data } = useQuery(ticketsQuery)
    return (
        <>
            <PageHeader label="Conversations" title="Tickets">
                Every ticket canopy has worked or been asked to, most recent activity first.
            </PageHeader>
            <Panel>
                <PanelHeader label="Start a ticket" />
                <StartTicket />
            </Panel>
            <Panel>
                <PanelHeader label="Tickets">
                    <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                </PanelHeader>
                {data === undefined ? (
                    <div className="flex min-h-72 flex-col gap-2 p-3">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-4 w-1/2" />
                    </div>
                ) : data.length === 0 ? (
                    <Placeholder>no tickets yet</Placeholder>
                ) : (
                    <ul className="divide-y" data-testid="tickets">
                        {data.map((ticket) => (
                            <Row key={ticket.key} ticket={ticket} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

function Row({ ticket }: { ticket: TicketSummary }) {
    return (
        <li className="flex items-center gap-3 px-3 py-2.5" data-testid={`ticket-${ticket.key}`}>
            <TicketLink ticketKey={ticket.key} className="w-24 shrink-0 truncate" />
            <span className="min-w-0 flex-1 truncate text-sm" title={ticket.title ?? undefined}>
                {ticket.title}
            </span>
            <span className="flex w-32">
                <Chip>{ticket.private ? `private, ${ticket.start ?? ''}` : 'public'}</Chip>
            </span>
            <span className="font-mono text-xs text-muted-foreground">
                {phaseLabel(ticket)}
                {ticket.done ? ', done' : ''}
            </span>
            <span className="flex items-center gap-4">
                {ticket.running_run !== null && (
                    <span className="flex items-center gap-1.5 font-mono text-xs text-status-running">
                        <RunDot state="running" />
                        run:{ticket.running_run}
                    </span>
                )}
                {ticket.awaiting !== null && (
                    <span className="flex items-center gap-1.5 font-mono text-xs text-status-blocked">
                        <RunDot state="blocked" />
                        waiting on you
                    </span>
                )}
                <Age at={ticket.active_at} className="w-10 text-right" />
            </span>
        </li>
    )
}
