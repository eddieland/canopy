// shadcn/ui Popover, Radix base, ported by hand because the registry was unreachable. Only the parts the UI uses: no
// anchor, header, title, or description. As the dropdown menu, it sits on `surface` with its edge and floating shadow,
// and does not animate, so it opens as fast as what it holds (ui/DESIGN.md).
import { Popover as PopoverPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** A panel that opens from its trigger. Escape or a click outside closes it, and the focus goes back to the trigger. */
function Popover(props: ComponentProps<typeof PopoverPrimitive.Root>) {
    return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

/** What opens its `Popover`. Radix sets its `aria-expanded`, `aria-haspopup`, and `aria-controls`. */
function PopoverTrigger(props: ComponentProps<typeof PopoverPrimitive.Trigger>) {
    return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

/**
 * The open panel, over the page beside its trigger, on `surface` with a hairline. The focus moves into it as it opens.
 * Its children are rendered only while it is open.
 */
function PopoverContent({
    className,
    align = 'center',
    sideOffset = 4,
    ...props
}: ComponentProps<typeof PopoverPrimitive.Content>) {
    return (
        <PopoverPrimitive.Portal>
            <PopoverPrimitive.Content
                data-slot="popover-content"
                align={align}
                sideOffset={sideOffset}
                className={cn(
                    'z-50 w-72 origin-(--radix-popover-content-transform-origin)',
                    'rounded-md border border-edge bg-surface p-4 text-foreground shadow-float outline-hidden',
                    className,
                )}
                {...props}
            />
        </PopoverPrimitive.Portal>
    )
}

export { Popover, PopoverContent, PopoverTrigger }
