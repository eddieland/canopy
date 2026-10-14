import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { reviewsQuery } from '@/api/queries'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { ReviewsTable } from '@/components/reviews-table'
import { ordered, useListOrder } from '@/lib/list-order'

/** canopy's latest review runs, newest first: the shadow PR reviews it keeps instead of posting them. */
export const Route = createFileRoute('/reviews/')({
    component: ReviewsPage,
})

function ReviewsPage() {
    const { data } = useQuery(reviewsQuery)
    const order = useListOrder('reviews')
    return (
        <>
            <PageHeader title="Reviews">
                canopy&apos;s own adversarial reviews, newest first. They are yours alone: nothing of them is on the PR,
                so this page, <code className="font-mono text-xs">canopy review show</code>, and the workers sent to fix
                their findings are the only places they are.
            </PageHeader>
            <Panel>
                <PanelHeader label="Review runs">
                    <span className="flex items-center gap-2">
                        {data !== undefined && data.length > 1 && <OrderToggle list="reviews" />}
                        <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelSkeleton className="min-h-72" />
                ) : data.length === 0 ? (
                    <Empty size="panel">
                        no reviews yet: set review.agent_prs or review.query, with capacity.max_reviews above 0
                    </Empty>
                ) : (
                    <ReviewsTable reviews={ordered('reviews', order, data)} />
                )}
            </Panel>
        </>
    )
}
