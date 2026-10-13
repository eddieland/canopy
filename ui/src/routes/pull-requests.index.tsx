import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { pullRequestsQuery } from '@/api/queries'
import type { PullRequest } from '@/api/types'
import { Age } from '@/components/age'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReviewLink } from '@/components/review-link'
import { RunLink } from '@/components/run-link'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Skeleton } from '@/components/ui/skeleton'
import { verdictText } from '@/lib/reviews'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

/** Every PR the journal knows, most recent activity first, whoever's it is. */
export const Route = createFileRoute('/pull-requests/')({
    component: PullRequestsPage,
})

function PullRequestsPage() {
    const { data } = useQuery(pullRequestsQuery)
    return (
        <>
            <PageHeader title="Pull requests">
                The loop&apos;s own PRs and every PR canopy reviewed, most recent activity first. A PR&apos;s page has
                its ticket, the runs that pushed to it, canopy&apos;s reviews of it, and what the loop decided.
            </PageHeader>
            <Panel>
                <PanelHeader label="Pull requests">
                    <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                </PanelHeader>
                {data === undefined ? (
                    <div className="flex min-h-72 flex-col gap-2 p-3">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-4 w-1/2" />
                    </div>
                ) : data.length === 0 ? (
                    <Placeholder>
                        no PRs yet: none of the loop&apos;s tickets has one, and nothing was reviewed
                    </Placeholder>
                ) : (
                    <ul className="stagger divide-y" data-testid="pull-requests">
                        {data.map((pr) => (
                            <Row key={pr.url} pr={pr} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

/**
 * A PR: the PR, its ticket and title (or `no ticket`, for any PR canopy only reviews), its unit's phase, the run
 * working it now, its latest review's verdict, and its age.
 */
function Row({ pr }: { pr: PullRequest }) {
    const review = pr.latest_review
    return (
        <li className="flex items-center gap-3 px-3 py-2.5" data-testid="pull-request">
            <PullRequestLink url={pr.url} className="w-64 shrink-0 truncate" />
            {pr.ticket_key === null ? (
                <span className="font-mono text-xs text-muted-foreground">no ticket</span>
            ) : (
                <span className="flex min-w-0 items-center gap-2">
                    <TicketLink ticketKey={pr.ticket_key} className="shrink-0" />
                    <TicketTitle title={pr.ticket_title} />
                </span>
            )}
            {pr.phase && <Chip word={pr.phase} />}
            <span className="ml-auto flex shrink-0 items-center gap-4">
                <span className="flex w-20 items-center gap-1.5 font-mono text-xs" data-testid="pull-request-run">
                    {pr.running_run !== null && (
                        <>
                            <RunDot state="running" />
                            <RunLink id={pr.running_run} />
                        </>
                    )}
                </span>
                <span
                    className={cn(
                        'flex w-44 items-center gap-1.5 font-mono text-xs whitespace-nowrap',
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
                <span className="flex w-20 justify-end gap-1 text-xs text-muted-foreground">
                    <Age at={pr.active_at} />
                    ago
                </span>
            </span>
        </li>
    )
}
