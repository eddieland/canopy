import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check, FileText, Undo2 } from 'lucide-react'
import { useState } from 'react'

import { decidePlan, refreshTicket } from '@/api/mutations'
import type { PlanChanged, TicketPlans } from '@/api/types'
import { Age } from '@/components/age'
import { Field, Fields } from '@/components/fields'
import { LinkedText } from '@/components/linked-text'
import { None } from '@/components/none'
import { Notice } from '@/components/notice'
import { Panel, PanelFooter, PanelHeader } from '@/components/panel'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { planText } from '@/lib/outcomes'
import { planApprovable, planNeededWhy, planWaits, planWaived, triageWord } from '@/lib/plan-state'
import { planRef } from '@/lib/refs'

/**
 * A ticket's plan in brief (docs/design/PLANNING.md §25): where the plan stands, which plan it is, the run that wrote
 * it and when, how many comments are open, Approve while it can be approved, and the link to the plan's own page, where
 * it is read, edited, commented on, and sent back. A ticket that had a triage before its plan shows it too: its run,
 * what it judged, and why, and while its waiver is in force and its implement has not started, Ask for a plan, which
 * undoes the waiver as `canopy plan KEY` does. A ticket's page shows it, and so does a `plan_review` item on the
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
    const decide = useMutation({
        mutationFn: (action: PlanChanged['action']) => decidePlan(ticketKey, action),
        onSuccess: (changed) => {
            setSaid(planText(ticketKey, changed))
            void refreshTicket(client, ticketKey)
        },
    })
    const newest = plans.newest?.plan
    const open = plans.threads.filter((thread) => !thread.resolved).length
    const approvable = planApprovable(plans)
    const { triage } = plans
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
                {triage !== null && (
                    <Field label="triage" mono>
                        <RunLink id={triage.run_id} /> {triageWord(triage)}{' '}
                        <span className="text-muted-foreground">
                            <Age at={triage.at} variant="ago" />
                        </span>
                    </Field>
                )}
                {triage !== null && triage.status !== 'running' && triage.reason !== null && (
                    <Field label="triage said">
                        <LinkedText text={triage.reason} />
                    </Field>
                )}
            </Fields>
            <PanelFooter>
                <div className="flex flex-wrap items-center gap-2">
                    {approvable && (
                        <Button
                            onClick={() => decide.mutate('approve')}
                            disabled={decide.isPending}
                            title="Approve the plan as its file stands, as canopy plan --approve does"
                        >
                            <Check />
                            Approve
                        </Button>
                    )}
                    {/* The one primary is Approve while there is one; the rest step back. */}
                    {triage?.undoable === true && (
                        <Button
                            variant="outline"
                            onClick={() => decide.mutate('request')}
                            disabled={decide.isPending}
                            title="Undo the triage's waiver: plan the ticket first, as canopy plan does"
                        >
                            <Undo2 />
                            Ask for a plan
                        </Button>
                    )}
                    <Button asChild variant="outline">
                        <Link to="/tickets/$key/plan" params={{ key: ticketKey }}>
                            <FileText />
                            Open plan
                        </Link>
                    </Button>
                    <span className="text-xs text-muted-foreground">{cardNote(plans, open)}</span>
                </div>
                <Notice error={decide.error} reserve>
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
 * needs one, or `waived` while a triage's waiver is in force, and why (its own setting, the waiver, or `policy.plan`)
 * on hover.
 */
export function PlanChip({ plans }: { plans: TicketPlans }) {
    const newest = plans.newest?.plan
    if (newest === undefined) {
        const word = planWaived(plans) ? 'waived' : plans.needed ? 'needed' : 'not needed'
        return (
            <span title={planNeededWhy(plans)} className="inline-flex">
                <Chip>{word}</Chip>
            </span>
        )
    }
    if (planWaits(plans)) {
        return <Chip tone="blocked">waiting on you</Chip>
    }
    // A proposed plan the operator asked to change waits on the planner now, not on them: said so, not `proposed`.
    if (newest.status === 'proposed' && plans.planning === null && plans.changes_asked !== null) {
        return <Chip>changes asked</Chip>
    }
    return <Chip>{newest.status}</Chip>
}

// What comes next for the plan, in a line beside its actions: a planner or a triage at work, a waiver in force, a
// request the planner has yet to read, or what the operator's word on it does.
function cardNote(plans: TicketPlans, open: number): string {
    if (plans.planning !== null) {
        return `Run ${plans.planning} is writing a new plan.`
    }
    if (plans.changes_asked !== null) {
        return 'You asked for changes: the next tick asks the planner for a new plan.'
    }
    if (plans.newest === null && plans.triage?.status === 'running') {
        return `Run ${plans.triage.run_id} is judging whether it needs a plan at all.`
    }
    if (plans.newest === null && plans.triage?.waived === true) {
        return plans.triage.undoable
            ? 'Triage waived its plan: the next tick can implement it unplanned. Asking for a plan undoes that.'
            : 'Triage waived its plan, and its implement went ahead unplanned.'
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
