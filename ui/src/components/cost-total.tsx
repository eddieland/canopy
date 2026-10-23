import type { CostTotal } from '@/api/types'
import { Cost } from '@/components/cost'
import { Field } from '@/components/fields'
import { Tip } from '@/components/tip'
import { countedText, unattributedCost } from '@/lib/cost-total'
import { modelNames } from '@/lib/models'

// What the part of a total no session named a model for counts, on hover.
const UNNAMED_HINT =
    'What the runs no session named a model for reported: not read yet, no longer kept by the runtime, failed to ' +
    'read, or making no model call'

/**
 * A `Fields` row for what a ticket's or a PR's runs cost in all (DESIGN §13): the total, and what it counted. Not the
 * overseer's: a tick serves the whole workspace. When more than one model served a ticket's runs, a line under it
 * splits the total by model, the most costly first, then what no session named a model for.
 */
export function CostTotalRow({ cost }: { cost: CostTotal }) {
    return (
        <Field label="total cost" className="flex flex-wrap items-baseline gap-x-2 text-xs" data-testid="cost-total">
            <Cost usd={cost.cost_usd} />
            <span className="text-muted-foreground">{countedText(cost)}</span>
            {cost.models.length > 1 && <ByModel cost={cost} />}
        </Field>
    )
}

/** A total cost split by model, each named as a list names it (`modelNames`), whole in its tip with its runs. */
function ByModel({ cost }: { cost: CostTotal }) {
    const names = modelNames(cost.models.map((m) => m.model))
    const unnamed = unattributedCost(cost)
    return (
        <span
            className="flex basis-full flex-wrap gap-x-3 font-mono text-muted-foreground"
            data-testid="cost-total-models"
        >
            {cost.models.map((m) => (
                <Tip key={m.model} fact={`${m.model}, over ${m.runs === 1 ? '1 run' : `${m.runs} runs`}`} mono>
                    <span>
                        {names.get(m.model) ?? m.model} <Cost usd={m.cost_usd} className="text-foreground" />
                    </span>
                </Tip>
            ))}
            {unnamed !== null && (
                <Tip fact={UNNAMED_HINT} mono>
                    <span>
                        none <Cost usd={unnamed} className="text-foreground" />
                    </span>
                </Tip>
            )}
        </span>
    )
}
