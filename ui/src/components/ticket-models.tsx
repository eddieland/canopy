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
import { MODEL_SOURCES, modelName, modelText } from '@/lib/outcomes'

/** A choice the menu makes: a model, or null to clear the ticket's override. */
interface Choice {
    /** The agent the choice is for. */
    agent: AgentModel['agent']
    /** The model, as `provider/model`, or null to clear the override. */
    model: string | null
}

/**
 * The model each of a ticket's agents runs on at its next run (DESIGN §13), and where that comes from: a row for its
 * workers, its planner, and its reviewer, side by side in one row, an override marked, each a menu that sets the ticket's override to one of the models the runtime
 * lists, read when the menu opens, or clears it, as `canopy model KEY MODEL --agent AGENT` and `--clear` do. A model
 * the runtime no longer lists refuses the agent's next run rather than run it on another.
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
        onSuccess: (now) => {
            setSaid(modelText(ticketKey, now))
            void client.invalidateQueries({ queryKey: keys.ticket(ticketKey) })
        },
    })
    if (models.length === 0) {
        return null
    }
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
            <Notice error={choose.error} className="px-3 pb-3">
                {said}
            </Notice>
        </div>
    )
}

function ModelMenu({
    current,
    disabled,
    onChoose,
}: {
    current: AgentModel
    disabled: boolean
    onChoose: (model: string | null) => void
}) {
    const [open, setOpen] = useState(false)
    // Read when the menu opens, not before: each read starts the runtime.
    const listed = useQuery({ ...modelsQuery, enabled: open })
    const name = modelName(current.model)
    const models = listed.data?.models ?? []
    // A model the runtime no longer lists is still the one chosen: it stays in the list so the menu shows it checked.
    const choices = current.model === null || models.includes(current.model) ? models : [...models, current.model]
    const why = listed.data?.error ?? (listed.isError ? listed.error.message : null)
    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="outline"
                    size="xs"
                    disabled={disabled}
                    aria-label={`${current.agent} model: ${name}`}
                    className="font-mono"
                >
                    {name}
                    <ChevronDown aria-hidden />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {listed.isPending && <DropdownMenuItem disabled>Reading the runtime&apos;s models…</DropdownMenuItem>}
                {why !== null && <DropdownMenuItem disabled>Could not read its models: {why}</DropdownMenuItem>}
                <DropdownMenuRadioGroup
                    value={current.source === 'ticket' && current.model !== null ? current.model : ''}
                    onValueChange={(value) => onChoose(value)}
                >
                    {choices.map((model) => (
                        <DropdownMenuRadioItem key={model} value={model} className="font-mono text-xs">
                            {model}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={current.source !== 'ticket'} onSelect={() => onChoose(null)}>
                    Clear the override
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
