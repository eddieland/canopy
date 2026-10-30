import { Check, ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

// A picker over names a list may hold dozens of (DESIGN.md, a choice of repositories): the button that opens it, the
// list under the field that narrows it, and an item of it. The repository pickers and the runs page's model filter
// are built of these, so every such list looks and finds alike.

/** The button that opens a picker, saying what is chosen; `quiet`, in `muted-foreground`, while it filters nothing. */
export function PickerButton({ label, quiet, children }: { label: string; quiet: boolean; children: ReactNode }) {
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

/**
 * A picker's open list, under the field that narrows it, its width the widest of the button and 16rem: `find` names
 * the field, `label` the list, and `empty` is what it says when what is typed leaves nothing.
 */
export function PickerList({
    find,
    label,
    empty,
    children,
}: {
    find: string
    label: string
    empty: string
    children: ReactNode
}) {
    return (
        <PopoverContent align="start" className="w-auto max-w-80 min-w-(--radix-popover-trigger-width) p-0">
            {/* What is typed is found anywhere in a name, as the page's own filter field finds words, rather than by
                cmdk's fuzzy match, which would find `web` in worker-backend. */}
            <Command label={find} filter={holds} className="min-w-64">
                {/* cmdk names the field by the command's label, and the list by its own. */}
                <CommandInput placeholder={find} />
                <CommandList label={label}>
                    <CommandEmpty>{empty}</CommandEmpty>
                    {children}
                </CommandList>
            </Command>
        </PopoverContent>
    )
}

/** A name in a picker's list, with a check at its left while it is chosen. */
export function PickerItem({
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

/** How an item ranks for what is typed in the field: 1 when its name holds it, else 0, which hides it. */
function holds(value: string, search: string): number {
    return value.toLowerCase().includes(search.trim().toLowerCase()) ? 1 : 0
}
