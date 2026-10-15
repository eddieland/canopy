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
import { Empty, PageHeader, Panel, PanelHeader, PanelScroll, PanelSkeleton } from '@/components/panel'
import { ReviewsTable } from '@/components/reviews-table'
import { RunsTable } from '@/components/runs-table'
import { Chip, Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { LinkOutButton } from '@/components/ticket-links'
import { TicketTitle } from '@/components/ticket-title'
import { addressOf, onGitHub } from '@/lib/links'
import { ordered, useListOrder } from '@/lib/list-order'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { None } from '@/components/none'
import { NO_TICKET } from '@/lib/words'

interface PullRequestSearch {
    url?: string | undefined
}

/** One PR: what it is, canopy's reviews of it, the runs that pushed to it, and the decisions naming it. */
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
    const title = pullRequestLabel(url)
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
        return <Missing title={title}>{error.message}</Missing>
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={title} />
                <Panel>
                    <PanelSkeleton rows={1} className="min-h-72" />
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
                What canopy knows of this PR: its ticket when it has one, canopy&apos;s reviews of it, the runs that
                pushed to it, and the decisions naming it.
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <Panel>
                    <PanelHeader label="Pull request">
                        <span className="text-xs text-muted-foreground">
                            active <Age at={pr.active_at} variant="ago" />
                        </span>
                    </PanelHeader>
                    <Fields>
                        <Field label="ticket" className="flex items-baseline gap-2">
                            {pr.ticket_key === null ? (
                                <None reason={NO_TICKET} />
                            ) : (
                                <>
                                    <TicketLink ticketKey={pr.ticket_key} className="shrink-0" />
                                    <TicketTitle title={pr.ticket_title} />
                                </>
                            )}
                        </Field>
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
                        {pr.phase && (
                            <Field label="phase" mono>
                                <Word word={pr.phase} />
                            </Field>
                        )}
                        <CostTotalRow cost={cost} />
                    </Fields>
                    {/* The PR's one action: a grant of another review when it is at its review limit. */}
                    {reviewLimit !== null && (
                        <GrantLimits limits={[reviewLimit]} ticketKey={pr.ticket_key} className="border-t" />
                    )}
                </Panel>
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
                            <RunsTable runs={ordered('pr-runs', runsOrder, runs)} ticket={false} />
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
                            <Decisions decisions={ordered('pr-decisions', decisionsOrder, decisions)} byTick />
                        </PanelScroll>
                    )}
                </Panel>
            </div>
        </>
    )
}
