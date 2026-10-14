import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { pullRequestsQuery } from '@/api/queries'
import type { PullRequest } from '@/api/types'
import { Age } from '@/components/age'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReviewLink } from '@/components/review-link'
import { ListRow } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { ordered, useListOrder } from '@/lib/list-order'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { verdictText } from '@/lib/reviews'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

/** Every PR the journal knows, most recent activity first, whoever's it is. */
export const Route = createFileRoute('/pull-requests/')({
    component: PullRequestsPage,
})

function PullRequestsPage() {
    const { data } = useQuery(pullRequestsQuery)
    const order = useListOrder('pull-requests')
    return (
        <>
            <PageHeader title="Pull requests">
                The loop&apos;s own PRs and every PR canopy reviewed, most recent activity first. A PR&apos;s page has
                its ticket, the runs that pushed to it, canopy&apos;s reviews of it, and what the loop decided.
            </PageHeader>
            <Panel>
                <PanelHeader label="Pull requests">
                    <span className="flex items-center gap-2">
                        {data !== undefined && data.length > 1 && <OrderToggle list="pull-requests" />}
                        <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelSkeleton className="min-h-72" />
                ) : data.length === 0 ? (
                    <Empty size="panel">
                        no PRs yet: none of the loop&apos;s tickets has one, and nothing was reviewed
                    </Empty>
                ) : (
                    <ul className="stagger divide-y" data-testid="pull-requests">
                        {ordered('pull-requests', order, data).map((pr) => (
                            <Row key={pr.url} pr={pr} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

/**
 * A PR: the PR (`org/repo#123` for GitHub's), its ticket and title (or `no ticket`, for any PR canopy only reviews),
 * its unit's phase, the run working it now, its latest review's verdict, and its age.
 */
function Row({ pr }: { pr: PullRequest }) {
    const review = pr.latest_review
    return (
        <ListRow kind="pull-request" data-testid="pull-request">
            <PullRequestLink url={pr.url} className="truncate">
                {pullRequestLabel(pr.url)}
            </PullRequestLink>
            <span className="flex min-w-0 items-center gap-3">
                {pr.ticket_key === null ? (
                    <span className="font-mono text-xs text-muted-foreground">no ticket</span>
                ) : (
                    <span className="flex min-w-0 items-center gap-2">
                        <TicketLink ticketKey={pr.ticket_key} className="shrink-0" />
                        <TicketTitle title={pr.ticket_title} />
                    </span>
                )}
                {pr.phase && <Chip word={pr.phase} />}
            </span>
            <span className="flex items-center gap-1.5 font-mono text-xs" data-testid="pull-request-run">
                {pr.running_run !== null && (
                    <>
                        <RunDot state="running" />
                        <RunLink id={pr.running_run} />
                    </>
                )}
            </span>
            <span
                className={cn(
                    'flex items-center gap-1.5 font-mono text-xs whitespace-nowrap',
                    review ? RUN_TEXT[review.state] : 'text-muted-foreground',
                )}
                data-testid="pull-request-review"
            >
                {review ? (
                    <>
                        <RunDot state={review.state} />
                        <ReviewLink id={review.id} />
                        {verdictText(review)}
                    </>
                ) : (
                    'not reviewed'
                )}
            </span>
            <span className="flex justify-end gap-1 text-xs text-muted-foreground">
                <Age at={pr.active_at} />
                ago
            </span>
        </ListRow>
    )
}
