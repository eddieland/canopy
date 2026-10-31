import type { RequestedReview, ReviewSummary } from '@/api/types'
import { Age } from '@/components/age'
import { Cost } from '@/components/cost'
import { None } from '@/components/none'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReviewDraftChip } from '@/components/review-draft-chip'
import { ReviewLink } from '@/components/review-link'
import { ListRow } from '@/components/rows'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped, Tip } from '@/components/tip'
import { reviewRef } from '@/lib/refs'
import { requestGroups, shortSha, verdictText, verdictTone } from '@/lib/reviews'
import { isNew } from '@/lib/seen-reviews'
import { cn } from '@/lib/utils'
import { NO_TICKET } from '@/lib/words'

// No PR waiting on a tick: one array, as a default made in the signature would be a new one on every render.
const NONE_REQUESTED: RequestedReview[] = []

/**
 * Review runs, one row each, opening the review's page with its findings on its diff: its verdict, its id, its ticket,
 * its impact, its PR and its title, the commit it read and the persona it wrote in, cost, and when. On a PR's own page
 * (`pr={false}`) the ticket and the PR are left out, as `RunsTable` leaves out a ticket on the ticket's page. The
 * reviews page passes the PRs the operator asked to have reviewed that no review of has started yet as `requested`, a
 * row each, before the runs, or after them with `requestedLast`: what comes next is the newest end of the list. A
 * review whose result is new to the operator (src/lib/seen-reviews.ts) has a dot in the accent after its verdict, said
 * `new` on hover and to a screen reader. A review of a PR the loop does not own says where its draft stands after
 * that (`ReviewDraftChip`), so the list shows which hold a review the operator has yet to publish or submit. A request
 * the operator made in several personas has a review of each commit in each (DESIGN §31): those rows sit together
 * where the first of them is, with no rule between them, and each after the first names only its persona in the PR's
 * place, so the request reads as one entry with its reviews side by side (`requestGroups`).
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
            {requestGroups(reviews).flatMap((group) =>
                group.map((review, i) => (
                    <ReviewRow
                        key={review.id}
                        review={review}
                        pr={pr}
                        lead={i === 0 ? undefined : group[0]?.id}
                        joined={i < group.length - 1}
                    />
                )),
            )}
            {requestedLast && waiting}
        </ul>
    )
}

/**
 * A PR the operator asked to have reviewed, waiting on a tick to start its review: a hollow ring, as nothing runs for
 * it yet, then `requested`, its author where a ticket would be once canopy has read the PR (it has no ticket: canopy
 * only reviews it), its PR, which opens its page with **Stop**, and how long it has waited. It has no review id,
 * impact, commit, or cost until its review starts, and then the review's own row takes its place.
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
            <span className="flex min-w-0">
                {request.author === null ? (
                    <None reason={NO_TICKET} brief className="font-mono text-xs" />
                ) : (
                    <Tip fact="The PR's author: canopy only reviews it, so it has no ticket">
                        <span className="truncate font-mono text-xs text-muted-foreground">{request.author}</span>
                    </Tip>
                )}
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

/**
 * One review's row. `lead` is the review whose row heads its request's group, on every other row of the group, which
 * then names only its persona where the PR and commit would repeat the lead's; `joined` drops the rule under a row
 * the next of its group follows.
 */
function ReviewRow({
    review,
    pr,
    lead,
    joined = false,
}: {
    review: ReviewSummary
    pr: boolean
    lead?: number
    joined?: boolean
}) {
    const sha = (
        <Tip fact={review.sha} mono>
            <span className="readout shrink-0 text-xs text-muted-foreground">
                {pr ? '' : 'at '}
                {shortSha(review.sha)}
            </span>
        </Tip>
    )
    // A PR reviewed in several personas side by side has a row for each, told apart by this. On a narrow list it gives
    // way before the PR's name does: it is cut first, and left out where the column has no room for it.
    const persona = review.persona !== null && (
        <Tip fact="The persona it wrote in">
            <span className="readout hidden min-w-0 shrink-[999] truncate text-xs text-muted-foreground @3xl:inline">
                as {review.persona}
            </span>
        </Tip>
    )
    // What the change is, the PR's own title or its ticket's. The PR's name, commit, and persona say which review it
    // is, so the title takes only the room they leave, up to its own width: a high shrink alone would still take a
    // sliver off the PR's name, and cut it. On a list narrower than `@6xl` that room is an ellipsis or a word at best,
    // so it is left out there.
    const title = pr && review.title !== null && (
        <TicketTitle title={review.title} className="hidden max-w-max grow basis-0 @6xl:block" />
    )
    // The rest of a request's group: its PR and commit are the lead's, so its persona alone tells it apart, shown at
    // any width since nothing else does.
    const named =
        lead === undefined ? (
            <>
                {pr && <PullRequestLink url={review.pr_url} />}
                {title}
                {sha}
                {persona}
            </>
        ) : (
            <Tip fact={`Reviewed from the same request, of the same commit, as ${reviewRef(lead)}, in another persona`}>
                <span className="readout min-w-0 truncate text-xs text-muted-foreground" data-testid="sibling-persona">
                    as {review.persona ?? 'another persona'}
                </span>
            </Tip>
        )
    return (
        <ListRow
            kind={pr ? 'review' : 'own-review'}
            className={cn('text-sm', joined && 'border-b-0 pb-1', lead !== undefined && 'pt-1')}
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
                {review.draft !== null && <ReviewDraftChip status={review.draft} />}
            </span>
            <ReviewLink id={review.id} />
            {pr && (
                <span className="truncate">
                    {lead === undefined &&
                        (review.ticket_key === null ? (
                            <None reason={NO_TICKET} brief className="font-mono text-xs" />
                        ) : (
                            <TicketLink ticketKey={review.ticket_key} />
                        ))}
                </span>
            )}
            <span className="flex">{review.impact !== null && <Chip word={`${review.impact} impact`} />}</span>
            <span className="flex min-w-0 items-center gap-3">{named}</span>
            <Cost usd={review.cost_usd} className="text-right text-xs text-muted-foreground" />
            <Age variant="span" started={review.started_at} ended={review.ended_at} className="text-right" />
        </ListRow>
    )
}
