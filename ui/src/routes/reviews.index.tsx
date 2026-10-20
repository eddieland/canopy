import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { CheckCheck } from 'lucide-react'

import { reviewRequestsQuery, reviewsQuery } from '@/api/queries'
import { OrderToggle } from '@/components/order-toggle'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PullRequestFilterBar } from '@/components/pull-request-filter'
import { ReviewRequestForm } from '@/components/review-request'
import { ReviewsTable } from '@/components/reviews-table'
import { Button } from '@/components/ui/button'
import { ordered, useListOrder } from '@/lib/list-order'
import {
    countText,
    filterWords,
    prQueryOf,
    prRepoOf,
    reposOf,
    requestShown,
    reviewShown,
} from '@/lib/pull-request-filter'
import type { PullRequestFilter } from '@/lib/pull-request-filter'
import { unseenOf, useMarkSeen } from '@/lib/seen-reviews'

/**
 * canopy's latest review runs, newest first: the shadow PR reviews it keeps instead of posting them. A PR the operator
 * asked to have reviewed is a row from the moment they ask, waiting on a tick, until its review starts. `?repo=` keeps
 * the reviews of PRs in that repository, and `?q=` those whose PR, ticket, or commit holds every word. A result new to
 * the operator is marked so, as the nav counts it, until its page shows it or the header's button marks every one seen,
 * as `canopy seen` does.
 */
export const Route = createFileRoute('/reviews/')({
    // Typed search params, as the tickets page's: every key returned, undefined when the page does not offer it.
    validateSearch: (search: Record<string, unknown>): PullRequestFilter => ({
        repo: prRepoOf(search['repo']),
        q: prQueryOf(search['q']),
    }),
    component: ReviewsPage,
})

function ReviewsPage() {
    const filter = Route.useSearch()
    const { data: runs } = useQuery(reviewsQuery)
    const { data: requested } = useQuery(reviewRequestsQuery)
    const order = useListOrder('reviews')
    const unseen = unseenOf(runs)
    const seen = useMarkSeen()
    // Both lists, or none: a request alone in the list would jump down once the runs arrived under it.
    const data = runs === undefined || requested === undefined ? undefined : { runs, requested }
    const count = data === undefined ? 0 : data.runs.length + data.requested.length
    const shownRuns = data?.runs.filter((review) => reviewShown(review, filter))
    const shownRequested = data?.requested.filter((request) => requestShown(request, filter))
    const shown =
        shownRuns === undefined || shownRequested === undefined
            ? undefined
            : { runs: shownRuns, requested: shownRequested }
    const shownCount = shown === undefined ? undefined : shown.runs.length + shown.requested.length
    const filtered = filter.repo !== undefined || filter.q !== undefined
    return (
        <>
            <PageHeader title="Reviews">
                canopy&apos;s own adversarial reviews, newest first. They are yours alone: nothing of them is on the PR,
                so this page, <code className="font-mono text-xs">canopy review show</code>, and the workers sent to fix
                their findings are the only places they are.
            </PageHeader>
            <Panel>
                <PanelHeader label="Review a PR" />
                <ReviewRequestForm />
            </Panel>
            <Panel>
                <PanelHeader label="Reviews">
                    <span className="flex items-center gap-2">
                        {unseen.length > 0 && (
                            <Button
                                variant="ghost"
                                size="xs"
                                title="Mark every new review seen, as canopy seen does"
                                disabled={seen.pending}
                                onClick={() => seen.mark(unseen.map((review) => review.id))}
                            >
                                <CheckCheck />
                                {`mark ${unseen.length} seen`}
                            </Button>
                        )}
                        {shownCount !== undefined && shownCount > 1 && <OrderToggle list="reviews" />}
                        <span className="readout text-xs text-muted-foreground" data-testid="reviews-count">
                            {countText(shownCount, data === undefined ? undefined : count, filtered)}
                        </span>
                    </span>
                </PanelHeader>
                <Notice error={seen.error} className="px-3 pt-2" />
                <PullRequestFilterBar
                    to="/reviews"
                    filter={filter}
                    repos={reposOf(data?.runs ?? [], filter.repo)}
                    label="Filter reviews by PR, ticket, or commit"
                    placeholder="Filter by PR, ticket, or commit"
                />
                {data === undefined || shown === undefined ? (
                    <PanelSkeleton className="min-h-72" />
                ) : count === 0 ? (
                    <Empty size="panel">
                        no reviews yet: ask for one above, or set{' '}
                        <code className="font-mono text-xs">review.agent_prs</code> or{' '}
                        <code className="font-mono text-xs">review.query</code>, with{' '}
                        <code className="font-mono text-xs">capacity.max_reviews</code> above 0
                    </Empty>
                ) : shownCount === 0 ? (
                    <Empty size="panel">{`no reviews${filterWords(filter)}`}</Empty>
                ) : (
                    <ReviewsTable
                        reviews={ordered('reviews', order, shown.runs)}
                        requested={ordered('reviews', order, shown.requested)}
                        requestedLast={order === 'oldest'}
                    />
                )}
            </Panel>
        </>
    )
}
