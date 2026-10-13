import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { reviewsQuery } from '@/api/queries'
import type { ReviewSummary } from '@/api/types'
import { Age } from '@/components/age'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { ReviewLink } from '@/components/review-link'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TrackerLink } from '@/components/tracker-link'
import { Skeleton } from '@/components/ui/skeleton'
import { shortSha, verdictText } from '@/lib/reviews'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

/** canopy's latest review runs, newest first: the shadow PR reviews it keeps instead of posting them. */
export const Route = createFileRoute('/reviews/')({
    component: ReviewsPage,
})

function ReviewsPage() {
    const { data } = useQuery(reviewsQuery)
    return (
        <>
            <PageHeader label="Reviews" title="Reviews">
                canopy's own adversarial reviews, newest first. They are yours alone: nothing of them is on the PR, so
                this page, <code className="font-mono text-xs">canopy review show</code>, and the workers sent to fix
                their findings are the only places they are.
            </PageHeader>
            <Panel>
                <PanelHeader label="Review runs">
                    <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                </PanelHeader>
                {data === undefined ? (
                    <div className="flex min-h-72 flex-col gap-2 p-3">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-4 w-1/2" />
                    </div>
                ) : data.length === 0 ? (
                    <Placeholder>no reviews yet</Placeholder>
                ) : (
                    <ul className="stagger divide-y" data-testid="reviews">
                        {data.map((review) => (
                            <Row key={review.id} review={review} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

function Row({ review }: { review: ReviewSummary }) {
    return (
        <li className="flex items-center gap-3 px-3 py-2.5 text-sm" data-testid={`review-${review.id}`}>
            <ReviewLink id={review.id} className="w-20 shrink-0" />
            <span className={cn('flex w-28 shrink-0 items-center gap-1.5 font-mono text-xs', RUN_TEXT[review.state])}>
                <RunDot state={review.state} />
                {verdictText(review)}
            </span>
            <span className="w-24 shrink-0">
                {review.ticket_key === null ? <Chip>review.query</Chip> : <TicketLink ticketKey={review.ticket_key} />}
            </span>
            <TrackerLink href={review.pr_url} className="min-w-0 truncate font-mono text-xs" />
            <span className="readout shrink-0 text-xs text-muted-foreground" title={review.sha}>
                {shortSha(review.sha)}
            </span>
            <span className="ml-auto flex shrink-0 items-center gap-4">
                {review.impact !== null && <Chip word={`${review.impact} impact`} />}
                <span className="readout w-14 text-right text-xs text-muted-foreground">
                    {review.cost_usd === null ? '' : `$${review.cost_usd.toFixed(2)}`}
                </span>
                <span className="flex w-20 justify-end gap-1 text-xs text-muted-foreground">
                    <Age at={review.ended_at ?? review.started_at} />
                    ago
                </span>
            </span>
        </li>
    )
}
