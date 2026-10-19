// shadcn/ui Dialog, Radix base, Vega style, ported by hand; see button.tsx. Only the parts the list of keys uses. Its
// overlay is the canvas at 70%, a token, as the sheet's and the alert dialog's are, rather than shadcn's black.
import { XIcon } from 'lucide-react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** A window over the page: it traps the focus, and Escape, a click outside, or its close button closes it. */
function Dialog(props: ComponentProps<typeof DialogPrimitive.Root>) {
    return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

/**
 * The window itself, centred over an overlay that dims the page, with a ghost close button in its top right corner.
 * It needs a `DialogTitle` and a `DialogDescription`, which may be `sr-only`.
 */
function DialogContent({ className, children, ...props }: ComponentProps<typeof DialogPrimitive.Content>) {
    return (
        <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay data-slot="dialog-overlay" className="fixed inset-0 z-50 bg-background/70" />
            <DialogPrimitive.Content
                data-slot="dialog-content"
                className={cn(
                    'fixed top-1/2 left-1/2 z-50 flex w-[calc(100%-2rem)] max-w-md -translate-1/2 flex-col gap-3',
                    'rounded-md border bg-surface p-4 outline-none',
                    className,
                )}
                {...props}
            >
                {children}
                <DialogPrimitive.Close
                    data-slot="dialog-close"
                    className={cn(buttonVariants({ variant: 'ghost', size: 'icon-sm' }), 'absolute top-2 right-2')}
                >
                    <XIcon aria-hidden />
                    <span className="sr-only">Close</span>
                </DialogPrimitive.Close>
            </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
    )
}

/** The window's name, which a screen reader announces as it opens. */
function DialogTitle({ className, ...props }: ComponentProps<typeof DialogPrimitive.Title>) {
    return (
        <DialogPrimitive.Title data-slot="dialog-title" className={cn('text-sm font-semibold', className)} {...props} />
    )
}

/** One line on what the window holds, which a screen reader reads after its title. */
function DialogDescription({ className, ...props }: ComponentProps<typeof DialogPrimitive.Description>) {
    return (
        <DialogPrimitive.Description
            data-slot="dialog-description"
            className={cn('text-sm text-muted-foreground', className)}
            {...props}
        />
    )
}

export { Dialog, DialogContent, DialogDescription, DialogTitle }
