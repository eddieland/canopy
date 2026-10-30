// shadcn/ui Hover Card, Radix base, ported by hand; see button.tsx. As the tooltip and the popover, it sits on
// `surface` with its palette's edge and floating shadow, and does not animate (ui/DESIGN.md). A card says more than a
// tooltip can, for what a link opens: its trigger is the link, so a click still goes there.
import { HoverCard as HoverCardPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

// As long as a tooltip waits (tooltip.tsx), so a pointer crossing the header opens nothing on its way.
const OPEN_MS = 500
// Long enough to move the pointer from the trigger onto the card without it closing.
const CLOSE_MS = 150

/**
 * A card about a link, opened by hovering it or by the keyboard's focus on it, and closed by leaving both it and the
 * card, or by Escape. Nothing in it is reached only there: what it shows is on the page the link opens.
 */
function HoverCard({
    openDelay = OPEN_MS,
    closeDelay = CLOSE_MS,
    ...props
}: ComponentProps<typeof HoverCardPrimitive.Root>) {
    return <HoverCardPrimitive.Root data-slot="hover-card" openDelay={openDelay} closeDelay={closeDelay} {...props} />
}

/** What opens its `HoverCard`: with `asChild`, its one child, a link. */
function HoverCardTrigger(props: ComponentProps<typeof HoverCardPrimitive.Trigger>) {
    return <HoverCardPrimitive.Trigger data-slot="hover-card-trigger" {...props} />
}

/** The open card, over the page beside its trigger, on `surface` with a hairline. */
function HoverCardContent({
    className,
    align = 'end',
    sideOffset = 6,
    ...props
}: ComponentProps<typeof HoverCardPrimitive.Content>) {
    return (
        <HoverCardPrimitive.Portal>
            <HoverCardPrimitive.Content
                data-slot="hover-card-content"
                align={align}
                sideOffset={sideOffset}
                collisionPadding={8}
                className={cn(
                    'z-50 w-96 origin-(--radix-hover-card-content-transform-origin)',
                    'rounded-md border border-edge bg-surface p-3 text-foreground shadow-float outline-hidden',
                    'animate-float',
                    className,
                )}
                {...props}
            />
        </HoverCardPrimitive.Portal>
    )
}

export { HoverCard, HoverCardContent, HoverCardTrigger }
