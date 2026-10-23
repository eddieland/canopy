// shadcn/ui Command, on cmdk, ported by hand because the registry was unreachable. Only the parts the UI uses: no
// dialog or shortcut. Its style classes are inlined and its per-theme overrides replaced with tokens: the item
// the keys are on is tinted `surface-raised`, as a menu's is (ui/DESIGN.md). Only this file imports cmdk, which gives
// a field over a list its combobox and listbox roles and its keys; Radix has no primitive for one.
import { Command as CommandPrimitive } from 'cmdk'
import { Search } from 'lucide-react'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/**
 * A list that a field above it narrows. The arrow keys move between its items from the field, and Enter picks the one
 * they are on. With `shouldFilter={false}`, the caller narrows the list itself.
 */
function Command({ className, ...props }: ComponentProps<typeof CommandPrimitive>) {
    return (
        <CommandPrimitive
            data-slot="command"
            className={cn('flex size-full flex-col overflow-hidden rounded-md bg-surface text-foreground', className)}
            {...props}
        />
    )
}

/** The field that narrows its `Command`'s list, with a magnifier at its start and a hairline under it. */
function CommandInput({ className, ...props }: ComponentProps<typeof CommandPrimitive.Input>) {
    return (
        <div data-slot="command-input-wrapper" className="flex h-9 items-center gap-2 border-b px-3">
            <Search aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            <CommandPrimitive.Input
                data-slot="command-input"
                className={cn(
                    'flex h-9 w-full rounded-md bg-transparent py-2 text-sm outline-hidden',
                    'placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50',
                    className,
                )}
                {...props}
            />
        </div>
    )
}

/** The items, scrolling past 18rem. */
function CommandList({ className, ...props }: ComponentProps<typeof CommandPrimitive.List>) {
    return (
        <CommandPrimitive.List
            data-slot="command-list"
            className={cn('max-h-72 scroll-py-1 overflow-x-hidden overflow-y-auto p-1', className)}
            {...props}
        />
    )
}

/** What the list says when the field leaves no item in it. */
function CommandEmpty({ className, ...props }: ComponentProps<typeof CommandPrimitive.Empty>) {
    return (
        <CommandPrimitive.Empty
            data-slot="command-empty"
            className={cn('py-6 text-center text-xs text-muted-foreground', className)}
            {...props}
        />
    )
}

/** Items under a heading, which a screen reader names the group by: the heading is a panel's label. */
function CommandGroup({ className, ...props }: ComponentProps<typeof CommandPrimitive.Group>) {
    return (
        <CommandPrimitive.Group
            data-slot="command-group"
            className={cn(
                'overflow-hidden [&_[cmdk-group-heading]]:panel-label [&_[cmdk-group-heading]]:px-2',
                className,
            )}
            {...props}
        />
    )
}

/** A hairline between items. */
function CommandSeparator({ className, ...props }: ComponentProps<typeof CommandPrimitive.Separator>) {
    return (
        <CommandPrimitive.Separator
            data-slot="command-separator"
            className={cn('-mx-1 my-1 h-px bg-border', className)}
            {...props}
        />
    )
}

/** One item in the list; `onSelect` hears it picked, by a click or by Enter while the keys are on it. */
function CommandItem({ className, ...props }: ComponentProps<typeof CommandPrimitive.Item>) {
    return (
        <CommandPrimitive.Item
            data-slot="command-item"
            className={cn(
                'relative flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden',
                'select-none data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50',
                'data-[selected=true]:bg-surface-raised',
                "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
                className,
            )}
            {...props}
        />
    )
}

export { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator }
