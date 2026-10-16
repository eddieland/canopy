// Radix Toolbar, wrapped by hand: shadcn has no toolbar. Its buttons and toggles take Button's ghost look at the `xs`
// sizes, as a panel header's controls do, and a toggle that is on is raised as a Toggle is (toggle.tsx). Radix gives
// the row one tab stop, with the arrow keys moving between its controls, and keeps each toggle's `aria-pressed`.
import type { VariantProps } from 'class-variance-authority'
import { Toolbar as ToolbarPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type Size = Pick<VariantProps<typeof buttonVariants>, 'size'>

const ON = 'data-[state=on]:bg-surface-raised data-[state=on]:text-foreground'

/** A row of controls over what they act on, such as an editor's formatting. Name it with `aria-label`. */
function Toolbar({ className, ...props }: ComponentProps<typeof ToolbarPrimitive.Root>) {
    return (
        <ToolbarPrimitive.Root
            data-slot="toolbar"
            className={cn('flex flex-wrap items-center gap-0.5', className)}
            {...props}
        />
    )
}

/** A button in a Toolbar, `icon-xs` unless given a size. */
function ToolbarButton({
    className,
    size = 'icon-xs',
    ...props
}: ComponentProps<typeof ToolbarPrimitive.Button> & Size) {
    return (
        <ToolbarPrimitive.Button
            data-slot="toolbar-button"
            className={cn(buttonVariants({ variant: 'ghost', size }), className)}
            {...props}
        />
    )
}

/** Toggles in a Toolbar that belong together: `single` for a choice of one, `multiple` for each on or off. */
function ToolbarToggleGroup({ className, ...props }: ComponentProps<typeof ToolbarPrimitive.ToggleGroup>) {
    return (
        <ToolbarPrimitive.ToggleGroup
            data-slot="toolbar-toggle-group"
            className={cn('flex items-center gap-0.5', className)}
            {...props}
        />
    )
}

/** One toggle in a ToolbarToggleGroup, `icon-xs` unless given a size, raised while on. */
function ToolbarToggleItem({
    className,
    size = 'icon-xs',
    ...props
}: ComponentProps<typeof ToolbarPrimitive.ToggleItem> & Size) {
    return (
        <ToolbarPrimitive.ToggleItem
            data-slot="toolbar-toggle-item"
            className={cn(buttonVariants({ variant: 'ghost', size }), ON, className)}
            {...props}
        />
    )
}

/** A hairline between a Toolbar's groups. */
function ToolbarSeparator({ className, ...props }: ComponentProps<typeof ToolbarPrimitive.Separator>) {
    return (
        <ToolbarPrimitive.Separator
            data-slot="toolbar-separator"
            className={cn('mx-1 h-4 w-px bg-border', className)}
            {...props}
        />
    )
}

export { Toolbar, ToolbarButton, ToolbarSeparator, ToolbarToggleGroup, ToolbarToggleItem }
