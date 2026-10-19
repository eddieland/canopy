import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { reviewRequestsQuery, reviewsQuery } from '@/api/queries'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { ReviewRequestForm } from '@/components/review-request'
import { ReviewsTable } from '@/components/reviews-table'
import { ordered, useListOrder } from '@/lib/list-order'

/**
 * canopy's latest review runs, newest first: the shadow PR reviews it keeps instead of posting them. A PR the operator
 * asked to have reviewed is a row from the moment they ask, waiting on a tick, until its review starts.
 */
export const Route = createFileRoute('/reviews/')({
    component: ReviewsPage,
})

function ReviewsPage() {
    const { data: runs } = useQuery(reviewsQuery)
    const { data: requested } = useQuery(reviewRequestsQuery)
    const order = useListOrder('reviews')
    // Both lists, or none: a request alone in the list would jump down once the runs arrived under it.
    const data = runs === undefined || requested === undefined ? undefined : { runs, requested }
    const count = data === undefined ? 0 : data.runs.length + data.requested.length
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
                        {count > 1 && <OrderToggle list="reviews" />}
                        <span className="readout text-xs text-muted-foreground">{data === undefined ? '' : count}</span>
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelSkeleton className="min-h-72" />
                ) : count === 0 ? (
                    <Empty size="panel">
                        no reviews yet: ask for one above, or set{' '}
                        <code className="font-mono text-xs">review.agent_prs</code> or{' '}
                        <code className="font-mono text-xs">review.query</code>, with{' '}
                        <code className="font-mono text-xs">capacity.max_reviews</code> above 0
                    </Empty>
                ) : (
                    <ReviewsTable
                        reviews={ordered('reviews', order, data.runs)}
                        requested={ordered('reviews', order, data.requested)}
                        requestedLast={order === 'oldest'}
                    />
                )}
            </Panel>
        </>
    )
}
