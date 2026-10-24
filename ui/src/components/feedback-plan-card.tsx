import { Link } from '@tanstack/react-router'
import { ListChecks } from 'lucide-react'
import type { ComponentProps } from 'react'

import type { FeedbackPlanWritten, WaitingFeedbackPlan } from '@/api/types'
import { Panel, PanelHeader } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { feedbackPlanRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/**
 * A feedback plan that waits, or waited, on the operator (DESIGN §32), wherever a page points to it: which plan, for
 * which PRs, how many items it covers and whether its PRs moved on since it was written, with a link to each PR's page
 * at the plan, where it is read and approved by item. `plan` is null once it waits no more; `which` and `urls` then
 * still name it, from what the page knew of it, so the PR stays a link. A `plan_review` item on the attention list
 * shows it, and a ticket's page leads with it in a card (`FeedbackPlanCard`).
 */
export function FeedbackPlanWaits({
    which,
    urls,
    plan,
    className,
    ...props
}: ComponentProps<'div'> & { which: number | null; urls: readonly string[]; plan: WaitingFeedbackPlan | null }) {
    const named = which === null ? 'The feedback plan' : `Feedback plan ${which}`
    const prs = urls.length === 0 ? '' : ` for ${urls.map((url) => pullRequestLabel(url)).join(' and ')}`
    return (
        <div className={cn('flex flex-col items-start gap-2', className)} {...props}>
            {plan === null ? (
                <p className="text-sm text-muted-foreground">
                    {named}
                    {prs} waits on you no more.
                </p>
            ) : (
                <p className="text-sm">
                    {named}
                    {prs} waits on you: {plan.items} {plan.items === 1 ? 'item' : 'items'}
                    {plan.stale ? ', and its PR has moved on since it was written.' : '.'}
                </p>
            )}
            {urls.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                    {urls.map((url) => (
                        <Button asChild variant="outline" key={url}>
                            <Link to="/pull-requests/pr" search={{ url }} hash="feedback-plan">
                                <ListChecks />
                                {plan === null ? 'See it on' : 'Approve it on'} {pullRequestLabel(url)}
                            </Link>
                        </Button>
                    ))}
                </div>
            )}
        </div>
    )
}

/**
 * The card a ticket's page leads with while its feedback plan waits on the operator: the plan's reference and a chip
 * in its header, then `FeedbackPlanWaits`. `led` is the plan the page first read, which keeps the card where it is
 * once the plan is approved, saying it waits no more, rather than move the page under the operator; `plan` is the
 * ticket's waiting plan now, or null.
 */
export function FeedbackPlanCard({ led, plan }: { led: WaitingFeedbackPlan; plan: WaitingFeedbackPlan | null }) {
    const shown = plan ?? led
    return (
        <Panel data-testid="feedback-plan-card">
            <PanelHeader label="Feedback plan">
                <span className="flex items-center gap-2">
                    <span className="readout text-xs text-muted-foreground">{feedbackPlanRef(shown.id)}</span>
                    {plan === null ? <Chip>answered</Chip> : <Chip tone="blocked">waiting on you</Chip>}
                </span>
            </PanelHeader>
            <FeedbackPlanWaits which={shown.id} urls={shown.pr_urls} plan={plan} className="p-3" />
        </Panel>
    )
}

/**
 * What a `feedback-plan` run wrote, on its page: the plan's reference, opening the first PR's page at the plan, each
 * PR it covers, and where the plan stands now, so the run's page leads to where the plan is approved.
 */
export function WroteFeedbackPlan({ plan }: { plan: FeedbackPlanWritten }) {
    const first = plan.pr_urls[0]
    const ref = feedbackPlanRef(plan.id)
    return (
        <span className="flex flex-wrap items-baseline gap-x-2" data-testid="run-feedback-plan">
            {first === undefined ? (
                <span>{ref}</span>
            ) : (
                <Link
                    to="/pull-requests/pr"
                    search={{ url: first }}
                    hash="feedback-plan"
                    className="text-accent underline-offset-4 hover:underline"
                >
                    {ref}
                </Link>
            )}
            {plan.pr_urls.length > 0 && (
                <span className="flex flex-wrap items-baseline gap-x-2">
                    for
                    {plan.pr_urls.map((url) => (
                        <PullRequestLink key={url} url={url} className="text-sm" />
                    ))}
                </span>
            )}
            <span className="text-muted-foreground">{stands(plan.status)}</span>
        </span>
    )
}

// Where a plan stands, in the words its PR page's chip and the ticket's card use.
function stands(status: FeedbackPlanWritten['status']): string {
    switch (status) {
        case 'waiting': {
            return 'waiting on you'
        }
        case 'approved': {
            return 'approved'
        }
        case 'spent': {
            return 'spent'
        }
        case 'superseded': {
            return 'superseded'
        }
    }
}
