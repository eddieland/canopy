import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { spendModelsQuery } from '@/api/queries'
import type { SpendModel } from '@/api/types'
import { Field, Fields } from '@/components/fields'
import { costText } from '@/lib/cost-total'
import { perRun } from '@/lib/spend'

/** How far back the line reads, the spend page's longest window, which its link opens. */
const DAYS = 30

/**
 * A canary's read on a ticket's page, under its agents' models (DESIGN §13): what its worker runs cost per run on each
 * model that served them in the last 30 days, beside the workspace's worker runs on the same model, so a model
 * canaried here is checked where it was set, without sums over a workspace-wide table. Workers alone, as the reviewer's
 * model is not the one canaried. Shown once more than one model has served its workers, or while `override` says the
 * ticket sets its workers' model; it links to the spend page's By model narrowed to the ticket for the rest.
 */
export function TicketCanary({ ticketKey, override }: { ticketKey: string; override: boolean }) {
    const own = workerRows(useQuery(spendModelsQuery({ days: DAYS }, ticketKey)).data?.models)
    const shown = own.length > 1 || (override && own.length > 0)
    // Every run's, read only once the line shows.
    const every = workerRows(useQuery({ ...spendModelsQuery({ days: DAYS }), enabled: shown }).data?.models)
    if (!shown) {
        return null
    }
    return (
        <Fields className="pt-0" data-testid="ticket-canary">
            <Field label="worker cost">
                <span className="flex flex-col gap-0.5 font-mono text-xs">
                    {own.map((m) => {
                        const runs = m.runs === 1 ? '1 run' : `${m.runs} runs`
                        const theirs = every.find((w) => w.model === m.model)
                        return (
                            <span key={m.model} className="flex flex-wrap gap-x-2" data-testid="ticket-canary-model">
                                <span>{m.model}</span>
                                <span className="text-muted-foreground">
                                    {runs}, <span className="readout text-foreground">{costText(perRun(m))}/run</span>
                                    {' · '}
                                    {/* Unread until the workspace's own read comes in. */}
                                    workspace {theirs === undefined ? '…' : `${costText(perRun(theirs))}/run`}
                                </span>
                            </span>
                        )
                    })}
                    <Link
                        to="/reports/spend"
                        search={{ days: DAYS, ticket: ticketKey }}
                        className="font-sans text-accent underline-offset-4 hover:underline"
                    >
                        Its last {DAYS} days by model, on Spend
                    </Link>
                </span>
            </Field>
        </Fields>
    )
}

/** The worker runs' rows that name a model, the most costly first, as the server orders them. */
function workerRows(models: readonly SpendModel[] | undefined): (SpendModel & { model: string })[] {
    return (models ?? []).filter((m): m is SpendModel & { model: string } => m.kind === 'workers' && m.model !== null)
}
