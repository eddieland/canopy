import type { RequestedReview, ReviewSummary } from '@/api/types'
import { Age } from '@/components/age'
import { Cost } from '@/components/cost'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReviewLink } from '@/components/review-link'
import { ListRow } from '@/components/rows'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Clipped, Tip } from '@/components/tip'
import { shortSha, verdictText, verdictTone } from '@/lib/reviews'
import { isNew } from '@/lib/seen-reviews'
import { cn } from '@/lib/utils'
import { None } from '@/components/none'
import { NO_TICKET } from '@/lib/words'

// No PR waiting on a tick: one array, as a default made in the signature would be a new one on every render.
const NONE_REQUESTED: RequestedReview[] = []

/**
 * Review runs, one row each, opening the review's page with its findings on its diff: its verdict, its id, its ticket,
 * its impact, its PR and the commit it read, cost, and when. On a PR's own page (`pr={false}`) the ticket and the PR
 * are left out, as `RunsTable` leaves out a ticket on the ticket's page. The reviews page passes the PRs the operator
 * asked to have reviewed that no review of has started yet as `requested`, a row each, before the runs, or after them
 * with `requestedLast`: what comes next is the newest end of the list. A review whose result is new to the operator
 * (src/lib/seen-reviews.ts) has a dot in the accent after its verdict, said `new` on hover and to a screen reader.
 */
export function ReviewsTable({
    reviews,
    requested = NONE_REQUESTED,
    requestedLast = false,
    pr = true,
}: {
    reviews: ReviewSummary[]
    requested?: RequestedReview[]
    requestedLast?: boolean
    pr?: boolean
}) {
    const waiting = requested.map((request) => <RequestedRow key={`requested-${request.pr_url}`} request={request} />)
    return (
        <ul className="divide-y" data-testid="reviews">
            {!requestedLast && waiting}
            {reviews.map((review) => (
                <ReviewRow key={review.id} review={review} pr={pr} />
            ))}
            {requestedLast && waiting}
        </ul>
    )
}

/**
 * A PR the operator asked to have reviewed, waiting on a tick to start its review: a hollow ring, as nothing runs for
 * it yet, then `requested`, its PR, which opens its page with **Stop**, and how long it has waited. It has no review
 * id, impact, commit, or cost until its review starts, and then the review's own row takes its place.
 */
function RequestedRow({ request }: { request: RequestedReview }) {
    return (
        <ListRow kind="review" className="text-sm" data-testid={`requested-${request.pr_url}`}>
            <span className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-muted-foreground">
                <span aria-hidden className="inline-flex size-2 shrink-0 rounded-full border border-muted-foreground" />
                <Tip fact="Waiting on the next tick to start its review">
                    <span>requested</span>
                </Tip>
            </span>
            <span />
            <span className="truncate">
                <None reason={NO_TICKET} brief className="font-mono text-xs" />
            </span>
            <span />
            <span className="flex min-w-0 items-center gap-3">
                <PullRequestLink url={request.pr_url} />
            </span>
            <span />
            <Age at={request.created_at} variant="ago" className="text-right" />
        </ListRow>
    )
}

function ReviewRow({ review, pr }: { review: ReviewSummary; pr: boolean }) {
    const sha = (
        <Tip fact={review.sha} mono>
            <span className="readout shrink-0 text-xs text-muted-foreground">
                {pr ? '' : 'at '}
                {shortSha(review.sha)}
            </span>
        </Tip>
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
                <Clipped text={verdictText(review)} />
                {isNew(review) && (
                    <Tip fact="new: you have not seen it yet">
                        <span className="inline-flex size-1.5 shrink-0 rounded-full bg-accent">
                            <span className="sr-only">new</span>
                        </span>
                    </Tip>
                )}
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
