import type { ModelsServed } from '@/api/types'
import { Cost } from '@/components/cost'
import { Field } from '@/components/fields'
import { None } from '@/components/none'
import { FAILED_READ, sameModel, unservedReason } from '@/lib/models'
import { cn } from '@/lib/utils'

/**
 * A Run panel's `model` field, under `spent`: each model that wrote the run's replies, as its session says (DESIGN
 * §13), its replies on hover. A run split between models gives each its share of the cost, the most costly first;
 * one model's cost is `spent` already. Until canopy reads the session, a few ended runs each tick, or when it cannot,
 * says why, muted. For a run that records the model canopy `asked` for, it says `asked X` until then instead, why
 * none served yet on hover. Once read, a run the model asked for served none of reads `asked Y ≠ served X`, and one it
 * served alongside another marks only the other `≠`: in the field's own color, since a model other than the one asked
 * for is worth knowing, not waiting on the operator. `X@variant` asked and `X` served are the same (`sameModel`).
 */
export function ModelsField({ models, asked = null }: { models: ModelsServed; asked?: string | null }) {
    return (
        <Field label="model" mono>
            <Models models={models} asked={asked} />
        </Field>
    )
}

function Models({ models, asked }: { models: ModelsServed; asked: string | null }) {
    const reason = unservedReason(models)
    if (reason !== null) {
        if (models.status === 'failed' && asked === null) {
            return (
                <span className="text-muted-foreground" title={models.error ?? undefined}>
                    none: {FAILED_READ}
                </span>
            )
        }
        return <NoneServed asked={asked} reason={reason} />
    }
    const split = models.models.length > 1
    // Whether each model is one canopy asked for; all of them when it asked for none.
    const askedFor = (model: string) => asked === null || sameModel(asked, model)
    const missed = !models.models.some((m) => askedFor(m.model))
    const served = (
        <span className={cn('flex-wrap gap-x-4', missed ? 'inline-flex' : 'flex')}>
            {models.models.map((m) => {
                const replies = m.replies === 1 ? '1 reply' : `${m.replies} replies`
                const other = !missed && !askedFor(m.model)
                return (
                    <span
                        key={m.model}
                        className="readout"
                        title={other ? `${replies}, not the model asked for` : replies}
                    >
                        {other && '≠ '}
                        {m.model}
                        {split && (
                            <>
                                {' '}
                                <Cost usd={m.cost_usd} className="text-muted-foreground" />
                            </>
                        )}
                    </span>
                )
            })}
        </span>
    )
    if (!missed) {
        return served
    }
    return (
        <span>
            asked {asked} ≠ served {served}
        </span>
    )
}

/** Why no model is named as having served a run; or, when canopy `asked` for one, that model, the why on hover. */
function NoneServed({ asked, reason }: { asked: string | null; reason: string }) {
    if (asked === null) {
        return <None reason={reason} />
    }
    return (
        <span className="readout" title={`none served: ${reason}`}>
            asked {asked}
        </span>
    )
}
