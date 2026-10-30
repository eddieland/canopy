// shadcn/ui Dialog, Radix base, Vega style, ported by hand; see button.tsx. Only the parts the jump palette uses: no
// trigger, header, footer, or close button. Its overlay is the canvas at 70%, a token, as the sheet's is, and its box
// sits in the window's top third rather than its middle, so a list growing under the field never moves the field.
import { Dialog as DialogPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** A box over the page: it traps the focus, Escape or a click outside closes it, and the focus goes back after. */
function Dialog(props: ComponentProps<typeof DialogPrimitive.Root>) {
    return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

/**
 * The box itself, over an overlay that dims the page and closes it on a click, a sixth of the window from its top and
 * as wide as `max-w-*` says, less a gutter in a narrow window. Its children are rendered only while it is open. It
 * needs a `DialogTitle`, which may be `sr-only`.
 */
function DialogContent({ className, ...props }: ComponentProps<typeof DialogPrimitive.Content>) {
    return (
        <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay
                data-slot="dialog-overlay"
                className="fixed inset-0 z-50 bg-background/70 animate-scrim"
            />
            <DialogPrimitive.Content
                data-slot="dialog-content"
                className={cn(
                    'fixed top-[16dvh] left-1/2 z-50 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2',
                    'rounded-md border border-edge bg-surface shadow-float outline-none animate-float',
                    className,
                )}
                {...props}
            />
        </DialogPrimitive.Portal>
    )
}

/** The box's name, which a screen reader announces as it opens. */
function DialogTitle(props: ComponentProps<typeof DialogPrimitive.Title>) {
    return <DialogPrimitive.Title data-slot="dialog-title" {...props} />
}

/** One line on what the box holds, which a screen reader reads after its title. */
function DialogDescription(props: ComponentProps<typeof DialogPrimitive.Description>) {
    return <DialogPrimitive.Description data-slot="dialog-description" {...props} />
}

export { Dialog, DialogContent, DialogDescription, DialogTitle }
