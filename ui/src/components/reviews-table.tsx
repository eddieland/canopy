import type { ReviewSummary } from '@/api/types'
import { Age } from '@/components/age'
import { Cost } from '@/components/cost'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReviewLink } from '@/components/review-link'
import { ListRow } from '@/components/rows'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { shortSha, verdictText, verdictTone } from '@/lib/reviews'
import { cn } from '@/lib/utils'
import { None } from '@/components/none'
import { NO_TICKET } from '@/lib/words'

/**
 * Review runs, one row each, opening the review's page with its findings on its diff: its verdict, its id, its ticket,
 * its impact, its PR and the commit it read, cost, and when. On a PR's own page (`pr={false}`) the ticket and the PR
 * are left out, as `RunsTable` leaves out a ticket on the ticket's page.
 */
export function ReviewsTable({ reviews, pr = true }: { reviews: ReviewSummary[]; pr?: boolean }) {
    return (
        <ul className="divide-y" data-testid="reviews">
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
            {/* The dot is how its run ended; the verdict's color, its worst finding. */}
            <span className={cn('flex min-w-0 items-center gap-1.5 font-mono text-xs', verdictTone(review))}>
                <RunDot state={review.state} />
                <span className="truncate" title={verdictText(review)}>
                    {verdictText(review)}
                </span>
            </span>
            <ReviewLink id={review.id} />
            {pr && (
                <span className="truncate">
                    {review.ticket_key === null ? (
                        <None reason={NO_TICKET} brief className="font-mono text-xs" />
                    ) : (
                        <TicketLink ticketKey={review.ticket_key} />
                    )}
                </span>
            )}
            <span className="flex">{review.impact !== null && <Chip word={`${review.impact} impact`} />}</span>
            {pr ? (
                <span className="flex min-w-0 items-center gap-3">
                    <PullRequestLink url={review.pr_url} />
                    {sha}
                </span>
            ) : (
                sha
            )}
            <Cost usd={review.cost_usd} className="text-right text-xs text-muted-foreground" />
            <Age variant="span" started={review.started_at} ended={review.ended_at} className="text-right" />
        </ListRow>
    )
}
