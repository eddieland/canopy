import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check, FileText } from 'lucide-react'
import { useState } from 'react'

import { decidePlan, refreshTicket } from '@/api/mutations'
import type { TicketPlans } from '@/api/types'
import { Age } from '@/components/age'
import { Field, Fields } from '@/components/fields'
import { None } from '@/components/none'
import { Notice } from '@/components/notice'
import { Panel, PanelFooter, PanelHeader } from '@/components/panel'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { planText } from '@/lib/outcomes'
import { planApprovable, planNeededWhy, planWaits } from '@/lib/plan-state'
import { planRef } from '@/lib/refs'

/**
 * A ticket's plan in brief (docs/design/PLANNING.md §25): where the plan stands, which plan it is, the run that wrote
 * it and when, how many comments are open, Approve while it can be approved, and the link to the plan's own page, where
 * it is read, edited, commented on, and sent back. A ticket's page shows it, and so does a `plan_review` item on the
 * attention list, `bare` there: its parts without a panel of their own, inside the item's. It imports no editor, so
 * neither page loads one.
 */
export function PlanCard({
    ticketKey,
    plans,
    bare = false,
}: {
    ticketKey: string
    plans: TicketPlans
    bare?: boolean
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const approve = useMutation({
        mutationFn: () => decidePlan(ticketKey, 'approve'),
        onSuccess: (changed) => {
            setSaid(planText(ticketKey, changed))
            void refreshTicket(client, ticketKey)
        },
    })
    const newest = plans.newest?.plan
    const open = plans.threads.filter((thread) => !thread.resolved).length
    const approvable = planApprovable(plans)
    const parts = (
        <>
            <PanelHeader label="Plan">
                <span className="flex items-center gap-2">
                    {newest !== undefined && (
                        <span className="readout text-xs text-muted-foreground">{planRef(newest.id)}</span>
                    )}
                    <PlanChip plans={plans} />
                </span>
            </PanelHeader>
            <Fields>
                <Field label="written by" mono>
                    {newest === undefined ? (
                        <None />
                    ) : (
                        <>
                            <RunLink id={newest.run_id} />{' '}
                            <span className="text-muted-foreground">
                                <Age at={newest.created_at} variant="ago" />
                            </span>
                        </>
                    )}
                </Field>
                <Field label="open comments" mono>
                    {open}
                </Field>
            </Fields>
            <PanelFooter>
                <div className="flex flex-wrap items-center gap-2">
                    {approvable && (
                        <Button
                            onClick={() => approve.mutate()}
                            disabled={approve.isPending}
                            title="Approve the plan as its file stands, as canopy plan --approve does"
                        >
                            <Check />
                            Approve
                        </Button>
                    )}
                    {/* The one primary is Approve while there is one; reading the plan is the quieter way in. */}
                    <Button asChild variant="outline">
                        <Link to="/tickets/$key/plan" params={{ key: ticketKey }}>
                            <FileText />
                            Open plan
                        </Link>
                    </Button>
                    <span className="text-xs text-muted-foreground">{cardNote(plans, open)}</span>
                </div>
                <Notice error={approve.error} reserve>
                    {said}
                </Notice>
            </PanelFooter>
        </>
    )
    return bare ? (
        <div className="border-b" data-testid="plan-card">
            {parts}
        </div>
    ) : (
        <Panel data-testid="plan-card">{parts}</Panel>
    )
}

/**
 * Where a ticket's plan stands, in words, as a chip: `waiting on you` in the blocked tone while its newest plan waits
 * on the operator, as everything that waits on them reads; else its status. With no plan at all, whether the ticket
 * needs one, and why (its own setting or `policy.plan`) on hover.
 */
export function PlanChip({ plans }: { plans: TicketPlans }) {
    const newest = plans.newest?.plan
    if (newest === undefined) {
        return (
            <span title={planNeededWhy(plans)} className="inline-flex">
                <Chip>{plans.needed ? 'needed' : 'not needed'}</Chip>
            </span>
        )
    }
    return planWaits(plans) ? <Chip tone="blocked">waiting on you</Chip> : <Chip>{newest.status}</Chip>
}

// What comes next for the plan, in a line beside its actions: a planner at work, a request it has yet to read, or what
// the operator's word on it does.
function cardNote(plans: TicketPlans, open: number): string {
    if (plans.planning !== null) {
        return `Run ${plans.planning} is writing a new plan.`
    }
    if (plans.changes_asked !== null) {
        return 'You asked for changes: the next tick asks the planner for a new plan.'
    }
    if (plans.newest === null) {
        return plans.needed ? 'None yet: the next tick dispatches a planner.' : 'No plan yet.'
    }
    if (!planApprovable(plans)) {
        return 'Read it and its earlier plans on its page.'
    }
    if (open > 0) {
        const comments = open === 1 ? 'comment' : 'comments'
        return `${open} open ${comments}: approving sends none. Open the plan to ask for changes.`
    }
    return 'Approving takes it as its file stands and lets its implement go ahead.'
}
