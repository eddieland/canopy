import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Send } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { newSubmission, refreshTicket, sendReviewFindings } from '@/api/mutations'
import { reviewQuery } from '@/api/queries'
import type { ReviewDetail } from '@/api/types'
import { Age } from '@/components/age'
import { Copyable } from '@/components/copy-button'
import { Field, Fields } from '@/components/fields'
import { FoldPanel } from '@/components/fold-panel'
import { PersonaField } from '@/components/persona-field'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { Notice } from '@/components/notice'
import { FindingCard, ReviewDiffPanels } from '@/components/review-diff'
import type { Wanted } from '@/components/review-diff'
import { ReviewDraftPanel, ReviewDraftState, ReviewPointCard } from '@/components/review-draft'
import { RichText } from '@/components/rich-text'
import { ReviewLink } from '@/components/review-link'
import { ListRow } from '@/components/rows'
import { Chip } from '@/components/status'
import { TicketField } from '@/components/ticket-field'
import { PullRequestLinksOut } from '@/components/ticket-links'
import { Timestamp } from '@/components/timestamp'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { reviewDescription, reviewDraftTitle } from '@/lib/descriptions'
import { reviewSentText } from '@/lib/outcomes'
import { pullRequestLabel, pullRequestUrl } from '@/lib/pull-request-label'
import { reviewRef } from '@/lib/refs'
import { goneText } from '@/lib/retention'
import {
    findingAnchor,
    placeFindings,
    SEVERITY_TONE,
    shortSha,
    siblingsOf,
    verdictText,
    verdictTone,
} from '@/lib/reviews'
import { useSeesReview } from '@/lib/seen-reviews'
import { tickId } from '@/lib/ticks'
import { cn } from '@/lib/utils'

// What every review's page shows, on its title's hover: its description is the review's state.
const HELP =
    "canopy's adversarial read of one commit of a PR, kept here: its findings sit on the diff, at the lines they " +
    'name. On a PR the loop does not own it is also a draft of your review, which posts nothing until you publish it.'

/** Why a review has no diff, when retention did not remove it. */
const NO_DIFF = 'no diff kept for this review: it is older than kept diffs, or its base could not be read'

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
    // Its result is seen once shown here, so the nav's count of new reviews no longer counts it.
    useSeesReview(data?.review)
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
    const { draft } = data
    const follow = (file: number) => setWanted({ file })
    // The PR on its host, first found under the title, as its own page has it: the Review panel's icon may be folded.
    const links = <PullRequestLinksOut url={pullRequestUrl(data.review.pr_url) ?? data.review.pr_url} />
    return (
        <>
            {/* With a draft, the page is the draft's record: the operator's review leads, its state the line. */}
            {draft === null ? (
                <PageHeader
                    title={`${reviewRef(data.review.id)} ${pullRequestLabel(data.review.pr_url)}`}
                    subject={data.ticket_title}
                    help={HELP}
                    links={links}
                >
                    {reviewDescription(data.review)}
                </PageHeader>
            ) : (
                <PageHeader
                    title={reviewRef(data.review.id)}
                    subject={reviewDraftTitle(data.review.pr_url, draft)}
                    help={HELP}
                    links={links}
                >
                    <ReviewDraftState draft={draft} />
                </PageHeader>
            )}
            <div className="stagger flex flex-col gap-6">
                {draft === null ? (
                    <>
                        <ReviewPanel detail={data} />
                        {data.findings.length > 0 && <FindingsPanel detail={data} onFollow={follow} />}
                    </>
                ) : (
                    <>
                        <ReviewDraftPanel
                            run={data.review.id}
                            prUrl={data.review.pr_url}
                            sha={data.review.sha}
                            draft={draft}
                            findings={data.findings.length}
                            hasDiff={data.diff !== null}
                            onFollow={follow}
                            siblings={siblingsOf(data.review, data.runs)}
                        />
                        <ReviewerFold detail={data} onFollow={follow} />
                    </>
                )}
                {/* With no diff, the findings list is their cards, so each finding shows once. */}
                {data.diff === null ? (
                    <Panel>
                        <PanelHeader label="Diff" />
                        <Empty>{goneText(data.diff_removed_after_days, NO_DIFF)}</Empty>
                    </Panel>
                ) : (
                    <>
                        <ReviewDiffPanels
                            run={data.review.id}
                            diff={data.diff}
                            placed={placed}
                            draft={data.draft}
                            wanted={wanted}
                        />
                        {/* After the files, which are what the operator reads the findings against. */}
                        {placed.elsewhere.length > 0 && (
                            <Panel>
                                <PanelHeader label="Not in the diff" />
                                <div className="flex flex-col gap-2 p-3">
                                    {placed.elsewhere.map((f) =>
                                        draft === null ? (
                                            <FindingCard key={f.n} run={data.review.id} numbered={f} />
                                        ) : (
                                            <ReviewPointCard
                                                key={f.n}
                                                run={data.review.id}
                                                numbered={f}
                                                draft={draft}
                                            />
                                        ),
                                    )}
                                </div>
                            </Panel>
                        )}
                    </>
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

/**
 * The review's fields, its summary first, since what it found is what the operator came for, then why the harness
 * decided its status, its verdict, and what it read. Its status is the page's description alone, and the PR's other
 * reviews are a line under the PR, so nothing here says what the header says. How its run went, its transcript, log,
 * and spend, is the run's own page, opened from the `run` field: read now and then, not each time.
 */
function ReviewPanel({ detail }: { detail: ReviewDetail }) {
    return (
        <Panel>
            <PanelHeader label="Review" />
            <ReviewFields detail={detail} />
        </Panel>
    )
}

/**
 * On a review with a draft, what canopy's reviewer made of the PR, which the operator's draft was written from: the
 * Review panel's fields and the findings in one panel, folded under the draft, since the draft is what the page is for.
 * Its header says the review's status and verdict, which the page's description, the draft's state, leaves out.
 */
function ReviewerFold({ detail, onFollow }: { detail: ReviewDetail; onFollow: (file: number) => void }) {
    const { review } = detail
    return (
        <FoldPanel
            label="What the reviewer found"
            readout={
                <span className="readout text-xs text-muted-foreground">
                    {reviewDescription(review)} · <span className={verdictTone(review)}>{verdictText(review)}</span>
                </span>
            }
            what="the review"
            data-testid="reviewer-fold"
        >
            <ReviewFields detail={detail} />
            {detail.findings.length > 0 && (
                <section className="border-t">
                    <h3 className="flex items-center gap-2 px-3 pt-3 panel-label">
                        Findings
                        <span className="readout text-xs text-muted-foreground">{detail.findings.length}</span>
                    </h3>
                    <FindingsBody detail={detail} onFollow={onFollow} />
                </section>
            )}
        </FoldPanel>
    )
}

// The Review panel's fields, in the panel or in the reviewer's fold.
function ReviewFields({ detail }: { detail: ReviewDetail }) {
    const { review } = detail
    const others = detail.runs.filter((r) => r.id !== review.id)
    return (
        <Fields>
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
            <Field label="verdict">
                <span className="flex items-center gap-2">
                    <span className={cn('font-mono text-xs', verdictTone(review))}>{verdictText(review)}</span>
                    {review.impact !== null && <Chip word={`${review.impact} impact`} />}
                </span>
            </Field>
            <Field label="pull request" mono>
                <PullRequestLink url={review.pr_url} className="text-sm" />
                {others.length > 0 && (
                    <span className="mt-0.5 flex flex-wrap gap-x-3 text-muted-foreground" data-testid="other-reviews">
                        <span>also</span>
                        {others.map((r) => (
                            <span key={r.id} className="readout">
                                <ReviewLink id={r.id} />, <span className={verdictTone(r)}>{verdictText(r)}</span>
                            </span>
                        ))}
                    </span>
                )}
            </Field>
            <TicketField ticketKey={review.ticket_key} title={detail.ticket_title} />
            <PersonaField persona={detail.persona} digest={detail.persona_digest} />
            <Field label="commit" mono>
                <Copyable text={review.sha} label="commit">
                    <span title={review.sha}>{shortSha(review.sha)}</span>
                </Copyable>
                {detail.base_branch !== null && (
                    <span className="text-muted-foreground"> against {detail.base_branch}</span>
                )}
            </Field>
            <Field label="run" mono>
                <span className="flex flex-wrap items-baseline gap-x-2">
                    {review.ended_at === null ? (
                        'still reviewing'
                    ) : (
                        <>
                            <Timestamp at={review.ended_at} />
                            <Age at={review.ended_at} variant="ago" />
                        </>
                    )}
                    <Link
                        to="/reviews/$id/run"
                        params={{ id: String(review.id) }}
                        className="text-accent underline-offset-4 hover:underline"
                        data-testid="review-run-link"
                    >
                        transcript and log
                    </Link>
                </span>
            </Field>
        </Fields>
    )
}

/** The findings in a panel of their own, on a review with no draft. */
function FindingsPanel({ detail, onFollow }: { detail: ReviewDetail; onFollow: (file: number) => void }) {
    return (
        <Panel>
            <PanelHeader label="Findings">
                <span className="readout text-xs text-muted-foreground">{detail.findings.length}</span>
            </PanelHeader>
            <FindingsBody detail={detail} onFollow={onFollow} />
        </Panel>
    )
}

/**
 * Every finding in one list, each linking to its card on the diff; with no diff kept, the list is the cards themselves,
 * so a finding shows once. On a review of one of the loop's own PRs, each
 * finding the operator has not dismissed has a box, and the ticked ones go to a worker together, as
 * `canopy send review:ID N...`: a reply on the ticket naming them, which the next tick reads as the operator's go-ahead
 * (DESIGN §21). `onFollow` hears a link followed to a finding on a file, by the file's index in the diff.
 */
function FindingsBody({ detail, onFollow }: { detail: ReviewDetail; onFollow: (file: number) => void }) {
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

    // A finding's box, when it can go to a worker.
    const box = (n: number, dismissed: boolean) =>
        detail.sendable &&
        !dismissed && (
            <Checkbox
                aria-label={`send finding ${n} to a worker`}
                checked={picked.has(n)}
                onCheckedChange={(checked) => pick(n, checked === true)}
                data-testid={`pick-finding-${n}`}
            />
        )

    return (
        <>
            {detail.diff === null ? (
                <ol className="flex flex-col gap-2 p-3">
                    {detail.findings.map((finding, i) => (
                        <li key={i}>
                            <FindingCard
                                run={review.id}
                                numbered={{ n: i + 1, finding }}
                                pick={box(i + 1, finding.dismissed)}
                            />
                        </li>
                    ))}
                </ol>
            ) : (
                <FindingRows detail={detail} box={box} onFollow={onFollow} />
            )}
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
        </>
    )
}

/** The findings as rows, each with its box (`box`) and a link to its card on the diff, and where on it the card is. */
function FindingRows({
    detail,
    box,
    onFollow,
}: {
    detail: ReviewDetail
    box: (n: number, dismissed: boolean) => ReactNode
    onFollow: (file: number) => void
}) {
    return (
        <ol className="divide-y">
            {detail.findings.map((f, i) => (
                <ListRow key={i} kind="review-finding" className="py-2 text-sm">
                    <span className="flex items-center gap-1.5">
                        {box(i + 1, f.dismissed)}
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
    )
}
