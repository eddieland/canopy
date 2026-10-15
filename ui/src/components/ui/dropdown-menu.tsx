// shadcn/ui DropdownMenu, Radix base, ported by hand; see button.tsx. Only the parts the UI uses: no checkbox, radio,
// or sub-menus. shadcn's `bg-accent` focus tint is `surface-raised` here (DESIGN.md), it has no shadow but its
// hairline, and it does not animate, so it opens as fast as the links it holds.
import { DropdownMenu as DropdownMenuPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** A menu that opens from its trigger. Escape or a click outside closes it, and the focus goes back to the trigger. */
function DropdownMenu(props: ComponentProps<typeof DropdownMenuPrimitive.Root>) {
    return <DropdownMenuPrimitive.Root data-slot="dropdown-menu" {...props} />
}

/** What opens its `DropdownMenu`. Radix sets its `aria-expanded` and `aria-haspopup`. */
function DropdownMenuTrigger(props: ComponentProps<typeof DropdownMenuPrimitive.Trigger>) {
    return <DropdownMenuPrimitive.Trigger data-slot="dropdown-menu-trigger" {...props} />
}

/**
 * The open menu, over the page beside its trigger, on `surface` with a hairline. As tall as the window leaves room
 * for, then it scrolls. Its children are rendered only while it is open.
 */
function DropdownMenuContent({
    className,
    sideOffset = 4,
    ...props
}: ComponentProps<typeof DropdownMenuPrimitive.Content>) {
    return (
        <DropdownMenuPrimitive.Portal>
            <DropdownMenuPrimitive.Content
                data-slot="dropdown-menu-content"
                sideOffset={sideOffset}
                className={cn(
                    'z-50 max-h-(--radix-dropdown-menu-content-available-height) min-w-32 overflow-x-hidden',
                    'overflow-y-auto rounded-md border bg-surface p-1 text-foreground',
                    'origin-(--radix-dropdown-menu-content-transform-origin)',
                    className,
                )}
                {...props}
            />
        </DropdownMenuPrimitive.Portal>
    )
}

/** One item in the menu; with `asChild`, a link. The arrow keys move between items, and Enter follows one. */
function DropdownMenuItem({ className, ...props }: ComponentProps<typeof DropdownMenuPrimitive.Item>) {
    return (
        <DropdownMenuPrimitive.Item
            data-slot="dropdown-menu-item"
            className={cn(
                'relative flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden',
                'select-none focus:bg-surface-raised data-disabled:pointer-events-none data-disabled:opacity-50',
                '[&_svg]:pointer-events-none [&_svg]:shrink-0',
                className,
            )}
            {...props}
        />
    )
}

export { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger }
