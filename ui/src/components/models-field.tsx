import type { ModelsServed } from '@/api/types'
import { Cost } from '@/components/cost'
import { Field } from '@/components/fields'
import { None } from '@/components/none'
import { FAILED_READ, unservedReason } from '@/lib/models'
import { cn } from '@/lib/utils'

/**
 * A Run panel's `model` field, under `spent`: each model that wrote the run's replies, as its session says (DESIGN
 * §13), its replies on hover. A run split between models gives each its share of the cost, the most costly first;
 * one model's cost is `spent` already. Until canopy reads the session, a few ended runs each tick, or when it cannot,
 * says why, muted. For a run that records the model canopy `asked` for, it says `asked X` until then instead, why
 * none served yet on hover; once read, a model that served other than the one asked for reads `served X, asked Y`, in
 * `status-blocked`.
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
    const differs = asked !== null && models.models.some((m) => m.model !== asked)
    const served = (
        <span className={cn('flex-wrap gap-x-4', differs ? 'inline-flex' : 'flex')}>
            {models.models.map((m) => (
                <span key={m.model} className="readout" title={m.replies === 1 ? '1 reply' : `${m.replies} replies`}>
                    {m.model}
                    {split && (
                        <>
                            {' '}
                            <Cost usd={m.cost_usd} className="text-muted-foreground" />
                        </>
                    )}
                </span>
            ))}
        </span>
    )
    if (!differs) {
        return served
    }
    return (
        <span className="text-status-blocked">
            served {served}, asked {asked}
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
