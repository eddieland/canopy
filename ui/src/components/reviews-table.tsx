import type { ReviewSummary } from '@/api/types'
import { Age } from '@/components/age'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReviewLink } from '@/components/review-link'
import { ListRow } from '@/components/rows'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { shortSha, verdictText } from '@/lib/reviews'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

/**
 * Review runs, one row each, opening the review's page with its findings on its diff: its verdict, its ticket and PR,
 * the commit it read, its impact, cost, and when. On a PR's own page (`pr={false}`) the ticket and the PR are left
 * out, as `RunsTable` leaves out a ticket on the ticket's page.
 */
export function ReviewsTable({ reviews, pr = true }: { reviews: ReviewSummary[]; pr?: boolean }) {
    return (
        <ul className="stagger divide-y" data-testid="reviews">
            {reviews.map((review) => (
                <ReviewRow key={review.id} review={review} pr={pr} />
            ))}
        </ul>
    )
}

function ReviewRow({ review, pr }: { review: ReviewSummary; pr: boolean }) {
    const sha = (
        <span className="readout shrink-0 text-xs text-muted-foreground" title={review.sha}>
            {pr ? '' : 'at '}
            {shortSha(review.sha)}
        </span>
    )
    return (
        <ListRow
            kind={pr ? 'review' : 'own-review'}
            className="text-sm"
            data-testid={pr ? `review-${review.id}` : `pull-request-review-${review.id}`}
        >
            <ReviewLink id={review.id} />
            <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[review.state])}>
                <RunDot state={review.state} />
                {verdictText(review)}
            </span>
            {pr ? (
                <>
                    <span className="truncate">
                        {review.ticket_key === null ? (
                            <Chip>review.query</Chip>
                        ) : (
                            <TicketLink ticketKey={review.ticket_key} />
                        )}
                    </span>
                    <span className="flex min-w-0 items-center gap-3">
                        <PullRequestLink url={review.pr_url} />
                        {sha}
                    </span>
                </>
            ) : (
                sha
            )}
            <span className="flex justify-end">
                {review.impact !== null && <Chip word={`${review.impact} impact`} />}
            </span>
            <span className="readout text-right text-xs text-muted-foreground">
                {review.cost_usd === null ? '' : `$${review.cost_usd.toFixed(2)}`}
            </span>
            <span className="flex justify-end gap-1 text-xs text-muted-foreground">
                <Age at={review.ended_at ?? review.started_at} />
                ago
            </span>
        </ListRow>
    )
}
