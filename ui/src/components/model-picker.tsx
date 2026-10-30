import { noop, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown } from 'lucide-react'
import { useId, useState } from 'react'
import type { ReactNode } from 'react'

import { freshModelsQuery, modelsQuery } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { PickerModel } from '@/lib/models'
import { modelName } from '@/lib/outcomes'
import { whyReadFailed } from '@/lib/read-failure'
import { cn } from '@/lib/utils'

/** Why a model the menu shows cannot be chosen: the runtime no longer lists it, so its agent's next run is refused. */
const GONE = 'no longer listed; its next run is refused'
/** Why a model at a variant cannot be chosen: the runtime lists the model, but not that variant of it any more. */
const VARIANT_GONE = 'variant no longer listed; its next run is refused'

/**
 * The menu that chooses the model one of canopy's agents runs on (DESIGN §13), shared by a ticket's agents
 * (`TicketModels`) and a review request (`ReviewModelMenu`): the trigger names the model its next run goes to, its
 * variant set apart, or `unchosen` in muted prose while the menu's own choice is unset, and opens a list of the models
 * the runtime lists, read as the trigger shows when `eager`, else when it opens, under a field that narrows it, grouped
 * by provider, each model's variants under it in the runtime's order, with the model chosen now pinned at the top and
 * checked wherever it is, whatever sets it. What is typed finds each row by its own id alone, the pinned one set aside,
 * so a variant typed and Enter picks the first model at that variant. Picking one hands it to `onChoose` and closes the
 * list; `clear`, below the list rather than in it, so a long list never scrolls it away, hands it null. The trigger
 * ends a long id in an ellipsis, the whole of it on hover, and stays in the keyboard's reach while a choice saves, so
 * the focus comes back to it once the list closes; it opens nothing until the save is done. A model or variant the
 * runtime no longer lists refuses the agent's next run rather than run it on another: the trigger is in the failure
 * color once the list says so, and the pinned row says why under it.
 */
export function ModelPicker({
    current,
    chosen,
    source,
    label,
    agent,
    clear,
    clearing = clear,
    unchosen,
    title,
    fresh = false,
    eager = false,
    saving,
    disabled = false,
    onChoose,
    testId,
}: {
    /** The model the agent's next run goes to now, whatever sets it. */
    current: PickerModel
    /** Whether the menu's own choice sets `current`: `clear` is offered, and picking it again saves nothing. */
    chosen: boolean
    /** Where `current` comes from, named after it in the pinned row. */
    source: string
    /** The trigger's accessible name, before what it names: `reviewer model`. */
    label: string
    /** The agent the model is for, which the field's name says. */
    agent: string
    /** What the button under the list that hands `onChoose` null says. */
    clear: string
    /** What the trigger reads while a clear saves, before its ellipsis: `clearing the override`. */
    clearing?: string
    /** What the trigger reads while `chosen` is false, in place of the model, such as `default`; the model if unset. */
    unchosen?: string
    /** The trigger's tip, such as the command it stands for; the model it names if unset. */
    title?: string
    /** Whether to read the runtime's list from the runtime itself, not the one the server kept, as it shows. */
    fresh?: boolean
    /** Whether to read the runtime's list as the trigger shows, not only when the menu opens, to mark a model gone. */
    eager?: boolean
    /** The choice being saved, a model or null for clearing it, while the server checks it; none while idle. */
    saving?: { model: string | null }
    /** Whether the menu is closed to choices, as while what it belongs to is sent. */
    disabled?: boolean
    /** Hears a model picked, or null for `clear`. */
    onChoose: (model: string | null) => void
    /** The trigger's test id. */
    testId?: string
}) {
    const client = useQueryClient()
    const [open, setOpen] = useState(false)
    // What is typed in the field, which a variant's row reads to name its model when the model's own row is hidden.
    const [search, setSearch] = useState('')
    // Read as the trigger shows when `eager`, not when its list opens, so a model gone is marked before anyone goes
    // looking: the server keeps the list it read for minutes, so a read seldom starts the runtime. Each menu's read is
    // the others', under one key.
    const listed = useQuery({
        ...(fresh ? freshModelsQuery : modelsQuery),
        enabled: fresh || open || eager,
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
    const placeholder = saving === undefined && !chosen ? unchosen : undefined
    const shown = saving === undefined ? (placeholder ?? modelName(current.model)) : `${saving.model ?? clearing}…`
    // A model's id is data, in monospace; the runtime's default names none, nor does a placeholder: they are prose.
    const named = placeholder === undefined && (saving === undefined ? current.model : saving.model) !== null
    const closed = disabled || saving !== undefined

    function choose(model: string | null) {
        setOpen(false)
        onChoose(model)
    }

    function openChange(now: boolean) {
        if (now && closed) {
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
                    aria-disabled={closed}
                    aria-busy={saving !== undefined}
                    aria-label={`${label}: ${shown}${refusal === null ? '' : `, ${refusal}`}`}
                    title={refusal === null ? (title ?? shown) : `${title ?? shown}: ${refusal}`}
                    className={cn(
                        'max-w-full aria-disabled:opacity-50',
                        // The `xs` button is monospace of its own, as an id is.
                        !named && 'font-sans text-muted-foreground',
                        // It refuses the agent's next run, so it is broken, as its attention item says.
                        refusal !== null && 'border-status-failed/40 text-status-failed',
                    )}
                    data-testid={testId}
                >
                    <span className="truncate">
                        {named && saving === undefined && id !== null && current.variant !== null ? (
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
                <Command label={`Find a model for the ${agent}`} filter={holds} className="min-w-72">
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
                                    note={refusal === null ? source : undefined}
                                    describedBy={refusal === null ? undefined : refusalId}
                                    // The menu's own choice chosen again is the same choice: nothing to save.
                                    onSelect={() => (chosen ? setOpen(false) : choose(current.model))}
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
                        disabled={!chosen}
                        onClick={() => choose(null)}
                        className="w-full justify-start font-normal"
                    >
                        {clear}
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

/** The model as the runtime's list names it, without its variant; null for the default. */
function modelId(current: PickerModel): string | null {
    if (current.model === null || current.variant === null) {
        return current.model
    }
    return current.model.slice(0, -(current.variant.length + 1))
}
