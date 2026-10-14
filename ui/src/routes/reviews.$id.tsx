import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { reviewQuery } from '@/api/queries'
import type { ReviewDetail } from '@/api/types'
import { Age } from '@/components/age'
import { Copyable } from '@/components/copy-button'
import { Field, Fields } from '@/components/fields'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { FindingCard, ReviewDiffPanels } from '@/components/review-diff'
import { RichText } from '@/components/rich-text'
import { ReviewLink } from '@/components/review-link'
import { ListRow } from '@/components/rows'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TrackerLink } from '@/components/tracker-link'
import { findingAnchor, placeFindings, SEVERITY_TEXT, shortSha, verdictText } from '@/lib/reviews'
import { RUN_TEXT } from '@/lib/run-state'
import { tickId } from '@/lib/ticks'
import { cn } from '@/lib/utils'

/** One review run: its fields, its findings, and the diff with each finding on the line it names. */
export const Route = createFileRoute('/reviews/$id')({
    component: ReviewPage,
})

function ReviewPage() {
    const { id } = Route.useParams()
    // A review run's id is a positive number, as a run's is.
    const parsed = tickId(id)
    if (parsed === null) {
        return <NoReview title={`review ${id}`}>not a review: its id is a positive number</NoReview>
    }
    return <Loaded id={parsed} />
}

function Loaded({ id }: { id: number }) {
    const { data, error } = useQuery(reviewQuery(id))
    if (error instanceof ApiError && error.status === 404) {
        return <NoReview title={`review ${id}`}>{error.message}</NoReview>
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={`review ${id}`} />
                <Panel>
                    <PanelSkeleton rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    const placed = placeFindings(data.findings, data.diff !== null)
    return (
        <>
            <PageHeader title={`review ${data.review.id}`}>
                canopy&apos;s adversarial read of one commit of a PR, kept here and posted nowhere: its findings sit on
                the diff, at the lines they name.
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <ReviewPanel detail={data} />
                {data.findings.length > 0 && <FindingsPanel detail={data} />}
                {placed.elsewhere.length > 0 && data.diff !== null && (
                    <Panel>
                        <PanelHeader label="Not in the diff" />
                        <div className="flex flex-col gap-2 p-3">
                            {placed.elsewhere.map((f) => (
                                <FindingCard key={f.n} run={data.review.id} numbered={f} />
                            ))}
                        </div>
                    </Panel>
                )}
                {data.diff === null ? (
                    <Panel>
                        <PanelHeader label="Diff" />
                        <Empty>
                            no diff kept for this review: it is older than kept diffs, or its base could not be read
                        </Empty>
                        {placed.elsewhere.length > 0 && (
                            <div className="flex flex-col gap-2 border-t p-3">
                                {placed.elsewhere.map((f) => (
                                    <FindingCard key={f.n} run={data.review.id} numbered={f} />
                                ))}
                            </div>
                        )}
                    </Panel>
                ) : (
                    <ReviewDiffPanels run={data.review.id} diff={data.diff} placed={placed} />
                )}
            </div>
        </>
    )
}

function NoReview({ title, children }: { title: string; children: string }) {
    return (
        <>
            <PageHeader title={title} />
            <Panel>
                <Empty size="panel">{children}</Empty>
            </Panel>
        </>
    )
}

function ReviewPanel({ detail }: { detail: ReviewDetail }) {
    const { review } = detail
    return (
        <Panel>
            <PanelHeader label="Review">
                <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[review.state])}>
                    <RunDot state={review.state} />
                    {review.status}
                </span>
            </PanelHeader>
            <Fields>
                <Field label="pull request" mono>
                    <TrackerLink href={review.pr_url} />
                    <PullRequestLink url={review.pr_url} className="ml-3 font-sans">
                        its page in canopy
                    </PullRequestLink>
                </Field>
                <Field label="ticket">
                    {review.ticket_key === null ? (
                        <span className="text-muted-foreground">none: a PR review.query matched</span>
                    ) : (
                        <TicketLink ticketKey={review.ticket_key} />
                    )}
                </Field>
                <Field label="commit" mono>
                    <Copyable text={review.sha} label="commit">
                        <span title={review.sha}>{shortSha(review.sha)}</span>
                    </Copyable>
                    {detail.base_branch !== null && (
                        <span className="text-muted-foreground"> against {detail.base_branch}</span>
                    )}
                </Field>
                <Field label="verdict">
                    <span className="flex items-center gap-2">
                        <span className="font-mono text-xs">{verdictText(review)}</span>
                        {review.impact !== null && <Chip word={`${review.impact} impact`} />}
                    </span>
                </Field>
                {detail.summary !== null && (
                    <Field label="summary">
                        <RichText text={detail.summary} />
                    </Field>
                )}
                {detail.note !== null && (
                    <Field label="harness">
                        <span className="text-status-failed">{detail.note}</span>
                    </Field>
                )}
                <Field label="ended" mono>
                    {review.ended_at === null ? (
                        'still reviewing'
                    ) : (
                        <span className="flex gap-1">
                            <Age at={review.ended_at} />
                            ago
                        </span>
                    )}
                </Field>
                <Field label="spent" mono>
                    {review.cost_usd === null ? 'none reported' : `$${review.cost_usd.toFixed(2)}`}
                </Field>
                {detail.runs.length > 1 && (
                    <Field label="this PR's reviews">
                        <span className="flex flex-wrap gap-x-4 gap-y-1">
                            {detail.runs.map((r) =>
                                r.id === review.id ? (
                                    <span key={r.id} className="readout text-xs">
                                        review {r.id}, {shortSha(r.sha)}
                                    </span>
                                ) : (
                                    <span key={r.id} className="readout text-xs text-muted-foreground">
                                        <ReviewLink id={r.id} />, {shortSha(r.sha)}, {verdictText(r)}
                                    </span>
                                ),
                            )}
                        </span>
                    </Field>
                )}
            </Fields>
        </Panel>
    )
}

/** Every finding in one list, each linking to its card on the diff. */
function FindingsPanel({ detail }: { detail: ReviewDetail }) {
    return (
        <Panel>
            <PanelHeader label="Findings">
                <span className="readout text-xs text-muted-foreground">{detail.findings.length}</span>
            </PanelHeader>
            <ol className="divide-y">
                {detail.findings.map((f, i) => (
                    <ListRow key={i} kind="review-finding" className="py-2 text-sm">
                        <span className="readout text-xs text-muted-foreground">{i + 1}</span>
                        <Chip className={cn('justify-center', SEVERITY_TEXT[f.severity])}>{f.severity}</Chip>
                        <span className="flex min-w-0 items-center gap-3">
                            {/* A router link, not a bare `#` href, which the page's <base> would send to the root. */}
                            <Link
                                to="/reviews/$id"
                                params={{ id: String(detail.review.id) }}
                                hash={findingAnchor(i + 1)}
                                className="min-w-0 truncate text-accent underline-offset-4 hover:underline"
                            >
                                {f.title}
                            </Link>
                            {f.dismissed && <Chip>dismissed</Chip>}
                        </span>
                        <span className="font-mono text-xs text-muted-foreground">
                            {f.line === null ? (f.file === null ? 'not in the diff' : 'on its file') : 'on the diff'}
                        </span>
                    </ListRow>
                ))}
            </ol>
        </Panel>
    )
}
