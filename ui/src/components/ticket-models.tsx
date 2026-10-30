import { noop, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown } from 'lucide-react'
import { useId, useState } from 'react'
import type { ReactNode } from 'react'

import { chooseTicketModel } from '@/api/mutations'
import { freshModelsQuery, keys, modelsQuery } from '@/api/queries'
import type { AgentModel } from '@/api/types'
import { Field, Fields } from '@/components/fields'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { sameModel } from '@/lib/models'
import { MODEL_SOURCES, modelName, modelText } from '@/lib/outcomes'
import { whyReadFailed } from '@/lib/read-failure'
import { cn } from '@/lib/utils'

/** A choice the menu made, while it saves: a model, or null to clear the ticket's override. */
interface Choice {
    /** The model, as `provider/model` or `provider/model@variant`, or null to clear the override. */
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
    /** Whether the choice cleared the override rather than set one, which the confirmation says. */
    cleared: boolean
}

/** Why a model the menu shows cannot be chosen: the runtime no longer lists it, so its agent's next run is refused. */
const GONE = 'no longer listed; its next run is refused'
/** Why a model at a variant cannot be chosen: the runtime lists the model, but not that variant of it any more. */
const VARIANT_GONE = 'variant no longer listed; its next run is refused'

/**
 * The model each of a ticket's agents runs on at its next run (DESIGN §13), and where that comes from: a row for its
 * workers, its planner, and its reviewer, each a `ModelChoice`, as an attention item shows them. The ticket's page lays
 * them out beside the personas instead (`TicketAgents`). `fresh` reads the runtime's list from the runtime itself, not
 * the one the server kept, as an item about a run refused its model does: that run has just found a model gone, which
 * a list read minutes ago may still name.
 */
export function TicketModels({
    ticketKey,
    models,
    fresh = false,
    className,
}: {
    ticketKey: string
    models: readonly AgentModel[]
    fresh?: boolean
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
                        <ModelChoice ticketKey={ticketKey} current={m} models={models} fresh={fresh} />
                    </Field>
                ))}
            </Fields>
        </div>
    )
}

/**
 * One agent's model at its next run: a menu that sets the ticket's override to one of the models the runtime lists,
 * or clears it, as `canopy model KEY MODEL --agent AGENT` and `--clear` do, each model at its default or at one of the
 * variants the runtime lists for it, then where the model comes from. The runtime's default names no model, so a row on
 * it names the one that served the agent's latest run once its session is read, as does a row whose runs went to
 * another. A choice saved is confirmed in place of where the model comes from, so nothing moves, until the ticket's
 * `models` change again: `saved`, saying so when it sets aside config's variant, or `cleared`; a choice refused says
 * why under the row. A model or variant the runtime no longer lists refuses the agent's next run rather than run it on
 * another: its menu's trigger is in the failure color, as its attention item is, once the list says so, which a row
 * that names a model reads as it shows (`fresh`, as `TicketModels` says).
 */
export function ModelChoice({
    ticketKey,
    current,
    models,
    fresh = false,
}: {
    ticketKey: string
    current: AgentModel
    models: readonly AgentModel[]
    fresh?: boolean
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
        onSuccess: (now, model) => {
            setSaid({ now, seen, settled: false, cleared: model === null })
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
                    fresh={fresh}
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
                        {said.cleared ? 'cleared' : 'saved'}
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

/**
 * The picker for one agent's model: the trigger names the model its next run goes to, its variant set apart, in the
 * failure color while the runtime's list no longer has it, and opens a list of the models the runtime lists under a
 * field that narrows it, grouped by provider, each model's variants under it in the runtime's order, with the model
 * chosen now pinned at the top and checked wherever it is, whatever sets it. What is typed finds each row by its own
 * id alone, the pinned one set aside, so a variant typed and Enter picks the first model at that variant. Picking one
 * sets the ticket's override and closes the list; `Clear the override`, below the list rather than in it, so a long
 * list never scrolls it away, clears it. The trigger ends a long id in an ellipsis, the whole of it on hover, and
 * stays in the keyboard's reach while a choice saves, so the focus comes back to it once the list closes; it opens
 * nothing until the save is done.
 */
function ModelPicker({
    current,
    fresh,
    saving,
    onChoose,
}: {
    current: AgentModel
    fresh: boolean
    saving: Choice | undefined
    onChoose: (model: string | null) => void
}) {
    const client = useQueryClient()
    const [open, setOpen] = useState(false)
    // What is typed in the field, which a variant's row reads to name its model when the model's own row is hidden.
    const [search, setSearch] = useState('')
    // Read as the row shows, not when its list opens, so a model gone is marked before anyone goes looking: the server
    // keeps the list it read for minutes, so a read seldom starts the runtime. The runtime's default names no model to
    // lose, so its row reads when its list opens. Each row's read is the others', under one key.
    const listed = useQuery({
        ...(fresh ? freshModelsQuery : modelsQuery),
        enabled: fresh || open || current.model !== null,
    })
    const reading = listed.isPending || listed.isFetching
    // A read that failed did nothing, so it says so in a read's words, not a write's.
    const why = listed.data?.error ?? (listed.isError ? whyReadFailed(listed.error) : null)
    // What the runtime lists, once read; undefined while unread or unreadable, when no model is known to be gone.
    const models = why === null ? listed.data?.models : undefined
    const variants = listed.data?.variants ?? {}
    const id = modelId(current)
    // Why the model chosen now would be refused as a choice, and refuses its agent's next run: shown, checked, never
    // offered. Null while the list is unread, or nothing is chosen.
    const refusal = models === undefined || id === null ? null : refusalOf(id, current.variant, models, variants)
    const refusalId = useId()
    const shown = saving === undefined ? modelName(current.model) : `${saving.model ?? 'clearing the override'}…`
    // A model's id is data, in monospace; the runtime's default names none, so it is muted prose.
    const named = (saving === undefined ? current.model : saving.model) !== null

    function choose(model: string | null) {
        setOpen(false)
        onChoose(model)
    }

    function openChange(now: boolean) {
        if (now && saving !== undefined) {
            return
        }
        setOpen(now)
        // Each opening starts from the whole list, as cmdk's own field does.
        setSearch('')
        if (now) {
            // On a page left open, a list older than a minute is read again as the menu opens, the server's kept one;
            // a read that fails says so in the list, from the query's own state.
            client.query(modelsQuery).catch(noop)
        }
    }

    return (
        <Popover open={open} onOpenChange={openChange}>
            <PopoverTrigger asChild>
                {/* Not `disabled` while it saves, which would drop the focus the list hands back to it. */}
                <Button
                    variant="outline"
                    size="xs"
                    aria-disabled={saving !== undefined}
                    aria-busy={saving !== undefined}
                    aria-label={`${current.agent} model: ${shown}${refusal === null ? '' : `, ${refusal}`}`}
                    title={refusal === null ? shown : `${shown}: ${refusal}`}
                    className={cn(
                        'max-w-full aria-disabled:opacity-50',
                        // The `xs` button is monospace of its own, as an id is.
                        !named && 'font-sans text-muted-foreground',
                        // It refuses the agent's next run, so it is broken, as its attention item says.
                        refusal !== null && 'border-status-failed/40 text-status-failed',
                    )}
                >
                    <span className="truncate">
                        {saving === undefined && id !== null && current.variant !== null ? (
                            <>
                                {id}
                                <span className={cn(refusal === null && 'text-muted-foreground')}>
                                    @{current.variant}
                                </span>
                            </>
                        ) : (
                            shown
                        )}
                    </span>
                    <ChevronDown aria-hidden />
                </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto max-w-96 min-w-(--radix-popover-trigger-width) p-0">
                {/* What is typed is found anywhere in an id, as the repository picker finds a name, rather than by
                    cmdk's fuzzy match, which would find `opus` in openai/gpt-5-plus. */}
                <Command label={`Find a model for the ${current.agent}`} filter={holds} className="min-w-72">
                    {/* cmdk names the field by the command's label, and the list by its own. */}
                    <CommandInput placeholder="Find a model" value={search} onValueChange={setSearch} />
                    <CommandList label="Models">
                        {models !== undefined && <CommandEmpty>no model has that name</CommandEmpty>}
                        {/* Pinned, so a long list keeps it in reach: the id, then where it comes from, or, under it and
                            out of its disabled look, in the failure color, why it cannot be chosen again. The
                            runtime's default is a state, not a choice. Set aside while something is typed, which finds
                            the model chosen in its provider's group, so Enter takes what was typed for. */}
                        {search.trim() === '' && (
                            <CommandGroup heading="Chosen now">
                                <ModelItem
                                    value="current"
                                    checked={current.model !== null}
                                    disabled={current.model === null || refusal !== null}
                                    title={refusal ?? modelName(current.model)}
                                    note={refusal === null ? sourceOf(current.source) : undefined}
                                    describedBy={refusal === null ? undefined : refusalId}
                                    // An override chosen again is the same override: nothing to save.
                                    onSelect={() =>
                                        current.source === 'ticket' ? setOpen(false) : choose(current.model)
                                    }
                                >
                                    <span className={cn(current.model === null && 'font-sans text-muted-foreground')}>
                                        {modelName(current.model)}
                                    </span>
                                </ModelItem>
                                {refusal !== null && (
                                    <p id={refusalId} className="pb-1.5 pl-8 text-xs text-status-failed">
                                        {refusal}
                                    </p>
                                )}
                            </CommandGroup>
                        )}
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
                                {ids.flatMap((model) => {
                                    const each = (variants[model] ?? []).map((v) => `${model}@${v}`)
                                    // A variant found by what is typed, its model not, names its model to the eye too.
                                    const alone = holds(model, search) === 0
                                    return [
                                        // Found by its own id alone: a variant typed then finds the variant's row
                                        // first, so Enter takes it rather than the model at its default.
                                        <ModelItem
                                            key={model}
                                            value={model}
                                            checked={model === current.model}
                                            onSelect={() => choose(model)}
                                            label={each.length === 0 ? undefined : `${model} (default)`}
                                            note={each.length === 0 ? undefined : '(default)'}
                                        >
                                            {model}
                                        </ModelItem>,
                                        ...each.map((atVariant) => (
                                            <ModelItem
                                                key={atVariant}
                                                value={atVariant}
                                                checked={atVariant === current.model}
                                                onSelect={() => choose(atVariant)}
                                                // Under its model, which a screen reader is told again.
                                                label={atVariant}
                                                className="pl-6"
                                            >
                                                {alone ? (
                                                    <span>
                                                        <span className="text-muted-foreground">{model}</span>
                                                        {atVariant.slice(model.length)}
                                                    </span>
                                                ) : (
                                                    atVariant.slice(model.length)
                                                )}
                                            </ModelItem>
                                        )),
                                    ]
                                })}
                            </CommandGroup>
                        ))}
                    </CommandList>
                </Command>
                {/* Out of the list, so it stays in sight however far the list scrolls; a Tab from the field. */}
                <div className="border-t border-border p-1">
                    <Button
                        variant="ghost"
                        size="sm"
                        disabled={current.source !== 'ticket'}
                        onClick={() => choose(null)}
                        className="w-full justify-start font-normal"
                    >
                        Clear the override
                    </Button>
                </div>
            </PopoverContent>
        </Popover>
    )
}

/**
 * A model in the picker's list, with a check at its left while it is the one chosen now: its id, ending in an ellipsis
 * when it is too long for the list, then a muted `note` after it, or under it when the two do not fit on a line;
 * `describedBy` names what says more of it outside it.
 */
function ModelItem({
    value,
    checked,
    disabled,
    title,
    onSelect,
    label,
    note,
    describedBy,
    className,
    children,
}: {
    value: string
    checked: boolean
    disabled?: boolean
    title?: string
    onSelect: () => void
    label?: string
    note?: string
    describedBy?: string
    className?: string
    children: ReactNode
}) {
    return (
        <CommandItem
            value={value}
            disabled={disabled}
            // The whole id, which a long one's ellipsis hides.
            title={title ?? value}
            onSelect={onSelect}
            aria-checked={checked}
            aria-label={label}
            aria-describedby={describedBy}
            className={cn('font-mono text-xs', className)}
        >
            <span className="flex size-4 items-center justify-center">
                {checked && <Check aria-hidden className="size-4 text-accent" />}
            </span>
            <span className="flex min-w-0 flex-wrap gap-x-2">
                <span className="truncate">{children}</span>
                {note !== undefined && <span className="font-sans text-muted-foreground">{note}</span>}
            </span>
        </CommandItem>
    )
}

/** Why the runtime's list refuses `id` at `variant`: it lists no such model, or not that variant of it; else null. */
function refusalOf(
    id: string,
    variant: string | null,
    models: readonly string[],
    variants: Readonly<Record<string, readonly string[]>>,
): string | null {
    if (!models.includes(id)) {
        return GONE
    }
    return variant === null || (variants[id] ?? []).includes(variant) ? null : VARIANT_GONE
}

/** Where the model chosen now comes from, after its id; for the default, the button's own word, so what sets it. */
function sourceOf(source: AgentModel['source']): string {
    return source === 'default' ? 'nothing sets one' : MODEL_SOURCES[source]
}

/** How an item ranks for what is typed in the field: 1 when its id holds it, else 0, which hides it. */
function holds(value: string, search: string): number {
    return value.toLowerCase().includes(search.trim().toLowerCase()) ? 1 : 0
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
