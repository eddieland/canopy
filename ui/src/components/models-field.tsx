import type { ModelsServed } from '@/api/types'
import { Cost } from '@/components/cost'
import { Field } from '@/components/fields'
import { None } from '@/components/none'

/**
 * A Run panel's `model` field, under `spent`: each model that wrote the run's replies, as its session says (DESIGN
 * §13), its replies on hover. A run split between models gives each its share of the cost, the most costly first;
 * one model's cost is `spent` already. Until canopy reads the session, a few ended runs each tick, or when it cannot,
 * says why, muted.
 */
export function ModelsField({ models }: { models: ModelsServed }) {
    return (
        <Field label="model" mono>
            <Models models={models} />
        </Field>
    )
}

function Models({ models }: { models: ModelsServed }) {
    switch (models.status) {
        case 'found': {
            if (models.models.length === 0) {
                return <None reason="its session made no model call" />
            }
            const split = models.models.length > 1
            return (
                <span className="flex flex-wrap gap-x-4">
                    {models.models.map((m) => (
                        <span
                            key={m.model}
                            className="readout"
                            title={m.replies === 1 ? '1 reply' : `${m.replies} replies`}
                        >
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
        }
        case 'running': {
            return <None reason="read from its session once it ends" />
        }
        case 'unread': {
            return <None reason="not read yet: a tick reads a few ended runs' sessions" />
        }
        case 'no_session': {
            return <None reason="it reported no session to read" />
        }
        case 'missing': {
            return <None reason="the runtime no longer keeps its session" />
        }
        case 'failed': {
            return (
                <span className="text-muted-foreground" title={models.error ?? undefined}>
                    none: its session could not be read, tried again later
                </span>
            )
        }
    }
}
