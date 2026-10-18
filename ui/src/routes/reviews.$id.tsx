import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Send } from 'lucide-react'
import { useState } from 'react'

import { ApiError } from '@/api/client'
import { newSubmission, refreshTicket, sendReviewFindings } from '@/api/mutations'
import { reviewQuery } from '@/api/queries'
import type { ReviewDetail } from '@/api/types'
import { Age } from '@/components/age'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { Field, Fields } from '@/components/fields'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { Notice } from '@/components/notice'
import { FindingCard, ReviewDiffPanels } from '@/components/review-diff'
import type { Wanted } from '@/components/review-diff'
import { RichText } from '@/components/rich-text'
import { ReviewLink } from '@/components/review-link'
import { ListRow } from '@/components/rows'
import { Chip, RunDot, Word } from '@/components/status'
import { TicketField } from '@/components/ticket-field'
import { Timestamp } from '@/components/timestamp'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { reviewDescription } from '@/lib/descriptions'
import { reviewSentText } from '@/lib/outcomes'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { reviewRef } from '@/lib/refs'
import { findingAnchor, placeFindings, SEVERITY_TONE, shortSha, verdictText, verdictTone } from '@/lib/reviews'
import { RUN_TEXT } from '@/lib/run-state'
import { tickId } from '@/lib/ticks'
import { cn } from '@/lib/utils'

// What every review's page shows, on its title's hover: its description is the review's state.
const HELP =
    "canopy's adversarial read of one commit of a PR, kept here and posted nowhere: its findings sit on the diff, at " +
    'the lines they name.'

/** One review run: its fields, its findings, and the diff with each finding on the line it names. */
export const Route = createFileRoute('/reviews/$id')({
    component: ReviewPage,
})

function ReviewPage() {
    const { id } = Route.useParams()
    // A review run's id is a positive number, as a run's is.
    const parsed = tickId(id)
    if (parsed === null) {
        return <NoReview title={reviewRef(id)}>not a review: its id is a positive number</NoReview>
    }
    return <Loaded id={parsed} />
}

function Loaded({ id }: { id: number }) {
    const query = useQuery(reviewQuery(id))
    // The file of the finding whose link the operator last followed, a new object each time, so the diff shows it.
    const [wanted, setWanted] = useState<Wanted | null>(null)
    const { data, error } = query
    if (error instanceof ApiError && error.status === 404) {
        return <NoReview title={reviewRef(id)}>{error.message}</NoReview>
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={reviewRef(id)} />
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    const placed = placeFindings(data.findings, data.diff !== null)
    return (
        <>
            <PageHeader
                title={`${reviewRef(data.review.id)} ${pullRequestLabel(data.review.pr_url)}`}
                subject={data.ticket_title}
                help={HELP}
            >
                {reviewDescription(data.review)}
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <ReviewPanel detail={data} />
                {data.findings.length > 0 && <FindingsPanel detail={data} onFollow={(file) => setWanted({ file })} />}
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
                    <ReviewDiffPanels run={data.review.id} diff={data.diff} placed={placed} wanted={wanted} />
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
                    <Word word={review.status} />
                </span>
            </PanelHeader>
            <Fields>
                <Field label="pull request" mono>
                    <PullRequestLink url={review.pr_url} className="text-sm" />
                </Field>
                <TicketField ticketKey={review.ticket_key} title={detail.ticket_title} />
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
                        <span className={cn('font-mono text-xs', verdictTone(review))}>{verdictText(review)}</span>
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
                        <span className="flex items-baseline gap-2">
                            <Timestamp at={review.ended_at} />
                            <Age at={review.ended_at} variant="ago" />
                        </span>
                    )}
                </Field>
                <Field label="spent" mono>
                    <Cost usd={review.cost_usd} />
                </Field>
                {detail.runs.length > 1 && (
                    <Field label="this PR's reviews">
                        <span className="flex flex-wrap gap-x-4 gap-y-1">
                            {detail.runs.map((r) =>
                                r.id === review.id ? (
                                    <span key={r.id} className="readout text-xs">
                                        {reviewRef(r.id)}, {shortSha(r.sha)}
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

/**
 * Every finding in one list, each linking to its card on the diff. On a review of one of the loop's own PRs, each
 * finding the operator has not dismissed has a box, and the ticked ones go to a worker together, as
 * `canopy send review:ID N...`: a reply on the ticket naming them, which the next tick reads as the operator's go-ahead
 * (DESIGN §21). `onFollow` hears a link followed to a finding on a file, by the file's index in the diff.
 */
function FindingsPanel({ detail, onFollow }: { detail: ReviewDetail; onFollow: (file: number) => void }) {
    const { review } = detail
    const client = useQueryClient()
    const [picked, setPicked] = useState<ReadonlySet<number>>(new Set())
    // Drawn anew whenever the findings picked change, so a retry of the same ones records nothing new (DESIGN §22).
    const [submission, setSubmission] = useState(newSubmission)
    const [said, setSaid] = useState<string | null>(null)
    const send = useMutation({
        mutationFn: (findings: number[]) => sendReviewFindings(review.id, findings, submission),
        onSuccess: (sent) => {
            setSaid(reviewSentText(sent))
            setPicked(new Set())
            setSubmission(newSubmission())
            void refreshTicket(client, sent.ticket_key)
        },
    })

    function pick(n: number, on: boolean) {
        const next = new Set(picked)
        if (on) {
            next.add(n)
        } else {
            next.delete(n)
        }
        setPicked(next)
        setSubmission(newSubmission())
    }

    return (
        <Panel>
            <PanelHeader label="Findings">
                <span className="readout text-xs text-muted-foreground">{detail.findings.length}</span>
            </PanelHeader>
            <ol className="divide-y">
                {detail.findings.map((f, i) => (
                    <ListRow key={i} kind="review-finding" className="py-2 text-sm">
                        <span className="flex items-center gap-1.5">
                            {detail.sendable && !f.dismissed && (
                                <Checkbox
                                    aria-label={`send finding ${i + 1} to a worker`}
                                    checked={picked.has(i + 1)}
                                    onCheckedChange={(checked) => pick(i + 1, checked === true)}
                                    data-testid={`pick-finding-${i + 1}`}
                                />
                            )}
                            <span className="readout text-xs text-muted-foreground">{i + 1}</span>
                        </span>
                        <Chip tone={SEVERITY_TONE[f.severity]} className="justify-center">
                            {f.severity}
                        </Chip>
                        <span className="flex min-w-0 items-center gap-3">
                            {/* A router link, not a bare `#` href, which the page's <base> would send to the root. */}
                            <Link
                                to="/reviews/$id"
                                params={{ id: String(detail.review.id) }}
                                hash={findingAnchor(i + 1)}
                                onClick={() => {
                                    if (f.file !== null) {
                                        onFollow(f.file)
                                    }
                                }}
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
            {detail.sendable && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t p-3">
                    <Button
                        size="sm"
                        onClick={() => send.mutate([...picked].toSorted((a, b) => a - b))}
                        disabled={picked.size === 0 || send.isPending}
                        title="Reply on the ticket naming the ticked findings: the next tick reads it as your go-ahead"
                        data-testid="send-findings"
                    >
                        <Send />
                        send to a worker
                    </Button>
                    {said === null && send.error === null ? (
                        <span className="text-xs text-muted-foreground">
                            tick the findings a worker on {review.ticket_key} should address; it leaves the rest alone
                        </span>
                    ) : (
                        <Notice error={send.error}>{said}</Notice>
                    )}
                </div>
            )}
        </Panel>
    )
}
