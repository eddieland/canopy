import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'

import { chooseTicketModel } from '@/api/mutations'
import { keys, modelsQuery } from '@/api/queries'
import type { AgentModel } from '@/api/types'
import { Field, Fields } from '@/components/fields'
import { Notice } from '@/components/notice'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { failedText, MODEL_SOURCES, modelName, modelText } from '@/lib/outcomes'
import { cn } from '@/lib/utils'

/** A choice the menu makes: a model, or null to clear the ticket's override. */
interface Choice {
    /** The agent the choice is for. */
    agent: AgentModel['agent']
    /** The model, as `provider/model`, or null to clear the override. */
    model: string | null
}

/** Why a model the menu shows cannot be chosen: the runtime no longer lists it, so its agent's next run is refused. */
const GONE = 'no longer listed; its next run is refused'
/** Why config's model at a variant cannot be chosen: an override names the model alone, which the menu lists. */
const VARIANT = "config's, with a variant"

/**
 * The model each of a ticket's agents runs on at its next run (DESIGN §13), and where that comes from: its workers,
 * its planner, and its reviewer side by side in one row, an override marked, each a menu that sets the ticket's
 * override to one of the models the runtime lists, read when the menu opens, or clears it, as
 * `canopy model KEY MODEL --agent AGENT` and `--clear` do. A model the runtime no longer lists refuses the agent's next
 * run rather than run it on another: its menu's trigger is in the blocked color once the list says so.
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
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const choose = useMutation({
        mutationFn: ({ agent, model }: Choice) => chooseTicketModel(ticketKey, agent, model),
        onMutate: () => setSaid(null),
        onSuccess: (now) => {
            setSaid(modelText(ticketKey, now))
            void client.invalidateQueries({ queryKey: keys.ticket(ticketKey) })
        },
    })
    if (models.length === 0) {
        return null
    }
    // The choice being saved, while the server reads the runtime's list again to check it, for up to 30 seconds.
    const saving = choose.isPending ? choose.variables : undefined
    return (
        <div className={className} data-testid="ticket-models">
            <Fields className="pb-1.5">
                {/* One row for the three, so the conversation under the Work panel stays in reach. */}
                <Field label="models">
                    <span className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                        {models.map((m) => (
                            <span
                                key={m.agent}
                                className="flex items-baseline gap-x-1.5"
                                title={MODEL_SOURCES[m.source]}
                                data-testid="ticket-model"
                            >
                                <span className="text-xs text-muted-foreground">{m.agent}</span>
                                <ModelMenu
                                    current={m}
                                    saving={saving?.agent === m.agent ? saving : undefined}
                                    disabled={choose.isPending}
                                    onChoose={(model) => choose.mutate({ agent: m.agent, model })}
                                />
                                {/* Where the rest come from is in the title: only an override is this page's. */}
                                {m.source === 'ticket' && <Chip>override</Chip>}
                            </span>
                        ))}
                    </span>
                </Field>
            </Fields>
            <Notice error={choose.error} subject={choose.variables?.agent} className="px-3 pb-3">
                {said}
            </Notice>
        </div>
    )
}

function ModelMenu({
    current,
    saving,
    disabled,
    onChoose,
}: {
    current: AgentModel
    saving: Choice | undefined
    disabled: boolean
    onChoose: (model: string | null) => void
}) {
    const [open, setOpen] = useState(false)
    // Read when the menu opens, not before: each read starts the runtime.
    const listed = useQuery({ ...modelsQuery, enabled: open })
    const reading = listed.isPending || listed.isFetching
    const why = listed.data?.error ?? (listed.isError ? failedText(listed.error) : null)
    // What the runtime lists, once read; undefined while unread or unreadable, when no model is known to be gone.
    const models = why === null ? listed.data?.models : undefined
    const id = modelId(current)
    const gone = id !== null && models !== undefined && !models.includes(id)
    // The model chosen now, when the server would refuse it as a choice: shown, checked if it is the override, never
    // offered. One config's at a variant names it, which an override cannot; the listed model alone is the choice.
    const refusal = models === undefined ? null : gone ? GONE : current.variant === null ? null : VARIANT
    const shown = saving === undefined ? modelName(current.model) : `${saving.model ?? 'clearing the override'}…`
    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="outline"
                    size="xs"
                    disabled={disabled}
                    aria-busy={saving !== undefined}
                    aria-label={`${current.agent} model: ${shown}${gone ? `, ${GONE}` : ''}`}
                    title={gone ? GONE : undefined}
                    className={cn('font-mono', gone && 'border-status-blocked/40 text-status-blocked')}
                >
                    {shown}
                    <ChevronDown aria-hidden />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {/* The row's title says this too, but a title reaches neither a keyboard nor a touch. */}
                <DropdownMenuItem disabled>Where it comes from: {MODEL_SOURCES[current.source]}</DropdownMenuItem>
                <DropdownMenuSeparator />
                {reading && <DropdownMenuItem disabled>Reading the runtime&apos;s models…</DropdownMenuItem>}
                {why !== null && !reading && (
                    <>
                        <p className="px-2 py-1.5 text-sm text-status-failed">Could not read its models: {why}</p>
                        <DropdownMenuItem
                            onSelect={(event) => {
                                // Kept open, to show the list read again, or why it failed again.
                                event.preventDefault()
                                void listed.refetch()
                            }}
                        >
                            Read again
                        </DropdownMenuItem>
                    </>
                )}
                <DropdownMenuRadioGroup
                    value={current.source === 'ticket' && current.model !== null ? current.model : ''}
                    onValueChange={(value) => onChoose(value)}
                >
                    {models?.map((model) => (
                        <DropdownMenuRadioItem key={model} value={model} className="font-mono text-xs">
                            {model}
                        </DropdownMenuRadioItem>
                    ))}
                    {current.model !== null && refusal !== null && (
                        <DropdownMenuRadioItem
                            value={current.model}
                            disabled
                            title={refusal}
                            className="font-mono text-xs"
                        >
                            <span>
                                {current.model}
                                <span className="font-sans text-muted-foreground">: {refusal}</span>
                            </span>
                        </DropdownMenuRadioItem>
                    )}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={current.source !== 'ticket'} onSelect={() => onChoose(null)}>
                    Clear the override
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/** The model an agent runs on as the runtime's list names it, without config's variant; null for the default. */
function modelId(current: AgentModel): string | null {
    if (current.model === null || current.variant === null) {
        return current.model
    }
    return current.model.slice(0, -(current.variant.length + 1))
}
