import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ticketsQuery } from '@/api/queries'
import type { TicketSummary } from '@/api/types'
import { Age } from '@/components/age'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { ListRow } from '@/components/rows'
import { StartTicket } from '@/components/start-ticket'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { ordered, useListOrder } from '@/lib/list-order'
import { phaseLabel } from '@/lib/phase'

/** Every ticket canopy has worked or been asked to, most recent activity first, and a form to start one. */
export const Route = createFileRoute('/tickets/')({
    component: TicketsPage,
})

function TicketsPage() {
    const { data } = useQuery(ticketsQuery)
    const order = useListOrder('tickets')
    return (
        <>
            <PageHeader title="Tickets">
                Every ticket canopy has worked or been asked to, most recent activity first.
            </PageHeader>
            <Panel>
                <PanelHeader label="Start a ticket" />
                <StartTicket />
            </Panel>
            <Panel>
                <PanelHeader label="Tickets">
                    <span className="flex items-center gap-2">
                        {data !== undefined && data.length > 1 && <OrderToggle list="tickets" />}
                        <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelSkeleton className="min-h-72" />
                ) : data.length === 0 ? (
                    <Empty size="panel">
                        no tickets yet: start one above, or give one the queue label in the tracker
                    </Empty>
                ) : (
                    <ul className="divide-y" data-testid="tickets">
                        {ordered('tickets', order, data).map((ticket) => (
                            <Row key={ticket.key} ticket={ticket} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

function Row({ ticket }: { ticket: TicketSummary }) {
    const phase = `${phaseLabel(ticket)}${ticket.done ? ', done' : ''}`
    return (
        <ListRow kind="ticket" data-testid={`ticket-${ticket.key}`}>
            <TicketLink ticketKey={ticket.key} className="truncate" />
            <TicketTitle title={ticket.title} />
            <span className="flex">
                <Chip>{ticket.private ? `private, ${ticket.start ?? ''}` : 'public'}</Chip>
            </span>
            <span className="truncate font-mono text-xs text-muted-foreground" title={phase}>
                {phase}
            </span>
            <span className="flex flex-col gap-0.5 whitespace-nowrap">
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
            </span>
            <Age at={ticket.active_at} className="text-right" />
        </ListRow>
    )
}
