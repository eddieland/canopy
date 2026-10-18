import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { GitPullRequest } from 'lucide-react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { pullRequestQuery } from '@/api/queries'
import type { PullRequestDetail } from '@/api/types'
import { Age } from '@/components/age'
import { CostTotalRow } from '@/components/cost-total'
import { Copyable } from '@/components/copy-button'
import { Decisions } from '@/components/decisions'
import { Field, Fields } from '@/components/fields'
import { GrantLimits } from '@/components/grant-limits'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll } from '@/components/panel'
import { ReviewRequestStatus } from '@/components/review-request'
import { ReviewThreads } from '@/components/review-threads'
import { ReviewsTable } from '@/components/reviews-table'
import { RunsTable } from '@/components/runs-table'
import { Chip } from '@/components/status'
import { TicketField } from '@/components/ticket-field'
import { LinkOutButton } from '@/components/ticket-links'
import { pullRequestDescription } from '@/lib/descriptions'
import { addressOf, onGitHub } from '@/lib/links'
import { ordered, useListOrder } from '@/lib/list-order'
import { pullRequestLabel } from '@/lib/pull-request-label'

interface PullRequestSearch {
    url?: string | undefined
}

// What every PR's page shows, on its title's hover: its description is the PR's state.
const HELP =
    'What canopy knows of this PR: its ticket when it has one, its review threads and the replies drafted to them, ' +
    "canopy's reviews of it, the runs that pushed to it, and the decisions naming it."

/**
 * One PR: what it is, its review threads with the replies its runs drafted, canopy's reviews of it, the runs that
 * pushed to it, and the decisions naming it.
 */
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
    const query = useQuery(pullRequestQuery(url))
    const { data, error } = query
    const title = pullRequestLabel(url)
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
        return <Missing title={title}>{error.message}</Missing>
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={title} />
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
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
                <Empty size="panel">{children}</Empty>
            </Panel>
        </>
    )
}

function PullRequestView({ detail, title }: { detail: PullRequestDetail; title: string }) {
    const { pull_request: pr, review_limit: reviewLimit, runs, reviews, decisions, cost } = detail
    const runsOrder = useListOrder('pr-runs')
    const reviewsOrder = useListOrder('pr-reviews')
    const decisionsOrder = useListOrder('pr-decisions')
    return (
        <>
            <PageHeader
                title={title}
                // Its own title, as its worker reported it, else its ticket's: the ticket's still shows below.
                subject={pr.title ?? pr.ticket_title}
                help={HELP}
                chips={pr.phase ? <Chip word={pr.phase} /> : undefined}
                // The PR on its host, as a ticket's page shows its links out: the title names it, so this says where it
                // goes.
                links={
                    <nav aria-label="Links out" className="mt-2 flex flex-wrap gap-2">
                        <LinkOutButton
                            href={pr.url}
                            label={onGitHub(pr.url) ? 'on GitHub' : addressOf(pr.url)}
                            icon={GitPullRequest}
                            hint="The PR"
                        />
                    </nav>
                }
            >
                {pullRequestDescription(pr, reviews.length)}
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <Panel>
                    <PanelHeader label="Pull request">
                        <span className="text-xs text-muted-foreground">
                            active <Age at={pr.active_at} variant="ago" />
                        </span>
                    </PanelHeader>
                    <Fields>
                        <TicketField ticketKey={pr.ticket_key} title={pr.ticket_title} />
                        {pr.repo && (
                            <Field label="repository" mono>
                                {pr.repo}
                            </Field>
                        )}
                        {pr.branch && (
                            <Field label="branch" mono>
                                <Copyable text={pr.branch} label="branch" />
                            </Field>
                        )}
                        <CostTotalRow cost={cost} />
                    </Fields>
                    {/* The PR's actions: stopping the operator's review request, and a grant of another review
                        when it is at its review limit. */}
                    <ReviewRequestStatus url={pr.url} request={pr.review_request} className="border-t" />
                    {reviewLimit !== null && (
                        <GrantLimits
                            limits={[reviewLimit]}
                            ticketKey={pr.ticket_key}
                            ownPr={pr.url}
                            className="border-t"
                        />
                    )}
                </Panel>
                {/* Its threads, which the drafts_waiting item opens, when canopy has read them or holds a draft: the
                    detail says so up front, so the page reserves their place before they arrive. */}
                {detail.threads && <ReviewThreads url={pr.url} />}
                <Panel data-testid="pull-request-reviews">
                    <PanelHeader label="Reviews">
                        <span className="flex items-center gap-2">
                            {reviews.length > 1 && <OrderToggle list="pr-reviews" />}
                            <span className="readout text-xs text-muted-foreground">{reviews.length}</span>
                        </span>
                    </PanelHeader>
                    {reviews.length === 0 ? (
                        <Empty>no reviews yet: canopy has not reviewed it</Empty>
                    ) : (
                        <ReviewsTable reviews={ordered('pr-reviews', reviewsOrder, reviews)} pr={false} />
                    )}
                </Panel>
                <Panel data-testid="pull-request-runs">
                    <PanelHeader label="Runs">
                        <span className="flex items-center gap-2">
                            {runs.length > 1 && <OrderToggle list="pr-runs" />}
                            <span className="readout text-xs text-muted-foreground">{runs.length}</span>
                        </span>
                    </PanelHeader>
                    {runs.length === 0 ? (
                        <Empty>no runs yet: none of its ticket&apos;s runs has pushed to it</Empty>
                    ) : (
                        <PanelScroll label="Runs">
                            <RunsTable runs={ordered('pr-runs', runsOrder, runs)} ticket={false} ownPr={pr.url} />
                        </PanelScroll>
                    )}
                </Panel>
                <Panel data-testid="pull-request-decisions">
                    <PanelHeader label="Decisions">
                        <span className="flex items-center gap-2">
                            {decisions.length > 1 && <OrderToggle list="pr-decisions" />}
                            <span className="readout text-xs text-muted-foreground">{decisions.length}</span>
                        </span>
                    </PanelHeader>
                    {decisions.length === 0 ? (
                        <Empty>no decisions yet: no tick has named it</Empty>
                    ) : (
                        <PanelScroll label="Decisions">
                            <Decisions
                                decisions={ordered('pr-decisions', decisionsOrder, decisions)}
                                byTick
                                ownPr={pr.url}
                            />
                        </PanelScroll>
                    )}
                </Panel>
            </div>
        </>
    )
}
