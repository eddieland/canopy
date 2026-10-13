// shadcn/ui ToggleGroup, Radix base, ported by hand because the registry was unreachable. Trimmed to the one look
// canopy uses, a segmented control: a row of items in a well, the picked one raised. Its variants, sizes, and
// spacing are left out until a second look needs them; its per-theme overrides are tokens (ui/DESIGN.md).
import { ToggleGroup as ToggleGroupPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/**
 * A segmented control. With `type="single"` it is a radio group: arrow keys move between the items, Tab leaves the
 * group, and pressing the item that is on turns it off, so a caller that must keep one on ignores an empty value.
 */
function ToggleGroup({ className, ...props }: ComponentProps<typeof ToggleGroupPrimitive.Root>) {
    return (
        <ToggleGroupPrimitive.Root
            data-slot="toggle-group"
            className={cn('inline-flex w-fit items-center rounded-md border bg-background p-0.5', className)}
            {...props}
        />
    )
}

function ToggleGroupItem({ className, ...props }: ComponentProps<typeof ToggleGroupPrimitive.Item>) {
    return (
        <ToggleGroupPrimitive.Item
            data-slot="toggle-group-item"
            className={cn(
                'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-sm px-2.5 text-xs whitespace-nowrap',
                'text-muted-foreground transition-[color,box-shadow] outline-none hover:text-foreground',
                'focus-visible:z-10 focus-visible:ring-3 focus-visible:ring-ring/50',
                'disabled:pointer-events-none disabled:opacity-50',
                'data-[state=on]:bg-surface-raised data-[state=on]:text-foreground data-[state=on]:shadow-xs',
                "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className,
            )}
            {...props}
        />
    )
}

export { ToggleGroup, ToggleGroupItem }
