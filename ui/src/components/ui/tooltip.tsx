// shadcn/ui Tooltip, Radix base, ported by hand; see button.tsx. Each tooltip brings its own provider, as shadcn's
// does, so a component that shows one renders anywhere, a unit test included. Like the dropdown menu it sits on
// `surface` with its palette's edge and floating shadow, and does not animate; it has no arrow, which the edge makes
// needless.
import { Tooltip as TooltipPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

// Long enough that a pointer crossing a list opens nothing on its way, about as long as a browser's own `title` waits.
const DELAY_MS = 500

/**
 * A short text about its trigger, opened by hovering it or by the keyboard's focus on it, and closed by Escape, by
 * leaving it, or by a click. Radix sets the trigger's `aria-describedby` while it is open.
 */
function Tooltip({ delayDuration = DELAY_MS, ...props }: ComponentProps<typeof TooltipPrimitive.Root>) {
    return (
        <TooltipPrimitive.Provider delayDuration={delayDuration}>
            <TooltipPrimitive.Root data-slot="tooltip" {...props} />
        </TooltipPrimitive.Provider>
    )
}

/** What opens its `Tooltip`: with `asChild`, its one child. */
function TooltipTrigger(props: ComponentProps<typeof TooltipPrimitive.Trigger>) {
    return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
}

/**
 * The open tooltip, over the page beside its trigger, in `text-xs` on `surface` with a hairline. It keeps the line
 * breaks of what it holds and wraps a long word rather than run off the window.
 */
function TooltipContent({ className, sideOffset = 4, ...props }: ComponentProps<typeof TooltipPrimitive.Content>) {
    return (
        <TooltipPrimitive.Portal>
            <TooltipPrimitive.Content
                data-slot="tooltip-content"
                sideOffset={sideOffset}
                collisionPadding={8}
                className={cn(
                    'z-50 max-w-sm rounded-md border border-edge bg-surface px-2 py-1 text-xs text-foreground',
                    'shadow-float',
                    'break-words whitespace-pre-line',
                    className,
                )}
                {...props}
            />
        </TooltipPrimitive.Portal>
    )
}

export { Tooltip, TooltipContent, TooltipTrigger }
