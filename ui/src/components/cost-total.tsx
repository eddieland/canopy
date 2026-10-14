import type { CostTotal } from '@/api/types'
import { Field } from '@/components/fields'
import { Cost } from '@/components/cost'
import { countedText } from '@/lib/cost-total'

/**
 * A `Fields` row for what a ticket's or a PR's runs cost in all (DESIGN §13): the total, and what it counted.
 * Not the overseer's: a tick serves the whole workspace.
 */
export function CostTotalRow({ cost }: { cost: CostTotal }) {
    return (
        <Field label="total cost" className="flex items-baseline gap-2 text-xs" data-testid="cost-total">
            <Cost usd={cost.cost_usd} />
            <span className="text-muted-foreground">{countedText(cost)}</span>
        </Field>
    )
}
