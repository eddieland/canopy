// shadcn/ui Sheet, Radix base, Vega style, ported by hand; see button.tsx. Only the left side, the one the rail opens
// from, and only the parts the shell uses. Its overlay is the canvas at 70%, a token, rather than shadcn's black.
import { Dialog as SheetPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** A panel that slides over the page from its edge: a dialog, so it traps the focus and Escape closes it. */
function Sheet(props: ComponentProps<typeof SheetPrimitive.Root>) {
    return <SheetPrimitive.Root data-slot="sheet" {...props} />
}

/** What opens its `Sheet`. Radix sets its `aria-expanded` and `aria-controls`. */
function SheetTrigger(props: ComponentProps<typeof SheetPrimitive.Trigger>) {
    return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />
}

/**
 * The sheet itself, over an overlay that dims the page and closes it on a click, against the window's left edge and
 * as tall as it. Its children are rendered only while it is open. It needs a `SheetTitle`, which may be `sr-only`.
 */
function SheetContent({ className, children, ...props }: ComponentProps<typeof SheetPrimitive.Content>) {
    return (
        <SheetPrimitive.Portal>
            <SheetPrimitive.Overlay data-slot="sheet-overlay" className="fixed inset-0 z-50 bg-background/70" />
            <SheetPrimitive.Content
                data-slot="sheet-content"
                className={cn(
                    'fixed inset-y-0 left-0 z-50 flex h-full w-3/4 max-w-xs flex-col border-r bg-surface outline-none',
                    className,
                )}
                {...props}
            >
                {children}
            </SheetPrimitive.Content>
        </SheetPrimitive.Portal>
    )
}

/** The sheet's name, which a screen reader announces as it opens. */
function SheetTitle(props: ComponentProps<typeof SheetPrimitive.Title>) {
    return <SheetPrimitive.Title data-slot="sheet-title" {...props} />
}

/** One line on what the sheet holds, which a screen reader reads after its title. */
function SheetDescription(props: ComponentProps<typeof SheetPrimitive.Description>) {
    return <SheetPrimitive.Description data-slot="sheet-description" {...props} />
}

export { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger }
