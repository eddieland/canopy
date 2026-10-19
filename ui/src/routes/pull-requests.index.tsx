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
import { verdictText, verdictTone } from '@/lib/reviews'
import { cn } from '@/lib/utils'
import { None } from '@/components/none'
import { NO_TICKET } from '@/lib/words'

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
                The loop&apos;s own PRs, every PR canopy reviewed, and every PR you asked it to review, most recent
                activity first. A PR&apos;s page has its ticket, the runs that pushed to it, canopy&apos;s reviews of
                it, and what the loop decided.
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
                    <ul className="divide-y" data-testid="pull-requests">
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
 * A PR: where it stands, the PR (`org/repo#123` for GitHub's), its unit's phase, its ticket (or `none`, why on hover,
 * for any PR canopy only reviews) and title, and its age. The title is the PR's own once a worker reports it, else its
 * ticket's.
 * Where it stands is the run working it, while one does, then its latest review's verdict and whether the operator's
 * review request on it is open.
 */
function Row({ pr }: { pr: PullRequest }) {
    return (
        <ListRow kind="pull-request" data-testid="pull-request">
            <State pr={pr} />
            <PullRequestLink url={pr.url} />
            <span className="flex">{pr.phase && <Chip word={pr.phase} className="min-w-0 shrink" />}</span>
            <span className="flex min-w-0 items-center gap-2">
                {pr.ticket_key === null ? (
                    <None reason={NO_TICKET} brief className="shrink-0 font-mono text-xs" />
                ) : (
                    <TicketLink ticketKey={pr.ticket_key} className="shrink-0" />
                )}
                {(pr.ticket_key !== null || pr.title !== null) && <TicketTitle title={pr.title ?? pr.ticket_title} />}
            </span>
            <Age at={pr.active_at} variant="ago" className="text-right" />
        </ListRow>
    )
}

/**
 * Where a PR stands, leading its row as a run's state does: while a run works it, the running dot and that run, then
 * its latest review and that review's verdict (the dot how the review's run ended, the verdict's color its worst
 * finding), or `not reviewed`, and `requested` while the operator's review request on it is open.
 */
function State({ pr }: { pr: PullRequest }) {
    const review = pr.latest_review
    return (
        <span
            className={cn(
                'flex min-w-0 items-center gap-1.5 font-mono text-xs whitespace-nowrap',
                review ? verdictTone(review) : 'text-muted-foreground',
            )}
            data-testid="pull-request-review"
        >
            {pr.running_run !== null && (
                <span className="flex items-center gap-1.5 pr-1.5" data-testid="pull-request-run">
                    <RunDot state="running" />
                    <RunLink id={pr.running_run} />
                </span>
            )}
            {review ? (
                <>
                    {pr.running_run === null && <RunDot state={review.state} />}
                    <ReviewLink id={review.id} />
                    <span className="truncate" title={verdictText(review)}>
                        {verdictText(review)}
                    </span>
                </>
            ) : (
                'not reviewed'
            )}
            {pr.review_request !== null && pr.review_request.ended_at === null && <Chip>requested</Chip>}
        </span>
    )
}
