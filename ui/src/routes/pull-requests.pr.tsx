import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { GitPullRequest } from 'lucide-react'
import type { ReactNode } from 'react'

import { LinkOutIcon } from '@/components/link-out-icon'
import { ApiError } from '@/api/client'
import { pullRequestQuery } from '@/api/queries'
import type { PullRequestDetail, ReviewSummary } from '@/api/types'
import { Age } from '@/components/age'
import { Copyable } from '@/components/copy-button'
import { Decisions } from '@/components/decisions'
import { PageHeader, Panel, PanelHeader, PanelScroll, Placeholder } from '@/components/panel'
import { ReviewLink } from '@/components/review-link'
import { RunsTable } from '@/components/runs-table'
import { Chip, RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { shortSha, verdictText } from '@/lib/reviews'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

interface PullRequestSearch {
    url?: string | undefined
}

/** One PR: what it is, the runs that pushed to it, canopy's reviews of it, and the decisions naming it. */
export const Route = createFileRoute('/pull-requests/pr')({
    // The PR is its URL, an opaque string the server checks: only an https:// one is passed on. Every key is returned,
    // undefined when invalid, so the router never keeps the raw value.
    validateSearch: (search: Record<string, unknown>): PullRequestSearch => {
        const url = search['url']
        return { url: typeof url === 'string' && url.startsWith('https://') ? url : undefined }
    },
    component: PullRequestPage,
})

function PullRequestPage() {
    const { url } = Route.useSearch()
    if (url === undefined) {
        return <Missing title="No PR named">open a PR from the pull requests list</Missing>
    }
    return <Loaded url={url} />
}

function Loaded({ url }: { url: string }) {
    const { data, error } = useQuery(pullRequestQuery(url))
    const title = url.replace(/^https:\/\//u, '')
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
        return <Missing title={title}>{error.message}</Missing>
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={title} />
                <Panel className="min-h-72 p-3">
                    <Skeleton className="h-4 w-1/2" />
                </Panel>
            </>
        )
    }
    return <PullRequestView detail={data} title={title} />
}

function Missing({ title, children }: { title: string; children: ReactNode }) {
    return (
        <>
            <PageHeader title={title} />
            <Panel>
                <Placeholder className="min-h-40">{children}</Placeholder>
            </Panel>
        </>
    )
}

function PullRequestView({ detail, title }: { detail: PullRequestDetail; title: string }) {
    const { pull_request: pr, runs, reviews, decisions } = detail
    return (
        <>
            <PageHeader
                title={title}
                chips={pr.phase ? <Chip word={pr.phase} /> : undefined}
                links={<PullRequestOut url={pr.url} />}
            >
                What canopy knows of this PR: its ticket when it has one, the runs that pushed to it, canopy&apos;s
                reviews of it, and the decisions naming it.
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <Panel>
                    <PanelHeader label="Pull request">
                        <span className="flex gap-1 text-xs text-muted-foreground">
                            active <Age at={pr.active_at} /> ago
                        </span>
                    </PanelHeader>
                    <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 p-3 text-sm">
                        <dt className="panel-label self-center">ticket</dt>
                        <dd className="flex min-w-0 items-center gap-2">
                            {pr.ticket_key === null ? (
                                <span className="text-muted-foreground">none: canopy has only reviewed it</span>
                            ) : (
                                <>
                                    <TicketLink ticketKey={pr.ticket_key} className="shrink-0" />
                                    <TicketTitle title={pr.ticket_title} />
                                </>
                            )}
                        </dd>
                        {pr.repo && (
                            <>
                                <dt className="panel-label self-center">repository</dt>
                                <dd className="font-mono text-xs">{pr.repo}</dd>
                            </>
                        )}
                        {pr.branch && (
                            <>
                                <dt className="panel-label self-center">branch</dt>
                                <dd className="min-w-0 font-mono text-xs">
                                    <Copyable text={pr.branch} label="branch" />
                                </dd>
                            </>
                        )}
                        {pr.phase && (
                            <>
                                <dt className="panel-label self-center">phase</dt>
                                <dd className="font-mono text-xs">{pr.phase}</dd>
                            </>
                        )}
                    </dl>
                </Panel>
                <Panel data-testid="pull-request-runs">
                    <PanelHeader label="Runs">
                        <span className="readout text-xs text-muted-foreground">{runs.length}</span>
                    </PanelHeader>
                    {runs.length === 0 ? (
                        <Placeholder className="min-h-20">no run has pushed to it</Placeholder>
                    ) : (
                        <PanelScroll label="Runs">
                            <RunsTable runs={runs} ticket={false} />
                        </PanelScroll>
                    )}
                </Panel>
                <Panel data-testid="pull-request-reviews">
                    <PanelHeader label="Reviews">
                        <span className="readout text-xs text-muted-foreground">{reviews.length}</span>
                    </PanelHeader>
                    {reviews.length === 0 ? (
                        <Placeholder className="min-h-20">canopy has not reviewed it</Placeholder>
                    ) : (
                        <ul className="divide-y">
                            {reviews.map((review) => (
                                <ReviewRow key={review.id} review={review} />
                            ))}
                        </ul>
                    )}
                </Panel>
                <Panel data-testid="pull-request-decisions">
                    <PanelHeader label="Decisions">
                        <span className="readout text-xs text-muted-foreground">{decisions.length}</span>
                    </PanelHeader>
                    {decisions.length === 0 ? (
                        <Placeholder className="min-h-20">no tick has named it</Placeholder>
                    ) : (
                        <PanelScroll label="Decisions">
                            <Decisions decisions={decisions} byTick />
                        </PanelScroll>
                    )}
                </Panel>
            </div>
        </>
    )
}

/** The PR on its host, as a ticket's page shows its links out. */
function PullRequestOut({ url }: { url: string }) {
    return (
        <nav aria-label="Links out" className="mt-2 flex flex-wrap gap-2">
            <Button
                asChild
                variant="outline"
                size="sm"
                className="max-w-full gap-1.5 font-mono text-xs font-normal text-accent"
            >
                <a href={url} target="_blank" rel="noreferrer noopener" title="The PR">
                    <LinkOutIcon href={url} icon={GitPullRequest} className="size-4" />
                    <span className="truncate">{url.replace(/^https:\/\//u, '')}</span>
                </a>
            </Button>
        </nav>
    )
}

/** A review run of the PR, opening its page with its findings on its diff: verdict, commit, impact, cost, when. */
function ReviewRow({ review }: { review: ReviewSummary }) {
    return (
        <li className="flex items-center gap-3 px-3 py-2.5 text-sm" data-testid={`pull-request-review-${review.id}`}>
            <ReviewLink id={review.id} className="w-20 shrink-0" />
            <span className={cn('flex w-28 shrink-0 items-center gap-1.5 font-mono text-xs', RUN_TEXT[review.state])}>
                <RunDot state={review.state} />
                {verdictText(review)}
            </span>
            <span className="readout shrink-0 text-xs text-muted-foreground" title={review.sha}>
                at {shortSha(review.sha)}
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
