import { useQuery } from '@tanstack/react-query'

import { configModelsQuery } from '@/api/queries'
import { ModelPicker } from '@/components/model-picker'
import { pickerModel, RUNTIME_DEFAULT, withVariant } from '@/lib/models'

/**
 * The model a review request's reviews run on (DESIGN §13, §21), in every persona: `Model [default ▾]`, the menu a
 * ticket's agents choose theirs with (`ModelPicker`), config's reviewer's model named after it in muted text while
 * none is picked. A model picked is this request's alone, as `canopy start URL --review --model M` gives it, and
 * `Use the default` goes back to config's. A model picked reads the runtime's list as the menu shows, as a ticket's
 * row naming a model does, so one the runtime no longer lists, kept in the form's draft, is in the failure color
 * before the menu opens, since the request's reviews would be refused on it; config's is the settings page's to mark,
 * and is read when the menu opens.
 */
export function ReviewModelMenu({
    model,
    url = 'URL',
    disabled = false,
    onChange,
    testId,
}: {
    /** The model picked for the request, `provider/model[@variant]`, or null for config's. */
    model: string | null
    /** The PR's URL, as the command the menu stands for names it; `URL` in the form, where it is still written. */
    url?: string
    /** Whether the menu is closed to choices, as while the request is sent. */
    disabled?: boolean
    /** Hears a model picked, or null to go back to config's. */
    onChange: (model: string | null) => void
    /** The menu's trigger's test id. */
    testId?: string
}) {
    const { data } = useQuery(configModelsQuery)
    const reviewer = data?.agents.find((row) => row.agent === 'reviewer')
    const id = reviewer?.model ?? null
    const configured = id === null ? null : withVariant(id, reviewer?.variant ?? null)
    const current = model === null ? pickerModel(configured) : pickerModel(model)
    return (
        <span className="flex flex-wrap items-center gap-2">
            <span className="panel-label" aria-hidden>
                Model
            </span>
            <ModelPicker
                current={current}
                chosen={model !== null}
                source={sourceOf(model, configured)}
                label="Model"
                agent="reviewer"
                clear="Use the default"
                unchosen="default"
                title={`canopy start ${url} --review --model ${model ?? 'M'}`}
                eager={model !== null}
                disabled={disabled}
                onChoose={onChange}
                testId={testId}
            />
            {/* What the default is, once config is read: the reviewer's in `[runtime.models]`, or the runtime's. */}
            {model === null && data !== undefined && (
                <span className="text-xs text-muted-foreground" data-testid="review-model-default">
                    {configured === null ? (
                        RUNTIME_DEFAULT
                    ) : (
                        <>
                            config&apos;s <span className="font-mono">{configured}</span>
                        </>
                    )}
                </span>
            )}
        </span>
    )
}

/** Where the model chosen now comes from, after its id in the menu: the request, config, or nothing. */
function sourceOf(model: string | null, configured: string | null): string {
    if (model !== null) {
        return 'this request'
    }
    return configured === null ? 'nothing sets one' : '[runtime.models]'
}
