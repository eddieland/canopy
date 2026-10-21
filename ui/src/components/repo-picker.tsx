import { Check, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
    Command,
    CommandEmpty,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { reposSummary } from '@/lib/repo-filter'
import { cn } from '@/lib/utils'

// The item that stands for every repository: words no repository's name has, since a name holds no space.
const EVERY = 'every repository'

/**
 * A filter by repository, for a workspace of any size (DESIGN.md, the repository picker): a button saying what is
 * chosen (`reposSummary`), opening `repos` in a list a field narrows, each checked while chosen, under
 * `every repository`, which clears them. Picking one adds or takes it away and keeps the list open, so several are
 * chosen in one go; Escape or a click outside closes it. What was chosen as it opened is listed first, so a long list
 * keeps it in reach, and no item moves under the pointer while it is open.
 */
export function RepoFilter({
    repos,
    chosen,
    onChoose,
}: {
    /** The repositories to offer, sorted; those chosen among them. */
    repos: readonly string[]
    /** The repositories chosen, sorted; none filters nothing. */
    chosen: readonly string[]
    /** Hears the repositories chosen once one is picked. */
    onChoose: (chosen: string[]) => void
}) {
    const [open, setOpen] = useState(false)
    const [first, setFirst] = useState<readonly string[]>([])
    const summary = reposSummary(chosen)
    const rest = repos.filter((r) => !first.includes(r))

    function toggle(repo: string) {
        onChoose(chosen.includes(repo) ? chosen.filter((r) => r !== repo) : [...chosen, repo].toSorted())
    }

    return (
        <Popover
            open={open}
            onOpenChange={(next) => {
                if (next) {
                    setFirst(chosen.filter((r) => repos.includes(r)))
                }
                setOpen(next)
            }}
        >
            <PickerButton label={`Filter by repository: ${summary}`} quiet={chosen.length === 0}>
                {summary}
            </PickerButton>
            <PickerList>
                <RepoItem value={EVERY} checked={chosen.length === 0} onSelect={() => onChoose([])}>
                    {EVERY}
                </RepoItem>
                <CommandSeparator />
                {first.map((r) => (
                    <RepoItem key={r} value={r} checked={chosen.includes(r)} onSelect={() => toggle(r)}>
                        {r}
                    </RepoItem>
                ))}
                {first.length > 0 && rest.length > 0 && <CommandSeparator />}
                {rest.map((r) => (
                    <RepoItem key={r} value={r} checked={chosen.includes(r)} onSelect={() => toggle(r)}>
                        {r}
                    </RepoItem>
                ))}
            </PickerList>
        </Popover>
    )
}

/**
 * One repository of `choices`, in a form: the same button and list as `RepoFilter`, `null` among the choices standing
 * for every repository. Picking one sets it and closes the list.
 */
export function RepoSelect({
    choices,
    value,
    onValue,
    label,
}: {
    /** The repositories to offer, in order, `null` for every one. */
    choices: readonly (string | null)[]
    /** The one chosen, `null` for every repository. */
    value: string | null
    /** Hears the one picked. */
    onValue: (repo: string | null) => void
    /** What the choice is, for a screen reader, which hears the button as it and then what is chosen. */
    label: string
}) {
    const [open, setOpen] = useState(false)
    const summary = value ?? EVERY
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PickerButton label={`${label}: ${summary}`} quiet={false}>
                {summary}
            </PickerButton>
            <PickerList>
                {choices.map((name) => (
                    <RepoItem
                        key={name ?? EVERY}
                        value={name ?? EVERY}
                        checked={name === value}
                        onSelect={() => {
                            onValue(name)
                            setOpen(false)
                        }}
                    >
                        {name ?? EVERY}
                    </RepoItem>
                ))}
            </PickerList>
        </Popover>
    )
}

/** The button that opens a picker, saying what is chosen; `quiet`, in `muted-foreground`, while it filters nothing. */
function PickerButton({ label, quiet, children }: { label: string; quiet: boolean; children: ReactNode }) {
    return (
        <PopoverTrigger asChild>
            <Button
                variant="outline"
                size="sm"
                aria-label={label}
                className={cn('max-w-64 font-mono text-xs font-normal', quiet && 'text-muted-foreground')}
            >
                <span className="truncate">{children}</span>
                <ChevronDown aria-hidden className="size-3 text-muted-foreground" />
            </Button>
        </PopoverTrigger>
    )
}

/** A picker's open list, under the field that narrows it, its width the widest of the button and 16rem. */
function PickerList({ children }: { children: ReactNode }) {
    return (
        <PopoverContent align="start" className="w-auto max-w-80 min-w-(--radix-popover-trigger-width) p-0">
            {/* What is typed is found anywhere in a name, as the page's own filter field finds words, rather than by
                cmdk's fuzzy match, which would find `web` in worker-backend. */}
            <Command label="Find a repository" filter={holds} className="min-w-64">
                {/* cmdk names the field by the command's label, and the list by its own. */}
                <CommandInput placeholder="Find a repository" />
                <CommandList label="Repositories">
                    <CommandEmpty>no repository has that name</CommandEmpty>
                    {children}
                </CommandList>
            </Command>
        </PopoverContent>
    )
}

/** How an item ranks for what is typed in the field: 1 when its name holds it, else 0, which hides it. */
function holds(value: string, search: string): number {
    return value.includes(search.trim().toLowerCase()) ? 1 : 0
}

/** A repository in a picker's list, with a check at its left while it is chosen. */
function RepoItem({
    value,
    checked,
    onSelect,
    children,
}: {
    value: string
    checked: boolean
    onSelect: () => void
    children: ReactNode
}) {
    return (
        <CommandItem value={value} onSelect={onSelect} aria-checked={checked} className="font-mono text-xs">
            <span className="flex size-4 items-center justify-center">
                {checked && <Check aria-hidden className="size-4 text-accent" />}
            </span>
            <span className="truncate">{children}</span>
        </CommandItem>
    )
}
