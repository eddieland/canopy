import type { CostTotal } from '@/api/types'
import { costText } from '@/lib/chores'
import { countedText } from '@/lib/cost-total'

/**
 * A field list's row for what a ticket's or a PR's runs cost in all (DESIGN §13): the total, and what it counted.
 * Not the overseer's: a tick serves the whole workspace.
 */
export function CostTotalRow({ cost }: { cost: CostTotal }) {
    return (
        <>
            <dt className="panel-label self-center">total cost</dt>
            <dd className="flex items-baseline gap-2 text-xs" data-testid="cost-total">
                <span className="readout">{costText(cost.cost_usd)}</span>
                <span className="text-muted-foreground">{countedText(cost)}</span>
            </dd>
        </>
    )
}
