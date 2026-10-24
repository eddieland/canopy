import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { chooseTicketModel } from '@/api/mutations'
import { keys, modelsQuery } from '@/api/queries'
import type { AgentModel } from '@/api/types'
import { Field, Fields } from '@/components/fields'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { failedText, MODEL_SOURCES, modelName, modelText } from '@/lib/outcomes'
import { cn } from '@/lib/utils'

/** A choice the menu makes: a model, or null to clear the ticket's override. */
interface Choice {
    /** The agent the choice is for. */
    agent: AgentModel['agent']
    /** The model, as `provider/model`, or null to clear the override. */
    model: string | null
}

/** A choice the server saved, confirmed in its agent's row until the ticket's models change after it. */
interface Said {
    /** The agent's model now, as the server answered the choice. */
    now: AgentModel
    /** The ticket's models when the row last looked, as `seenOf` writes them. */
    seen: string
    /** Whether the ticket's models have caught up with the choice: any change after that ends the confirmation. */
    settled: boolean
}

/** Why a model the menu shows cannot be chosen: the runtime no longer lists it, so its agent's next run is refused. */
const GONE = 'no longer listed; its next run is refused'
/** Why config's model at a variant cannot be chosen: an override names the model alone, which the menu lists. */
const VARIANT = "config's, with a variant"

/**
 * The model each of a ticket's agents runs on at its next run (DESIGN §13), and where that comes from: a row for its
 * workers, its planner, and its reviewer, laid out as `TicketPersonas` lays out their personas, each a menu that sets
 * the ticket's override to one of the models the runtime lists, read when the menu opens, or clears it, as
 * `canopy model KEY MODEL --agent AGENT` and `--clear` do. The runtime's default names no model, so a row on it names
 * the one that served the agent's latest run once its session is read, as does a row whose runs went to another. A
 * choice saved is confirmed in its row, in place, until the ticket's models change again. A model the runtime no
 * longer lists refuses the agent's next run rather than run it on another: its menu's trigger is in the blocked color
 * once the list says so.
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
    const seen = seenOf(models)
    const [said, setSaid] = useState<Said | null>(null)
    if (said !== null && seen !== said.seen) {
        // The read the choice set off brings it in, and the confirmation stays; a change after that is news it no
        // longer speaks for, and so is one that is not the choice.
        const arrived = models.find((m) => m.agent === said.now.agent)
        const caughtUp = !said.settled && arrived !== undefined && sameChoice(arrived, said.now)
        setSaid(caughtUp ? { ...said, seen, settled: true } : null)
    }
    const choose = useMutation({
        mutationFn: ({ agent, model }: Choice) => chooseTicketModel(ticketKey, agent, model),
        onMutate: () => setSaid(null),
        onSuccess: (now) => {
            setSaid({ now, seen, settled: false })
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
                {models.map((m) => {
                    const confirmed = said?.now.agent === m.agent ? said : null
                    // Until the ticket is read again, the row shows what the server answered rather than what it had.
                    const row = confirmed !== null && !confirmed.settled ? confirmed.now : m
                    const served = row.last_served === modelId(row) ? null : row.last_served
                    return (
                        <Field key={m.agent} label={`${m.agent} model`}>
                            <span className="flex flex-wrap items-baseline gap-x-2" data-testid="ticket-model">
                                <ModelPicker
                                    current={row}
                                    saving={saving?.agent === m.agent ? saving : undefined}
                                    disabled={choose.isPending}
                                    onChoose={(model) => choose.mutate({ agent: m.agent, model })}
                                />
                                {/* The default's button already says where it comes from. */}
                                {row.source !== 'default' && (
                                    <span className="text-xs text-muted-foreground">{MODEL_SOURCES[row.source]}</span>
                                )}
                                {confirmed !== null && (
                                    <output className="inline-flex items-baseline gap-1 text-xs text-status-done">
                                        <Check aria-hidden className="size-3 self-center" />
                                        saved
                                        <span className="sr-only">: {modelText(ticketKey, confirmed.now)}</span>
                                    </output>
                                )}
                                {served !== null && (
                                    <span className="text-xs text-muted-foreground">
                                        last served <span className="font-mono">{served}</span>
                                    </span>
                                )}
                            </span>
                        </Field>
                    )
                })}
            </Fields>
            <Notice error={choose.error} subject={choose.variables?.agent} className="px-3 pb-3" />
        </div>
    )
}

/**
 * The picker for one agent's model: the trigger names the model its next run goes to, and opens a list of the models
 * the runtime lists under a field that narrows it, grouped by provider, with the model chosen now pinned at the top
 * and checked wherever it is, whatever sets it. Picking one sets the ticket's override and closes the list; `Clear
 * the override` at its foot, reachable whatever is typed, clears it.
 */
function ModelPicker({
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
    // Read when the list opens, not before: each read starts the runtime.
    const listed = useQuery({ ...modelsQuery, enabled: open })
    const reading = listed.isPending || listed.isFetching
    const why = listed.data?.error ?? (listed.isError ? failedText(listed.error) : null)
    // What the runtime lists, once read; undefined while unread or unreadable, when no model is known to be gone.
    const models = why === null ? listed.data?.models : undefined
    const id = modelId(current)
    const gone = id !== null && models !== undefined && !models.includes(id)
    // The model chosen now, when the server would refuse it as a choice: shown, checked, never offered. One config's
    // at a variant names it, which an override cannot; the listed model alone is the choice.
    const refusal = models === undefined ? null : gone ? GONE : current.variant === null ? null : VARIANT
    const shown = saving === undefined ? modelName(current.model) : `${saving.model ?? 'clearing the override'}…`
    // A model's id is data, in monospace; the runtime's default names none, so it is muted prose.
    const named = (saving === undefined ? current.model : saving.model) !== null

    function choose(model: string | null) {
        setOpen(false)
        onChoose(model)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <Button
                    variant="outline"
                    size="xs"
                    disabled={disabled}
                    aria-busy={saving !== undefined}
                    aria-label={`${current.agent} model: ${shown}${gone ? `, ${GONE}` : ''}`}
                    title={gone ? GONE : undefined}
                    className={cn(
                        // The `xs` button is monospace of its own, as an id is.
                        !named && 'font-sans text-muted-foreground',
                        gone && 'border-status-blocked/40 text-status-blocked',
                    )}
                >
                    {shown}
                    <ChevronDown aria-hidden />
                </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto max-w-96 min-w-(--radix-popover-trigger-width) p-0">
                {/* What is typed is found anywhere in an id, as the repository picker finds a name, rather than by
                    cmdk's fuzzy match, which would find `opus` in openai/gpt-5-plus. */}
                <Command label={`Find a model for the ${current.agent}`} filter={holds} className="min-w-72">
                    {/* cmdk names the field by the command's label, and the list by its own. */}
                    <CommandInput placeholder="Find a model" />
                    <CommandList label="Models">
                        {models !== undefined && <CommandEmpty>no model has that name</CommandEmpty>}
                        <CommandGroup heading="Chosen now">
                            {/* Pinned, so a long list keeps it in reach: the id, then where it comes from, or why it
                                cannot be chosen again. The runtime's default is a state, not a choice. */}
                            <ModelItem
                                value="current"
                                keywords={[current.model ?? MODEL_SOURCES.default]}
                                checked={current.model !== null}
                                disabled={current.model === null || refusal !== null}
                                title={refusal ?? undefined}
                                // An override chosen again is the same override: nothing to save.
                                onSelect={() => (current.source === 'ticket' ? setOpen(false) : choose(id))}
                            >
                                <span className={cn(current.model === null && 'font-sans text-muted-foreground')}>
                                    {modelName(current.model)}
                                </span>
                                <span className="font-sans text-muted-foreground">
                                    {refusal ?? sourceOf(current.source)}
                                </span>
                            </ModelItem>
                        </CommandGroup>
                        {reading && (
                            <p className="px-2 py-1.5 text-sm text-muted-foreground">
                                Reading the runtime&apos;s models…
                            </p>
                        )}
                        {why !== null && !reading && (
                            <>
                                <p className="px-2 py-1.5 text-sm text-status-failed">
                                    Could not read its models: {why}
                                </p>
                                {/* Kept open, to show the list read again, or why it failed again. */}
                                <CommandItem forceMount value="read again" onSelect={() => void listed.refetch()}>
                                    Read again
                                </CommandItem>
                            </>
                        )}
                        {byProvider(models ?? []).map(([provider, ids]) => (
                            <CommandGroup key={provider} heading={provider}>
                                {ids.map((model) => (
                                    <ModelItem
                                        key={model}
                                        value={model}
                                        checked={model === id}
                                        onSelect={() => choose(model)}
                                    >
                                        {model}
                                    </ModelItem>
                                ))}
                            </CommandGroup>
                        ))}
                        <CommandSeparator alwaysRender />
                        <CommandItem
                            forceMount
                            value="clear the override"
                            disabled={current.source !== 'ticket'}
                            onSelect={() => choose(null)}
                        >
                            Clear the override
                        </CommandItem>
                    </CommandList>
                </Command>
            </PopoverContent>
        </Popover>
    )
}

/** A model in the picker's list, with a check at its left while it is the one chosen now. */
function ModelItem({
    value,
    keywords,
    checked,
    disabled,
    title,
    onSelect,
    children,
}: {
    value: string
    keywords?: string[]
    checked: boolean
    disabled?: boolean
    title?: string
    onSelect: () => void
    children: ReactNode
}) {
    return (
        <CommandItem
            value={value}
            keywords={keywords}
            disabled={disabled}
            title={title}
            onSelect={onSelect}
            aria-checked={checked}
            className="font-mono text-xs"
        >
            <span className="flex size-4 items-center justify-center">
                {checked && <Check aria-hidden className="size-4 text-accent" />}
            </span>
            <span className="flex flex-wrap gap-x-2 truncate">{children}</span>
        </CommandItem>
    )
}

/** Where the model chosen now comes from, after its id; for the default, the button's own word, so what sets it. */
function sourceOf(source: AgentModel['source']): string {
    return source === 'default' ? 'nothing sets one' : MODEL_SOURCES[source]
}

/** How an item ranks for what is typed in the field: 1 when its id, or a keyword, holds it, else 0, which hides it. */
function holds(value: string, search: string, keywords?: string[]): number {
    const typed = search.trim().toLowerCase()
    return [value, ...(keywords ?? [])].some((word) => word.toLowerCase().includes(typed)) ? 1 : 0
}

/** The models by provider, the part of `provider/model` before the slash, each group in the list's own order. */
function byProvider(models: readonly string[]): [string, string[]][] {
    const groups = new Map<string, string[]>()
    for (const model of models) {
        const slash = model.indexOf('/')
        const provider = slash === -1 ? model : model.slice(0, slash)
        const group = groups.get(provider)
        if (group === undefined) {
            groups.set(provider, [model])
        } else {
            group.push(model)
        }
    }
    return [...groups]
}

/** The model an agent runs on as the runtime's list names it, without config's variant; null for the default. */
function modelId(current: AgentModel): string | null {
    if (current.model === null || current.variant === null) {
        return current.model
    }
    return current.model.slice(0, -(current.variant.length + 1))
}

/** The ticket's models as one string, so a read that changes none of them leaves a row's confirmation standing. */
function seenOf(models: readonly AgentModel[]): string {
    return JSON.stringify(models)
}

/** Whether a row shows the choice the server answered: the same model, from the same place. */
function sameChoice(a: AgentModel, b: AgentModel): boolean {
    return a.model === b.model && a.source === b.source
}
