import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { ticketPlansQuery, ticketQuery } from '@/api/queries'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelLoading } from '@/components/panel'
import { TicketPlan } from '@/components/ticket-plan'

/**
 * A ticket's plan on a page of its own (docs/design/PLANNING.md §25): its newest plan in the plan editor, with its
 * comments in the margin, Approve, Ask for changes, and Skip the plan, then its earlier plans, read only. The plan
 * wants the page's width, and a page of its own is linked to and left with Back; the ticket's page has its card.
 */
export const Route = createFileRoute('/tickets/$key_/plan')({
    component: PlanPage,
})

function PlanPage() {
    const { key } = Route.useParams()
    // The ticket for its title alone; the plans are the page.
    const title = useQuery(ticketQuery(key)).data?.ticket.title
    const query = useQuery(ticketPlansQuery(key))
    const { data, error } = query
    const header = (
        <PageHeader parents={<TicketCrumb ticketKey={key} />} title="Plan" tab={`${key} plan`}>
            {title ?? ''}
        </PageHeader>
    )
    if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
        return (
            <>
                {header}
                <Panel>
                    <Notice error={error} className="p-3" />
                </Panel>
            </>
        )
    }
    if (data === undefined) {
        return (
            <>
                {header}
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return (
        <>
            {header}
            {data.needed || data.plans.length > 0 ? (
                <TicketPlan key={key} ticketKey={key} plans={data} />
            ) : (
                <Panel>
                    <Empty size="panel">
                        no plan: {key} needs none. <code className="font-mono text-xs">canopy plan {key}</code> asks for
                        one.
                    </Empty>
                </Panel>
            )}
        </>
    )
}

function TicketCrumb({ ticketKey }: { ticketKey: string }) {
    return (
        <Link to="/tickets/$key" params={{ key: ticketKey }} activeOptions={{ exact: true }}>
            {ticketKey}
        </Link>
    )
}
