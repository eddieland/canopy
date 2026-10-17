import { Link } from '@tanstack/react-router'
import { FileText } from 'lucide-react'

import type { TicketPlans } from '@/api/types'
import { Age } from '@/components/age'
import { Field, Fields } from '@/components/fields'
import { None } from '@/components/none'
import { Panel, PanelHeader } from '@/components/panel'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { planRef } from '@/lib/refs'

/**
 * A ticket's plan on its page, in brief (docs/design/PLANNING.md §25): where the plan stands, which plan it is, the run
 * that wrote it and when, how many comments are open, and the link to the plan's own page, where it is read, edited,
 * and decided. Nothing here edits or decides it, so the ticket's page never loads the plan editor.
 */
export function PlanCard({ ticketKey, plans }: { ticketKey: string; plans: TicketPlans }) {
    const newest = plans.newest?.plan
    const waiting = newest?.status === 'proposed' && plans.planning === null
    const open = plans.threads.filter((thread) => !thread.resolved).length
    return (
        <Panel data-testid="plan-card">
            <PanelHeader label="Plan">
                <span className="flex items-center gap-2">
                    {newest !== undefined && (
                        <span className="readout text-xs text-muted-foreground">{planRef(newest.id)}</span>
                    )}
                    <Chip tone={waiting ? 'blocked' : 'plain'}>
                        {newest?.status ?? (plans.needed ? 'needed' : 'none')}
                    </Chip>
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
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t p-3">
                <Button asChild variant={waiting ? 'default' : 'outline'} size="sm">
                    <Link to="/tickets/$key/plan" params={{ key: ticketKey }}>
                        <FileText />
                        Open plan
                    </Link>
                </Button>
                <span className="text-xs text-muted-foreground">{cardNote(plans)}</span>
            </div>
        </Panel>
    )
}

// What comes next for the plan, in a line beside the link: a planner at work, a request it has yet to read, or what
// the plan's page is for.
function cardNote(plans: TicketPlans): string {
    if (plans.planning !== null) {
        return `Run ${plans.planning} is writing a new plan.`
    }
    if (plans.changes_asked !== null) {
        return 'You asked for changes: the next tick asks the planner for a new plan.'
    }
    if (plans.newest === null) {
        return plans.needed ? 'None yet: the next tick dispatches a planner.' : 'No plan yet.'
    }
    return plans.newest.plan.status === 'proposed'
        ? 'It waits on you: read it, comment, then approve or ask for changes.'
        : 'Read it and its earlier plans on its page.'
}
