import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useState } from 'react'

import { chooseTicketModel } from '@/api/mutations'
import { keys } from '@/api/queries'
import type { AgentModel } from '@/api/types'
import { Field, Fields } from '@/components/fields'
import { ModelPicker } from '@/components/model-picker'
import { Notice } from '@/components/notice'
import { sameModel } from '@/lib/models'
import { MODEL_SOURCES, modelText } from '@/lib/outcomes'

/** A choice the server saved, confirmed in its agent's row until the ticket's models change after it. */
interface Said {
    /** The agent's model now, as the server answered the choice. */
    now: AgentModel
    /** The ticket's models when the row last looked, as `seenOf` writes them. */
    seen: string
    /** Whether the ticket's models have caught up with the choice: any change after that ends the confirmation. */
    settled: boolean
}

/**
 * The model each of a ticket's agents runs on at its next run (DESIGN §13), and where that comes from: a row for its
 * workers, its planner, and its reviewer, each a `ModelChoice`, as an attention item shows them. The ticket's page lays
 * them out beside the personas instead (`TicketAgents`).
 */
export function TicketModels({
    ticketKey,
    models,
    className,
}: {
    ticketKey: string
    models: readonly AgentModel[]
    className?: string
}) {
    if (models.length === 0) {
        return null
    }
    return (
        <div className={className} data-testid="ticket-models">
            <Fields className="pb-1.5">
                {models.map((m) => (
                    <Field key={m.agent} label={`${m.agent} model`}>
                        <ModelChoice ticketKey={ticketKey} current={m} models={models} />
                    </Field>
                ))}
            </Fields>
        </div>
    )
}

/**
 * One agent's model at its next run: a menu that sets the ticket's override to one of the models the runtime lists,
 * read when the menu opens, or clears it, as `canopy model KEY MODEL --agent AGENT` and `--clear` do, each model at its
 * default or at one of the variants the runtime lists for it, then where the model comes from. The runtime's default
 * names no model, so a row on it names the one that served the agent's latest run once its session is read, as does a
 * row whose runs went to another. A choice saved is confirmed in place of where the model comes from, so nothing
 * moves, until the ticket's `models` change again, saying so when it sets aside
 * config's variant; a choice refused says why under the row. A model or variant the runtime no longer lists refuses
 * the agent's next run rather than run it on another: its menu's trigger is in the blocked color once the list says so.
 */
export function ModelChoice({
    ticketKey,
    current,
    models,
}: {
    ticketKey: string
    current: AgentModel
    models: readonly AgentModel[]
}) {
    const client = useQueryClient()
    const seen = seenOf(models)
    const [said, setSaid] = useState<Said | null>(null)
    if (said !== null && seen !== said.seen) {
        // The read the choice set off brings it in, and the confirmation stays; a change after that is news it no
        // longer speaks for, and so is one that is not the choice.
        const caughtUp = !said.settled && sameChoice(current, said.now)
        setSaid(caughtUp ? { ...said, seen, settled: true } : null)
    }
    const choose = useMutation({
        mutationFn: (model: string | null) => chooseTicketModel(ticketKey, current.agent, model),
        onMutate: () => setSaid(null),
        onSuccess: (now) => {
            setSaid({ now, seen, settled: false })
            void client.invalidateQueries({ queryKey: keys.ticket(ticketKey) })
        },
    })
    // Until the ticket is read again, the row shows what the server answered rather than what it had.
    const row = said !== null && !said.settled ? said.now : current
    // A session names a variant other than the model's default with it, so either may be the row's.
    const served =
        row.last_served === null || (row.model !== null && sameModel(row.model, row.last_served))
            ? null
            : row.last_served
    return (
        <>
            <span className="flex flex-wrap items-baseline gap-x-2" data-testid="ticket-model">
                <ModelPicker
                    current={row}
                    chosen={row.source === 'ticket'}
                    source={sourceOf(row.source)}
                    label={`${row.agent} model`}
                    agent={row.agent}
                    clear="Clear the override"
                    clearing="clearing the override"
                    // The choice being saved, while the server reads the runtime's list again to check it, for up to
                    // 30 seconds.
                    saving={choose.isPending ? { model: choose.variables ?? null } : undefined}
                    onChoose={(model) => choose.mutate(model)}
                />
                {said === null ? (
                    // The default's button already says where it comes from.
                    row.source !== 'default' && (
                        <span className="text-xs text-muted-foreground">{MODEL_SOURCES[row.source]}</span>
                    )
                ) : (
                    // In place of where the model comes from, which the sentence a screen reader is told says.
                    <output className="inline-flex items-baseline gap-1 text-xs text-status-done">
                        <Check aria-hidden className="size-3 self-center" />
                        saved
                        <span className="sr-only">: {modelText(ticketKey, said.now)}</span>
                        {/* What the sentence before says, to the eye, as the CLI puts it. */}
                        {said.now.dropped_variant !== null && (
                            <span aria-hidden className="text-muted-foreground">
                                (config&apos;s variant <span className="font-mono">{said.now.dropped_variant}</span> no
                                longer applies)
                            </span>
                        )}
                    </output>
                )}
                {served !== null && (
                    <span className="min-w-0 truncate text-xs text-muted-foreground" title={served}>
                        last served <span className="font-mono">{served}</span>
                    </span>
                )}
            </span>
            <Notice error={choose.error} className="pt-1" />
        </>
    )
}

/** Where the model chosen now comes from, after its id; for the default, the button's own word, so what sets it. */
function sourceOf(source: AgentModel['source']): string {
    return source === 'default' ? 'nothing sets one' : MODEL_SOURCES[source]
}

/** The ticket's models as one string, so a read that changes none of them leaves a row's confirmation standing. */
function seenOf(models: readonly AgentModel[]): string {
    return JSON.stringify(models)
}

/** Whether a row shows the choice the server answered: the same model, from the same place. */
function sameChoice(a: AgentModel, b: AgentModel): boolean {
    return a.model === b.model && a.source === b.source
}
