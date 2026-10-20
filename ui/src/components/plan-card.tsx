import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check, FileText, MessageSquareReply } from 'lucide-react'
import { useState } from 'react'

import { decidePlan, refreshTicket } from '@/api/mutations'
import type { PlanChanged, TicketPlans } from '@/api/types'
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
import { cn } from '@/lib/utils'

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
    const note = cardNote(plans, open)
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
            <ChangesAsked plans={plans} className="mx-3 mb-3" />
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
                    <Button asChild variant="outline">
                        <Link to="/tickets/$key/plan" params={{ key: ticketKey }}>
                            <FileText />
                            Open plan
                        </Link>
                    </Button>
                    {note !== null && <span className="text-xs text-muted-foreground">{note}</span>}
                </div>
                <Notice error={decide.error}>{said}</Notice>
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
 * on the operator, as everything that waits on them reads; `changes asked` in the running tone while a proposed plan
 * waits on the planner for the changes the operator asked; else its status. With no plan at all, whether the ticket
 * needs one, and why (its own setting or `policy.plan`) on hover.
 */
export function PlanChip({ plans }: { plans: TicketPlans }) {
    const newest = plans.newest?.plan
    if (newest === undefined) {
        const word = plans.needed ? 'needed' : 'not needed'
        return (
            <span title={planNeededWhy(plans)} className="inline-flex">
                <Chip>{word}</Chip>
            </span>
        )
    }
    if (planWaits(plans)) {
        return <Chip tone="blocked">waiting on you</Chip>
    }
    return changesAsked(plans) && newest.status === 'proposed' ? (
        <Chip tone="running">changes asked</Chip>
    ) : (
        <Chip>{newest.status}</Chip>
    )
}

/**
 * The band that says the operator asked for changes no planner has read yet, and when: until the next tick sends the
 * planner back, the plan's word is the loop's, not theirs. It heads the plan's page and sits in its card, in the
 * running tone, since the loop acts on it next, and leaves once a planner starts.
 */
export function ChangesAsked({ plans, className }: { plans: TicketPlans; className?: string }) {
    if (!changesAsked(plans)) {
        return null
    }
    return (
        <section
            aria-label="Changes asked"
            data-testid="changes-asked"
            className={cn(
                'flex items-start gap-3 rounded-md border px-3 py-2',
                'border-status-running/40 bg-status-running/8',
                className,
            )}
        >
            <MessageSquareReply aria-hidden className="mt-0.5 size-4 shrink-0 text-status-running" />
            <p className="text-sm break-words">
                <span className="font-medium text-status-running">
                    You asked for changes{' '}
                    <Age at={plans.changes_asked} variant="ago" className="text-sm text-status-running" />:
                </span>{' '}
                the next tick asks the planner for a new plan.
            </p>
        </section>
    )
}

// Whether the operator asked for changes that no planner has started on yet. A ticket whose plan was put aside and that
// needs none now has no planner coming to read them, so it is not.
function changesAsked(plans: TicketPlans): plans is TicketPlans & { changes_asked: string } {
    const needless = plans.newest?.plan.status === 'superseded' && !plans.needed
    return plans.changes_asked !== null && plans.planning === null && !needless
}

// What comes next for the plan, in a line beside its actions: a planner at work, or what the operator's word on it
// does. Nothing while changes asked wait on a planner, which the card's band says.
function cardNote(plans: TicketPlans, open: number): string | null {
    if (plans.planning !== null) {
        return `Run ${plans.planning} is writing a new plan.`
    }
    if (changesAsked(plans)) {
        return null
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
