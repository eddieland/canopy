// shadcn/ui Button, Radix base, Vega style (components.json), ported by hand because the registry was unreachable
// when this was set up. Its style classes are inlined and its per-theme overrides replaced with tokens (ui/DESIGN.md).
import { cva } from 'class-variance-authority'
import type { VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** The button's classes for a `variant` and a `size`, for an element that looks like a button but is not one. */
const buttonVariants = cva(
    [
        'group/button inline-flex shrink-0 items-center justify-center',
        'rounded-md border border-transparent bg-clip-padding',
        'text-sm font-medium whitespace-nowrap outline-none select-none',
        'transition-[color,background-color,border-color,box-shadow]',
        'focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
        'active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50',
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
    ],
    {
        variants: {
            variant: {
                default: 'bg-accent text-accent-foreground hover:bg-accent/85',
                outline: [
                    'border-border bg-surface-raised hover:bg-surface hover:text-foreground',
                    'aria-expanded:bg-surface aria-expanded:text-foreground',
                ],
                secondary: 'bg-surface-raised text-foreground hover:bg-surface-raised/70',
                ghost: [
                    'text-muted-foreground hover:bg-surface-raised hover:text-foreground',
                    'aria-expanded:bg-surface-raised aria-expanded:text-foreground',
                ],
                destructive: 'bg-status-failed/12 text-status-failed hover:bg-status-failed/20',
                link: 'text-accent underline-offset-4 hover:underline',
            },
            size: {
                default: 'h-9 gap-1.5 px-2.5',
                xs: "h-6 gap-1 px-2 text-xs [&_svg:not([class*='size-'])]:size-3",
                sm: 'h-8 gap-1 px-2.5',
                lg: 'h-10 gap-1.5 px-2.5',
                icon: 'size-9',
                'icon-xs': "size-6 [&_svg:not([class*='size-'])]:size-3",
                'icon-sm': 'size-8',
                'icon-lg': 'size-10',
            },
        },
        defaultVariants: {
            variant: 'default',
            size: 'default',
        },
    },
)

/** A button in one of its variants and sizes. With `asChild`, its styles go on its one child, such as a link. */
function Button({
    className,
    variant = 'default',
    size = 'default',
    asChild = false,
    ...props
}: ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
    const Comp = asChild ? Slot.Root : 'button'
    return (
        <Comp
            data-slot="button"
            data-variant={variant}
            data-size={size}
            className={cn(buttonVariants({ variant, size, className }))}
            {...props}
        />
    )
}

export { Button, buttonVariants }
