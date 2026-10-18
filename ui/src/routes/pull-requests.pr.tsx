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
import { ListPanel } from '@/components/list-panel'
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
    "canopy's reviews of it, its ticket's runs that pushed to it, and the decisions naming it."

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
                {pullRequestDescription(pr, reviewLimit)}
            </PageHeader>
            <div className="stagger flex flex-col gap-6">
                <Panel data-testid="pull-request-fields">
                    <PanelHeader label="Pull request">
                        <span className="text-xs text-muted-foreground">
                            active <Age at={pr.active_at} variant="ago" />
                        </span>
                    </PanelHeader>
                    <Fields>
                        {/* Why it has none is its description's: `canopy only reviews it`, said once. Its repository
                            is its title's (`acme/api#12`). */}
                        <TicketField ticketKey={pr.ticket_key} title={pr.ticket_title} why={false} />
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
                <ListPanel
                    label="Reviews"
                    count={reviews.length}
                    list="pr-reviews"
                    empty="no reviews yet: canopy has not reviewed it"
                    data-testid="pull-request-reviews"
                >
                    <ReviewsTable reviews={ordered('pr-reviews', reviewsOrder, reviews)} pr={false} />
                </ListPanel>
                {/* Runs are a ticket's, so a PR canopy only reviews can never have one: it has no list to show. */}
                {pr.ticket_key !== null && (
                    <ListPanel
                        label="Runs"
                        count={runs.length}
                        list="pr-runs"
                        empty="no runs yet: none of its ticket's runs has pushed to it"
                        data-testid="pull-request-runs"
                    >
                        <PanelScroll label="Runs">
                            <RunsTable runs={ordered('pr-runs', runsOrder, runs)} ticket={false} ownPr={pr.url} />
                        </PanelScroll>
                    </ListPanel>
                )}
                <ListPanel
                    label="Decisions"
                    count={decisions.length}
                    list="pr-decisions"
                    empty="no decisions yet: no tick has named it"
                    data-testid="pull-request-decisions"
                >
                    <PanelScroll label="Decisions">
                        <Decisions
                            decisions={ordered('pr-decisions', decisionsOrder, decisions)}
                            byTick
                            ownPr={pr.url}
                        />
                    </PanelScroll>
                </ListPanel>
            </div>
        </>
    )
}
