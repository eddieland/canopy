// shadcn/ui DropdownMenu, Radix base, ported by hand; see button.tsx. Only the parts the UI uses: no sub-menus.
// shadcn's `bg-accent` focus tint is `surface-raised` here (DESIGN.md), it floats in its palette's edge and shadow,
// and it does not animate, so it opens as fast as the links it holds.
import { Check } from 'lucide-react'
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
                    'overflow-y-auto rounded-md border border-edge bg-surface p-1 text-foreground shadow-float',
                    'origin-(--radix-dropdown-menu-content-transform-origin) animate-float-in',
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

/** Items of which one is chosen, as a style is; `value` is the chosen one's and `onValueChange` hears a new choice. */
function DropdownMenuRadioGroup(props: ComponentProps<typeof DropdownMenuPrimitive.RadioGroup>) {
    return <DropdownMenuPrimitive.RadioGroup data-slot="dropdown-menu-radio-group" {...props} />
}

/** One choice in a DropdownMenuRadioGroup, with a check at its left while it is the chosen one. */
function DropdownMenuRadioItem({
    className,
    children,
    ...props
}: ComponentProps<typeof DropdownMenuPrimitive.RadioItem>) {
    return (
        <DropdownMenuPrimitive.RadioItem
            data-slot="dropdown-menu-radio-item"
            className={cn(
                'relative flex cursor-default items-center gap-2 rounded-sm py-1.5 pr-2 pl-8 text-sm outline-hidden',
                'select-none focus:bg-surface-raised data-disabled:pointer-events-none data-disabled:opacity-50',
                '[&_svg]:pointer-events-none [&_svg]:shrink-0',
                className,
            )}
            {...props}
        >
            <span className="pointer-events-none absolute left-2 flex size-4 items-center justify-center">
                <DropdownMenuPrimitive.ItemIndicator>
                    <Check className="size-4 text-accent" />
                </DropdownMenuPrimitive.ItemIndicator>
            </span>
            {children}
        </DropdownMenuPrimitive.RadioItem>
    )
}

/**
 * An option in the menu that is on or off, with a check at its left while on; `checked` is its state and
 * `onCheckedChange` hears it flip. Picking one closes the menu unless its `onSelect` prevents that. With `bare`, it
 * draws no check and leaves its children to show its state, as an icon alone does by its `data-state`.
 */
function DropdownMenuCheckboxItem({
    className,
    children,
    bare = false,
    ...props
}: ComponentProps<typeof DropdownMenuPrimitive.CheckboxItem> & { bare?: boolean }) {
    if (bare) {
        return (
            <DropdownMenuPrimitive.CheckboxItem
                data-slot="dropdown-menu-checkbox-item"
                className={cn(
                    'relative flex cursor-default items-center justify-center rounded-sm p-1.5 outline-hidden',
                    'select-none focus:bg-surface-raised data-disabled:pointer-events-none data-disabled:opacity-50',
                    '[&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
                    className,
                )}
                {...props}
            >
                {children}
            </DropdownMenuPrimitive.CheckboxItem>
        )
    }
    return (
        <DropdownMenuPrimitive.CheckboxItem
            data-slot="dropdown-menu-checkbox-item"
            className={cn(
                'relative flex cursor-default items-center gap-2 rounded-sm py-1.5 pr-2 pl-8 text-sm outline-hidden',
                'select-none focus:bg-surface-raised data-disabled:pointer-events-none data-disabled:opacity-50',
                '[&_svg]:pointer-events-none [&_svg]:shrink-0',
                className,
            )}
            {...props}
        >
            <span className="pointer-events-none absolute left-2 flex size-4 items-center justify-center">
                <DropdownMenuPrimitive.ItemIndicator>
                    <Check className="size-4 text-accent" />
                </DropdownMenuPrimitive.ItemIndicator>
            </span>
            {children}
        </DropdownMenuPrimitive.CheckboxItem>
    )
}

/** A hairline between a menu's groups. */
function DropdownMenuSeparator({ className, ...props }: ComponentProps<typeof DropdownMenuPrimitive.Separator>) {
    return (
        <DropdownMenuPrimitive.Separator
            data-slot="dropdown-menu-separator"
            className={cn('-mx-1 my-1 h-px bg-border', className)}
            {...props}
        />
    )
}

export {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
}
