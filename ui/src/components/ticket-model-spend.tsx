import { Link } from '@tanstack/react-router'

import type { AgentModel, SpendModel } from '@/api/types'
import { Cost } from '@/components/cost'
import { Tip } from '@/components/tip'
import { costText } from '@/lib/cost-total'
import { counted } from '@/lib/descriptions'
import { modelNames } from '@/lib/models'
import { comparedModels, perRun, TICKET_MODEL_WINDOW, workspacePerRun } from '@/lib/spend'
import { cn } from '@/lib/utils'

/**
 * What a ticket's worker runs cost each on each model over the last 30 days, beside what the workspace's worker runs
 * cost each on the same model: one line under the Work panel's models, when more than one model served the ticket's
 * workers or its override sets theirs (`comparedModels`), so a model tried on one ticket reads against the rest.
 * Workers only, so the reviewer's model does not mix in, as the total cost's split by model does. Its label opens
 * Spend's By model for the ticket over the same 30 days, for the replies and the reviewer's runs.
 */
export function TicketModelSpend({
    ticketKey,
    spend,
    models,
    className,
}: {
    ticketKey: string
    spend: readonly SpendModel[]
    models: readonly AgentModel[]
    className?: string
}) {
    const override = models.some((m) => m.agent === 'worker' && m.source === 'ticket')
    const rows = comparedModels(spend, override)
    if (rows.length === 0) {
        return null
    }
    const names = modelNames(rows.flatMap((m) => (m.model === null ? [] : [m.model])))
    return (
        <p
            className={cn('flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs text-muted-foreground', className)}
            data-testid="ticket-model-spend"
        >
            <Link
                to="/reports/spend"
                search={{ days: TICKET_MODEL_WINDOW.days, ticket: ticketKey }}
                className="text-accent underline-offset-4 hover:underline"
            >
                worker spend, {TICKET_MODEL_WINDOW.days} days
            </Link>
            {rows.map((m) => {
                const model = m.model ?? ''
                return (
                    <Tip key={model} fact={factOf(m)} mono>
                        <span className="font-mono">
                            {names.get(model) ?? model}: {counted(m.runs, 'run')},{' '}
                            <Cost usd={perRun(m)} className="text-foreground" />
                            /run · workspace <Cost usd={workspacePerRun(m)} />
                            /run
                        </span>
                    </Tip>
                )
            })}
        </p>
    )
}

/** A model's figures whole, on hover: its id, and both sides' runs and what they cost each. */
function factOf(m: SpendModel): string {
    const workspace = m.workspace_runs ?? 0
    return (
        `${m.model ?? ''}: ${counted(m.runs, 'run')} of this ticket's, ${costText(perRun(m))} each; ` +
        `${counted(workspace, 'run')} of the workspace's, these among them, ${costText(workspacePerRun(m))} each`
    )
}
