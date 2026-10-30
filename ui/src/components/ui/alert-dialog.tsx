// shadcn/ui Alert Dialog, Radix base, Vega style, ported by hand; see button.tsx. Only the parts a question before
// losing work uses. Its overlay is the canvas at 70%, a token, as the sheet's is, rather than shadcn's black.
import { AlertDialog as AlertDialogPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** A question the operator must answer before going on: it traps the focus, and Escape answers it with its Cancel. */
function AlertDialog(props: ComponentProps<typeof AlertDialogPrimitive.Root>) {
    return <AlertDialogPrimitive.Root data-slot="alert-dialog" {...props} />
}

/**
 * The question itself, centred over an overlay that dims the page, which a click does not close. It needs an
 * `AlertDialogTitle` and an `AlertDialogDescription`, and takes the focus to its `AlertDialogCancel`.
 */
function AlertDialogContent({ className, ...props }: ComponentProps<typeof AlertDialogPrimitive.Content>) {
    return (
        <AlertDialogPrimitive.Portal>
            <AlertDialogPrimitive.Overlay
                data-slot="alert-dialog-overlay"
                className="fixed inset-0 z-50 bg-background/70"
            />
            <AlertDialogPrimitive.Content
                data-slot="alert-dialog-content"
                className={cn(
                    'fixed top-1/2 left-1/2 z-50 flex w-[calc(100%-2rem)] max-w-sm -translate-1/2 flex-col gap-3',
                    'rounded-md border border-edge bg-surface p-4 shadow-float outline-none',
                    className,
                )}
                {...props}
            />
        </AlertDialogPrimitive.Portal>
    )
}

/** The question, which a screen reader announces as it opens. */
function AlertDialogTitle({ className, ...props }: ComponentProps<typeof AlertDialogPrimitive.Title>) {
    return (
        <AlertDialogPrimitive.Title
            data-slot="alert-dialog-title"
            className={cn('text-sm font-semibold', className)}
            {...props}
        />
    )
}

/** What answering it either way means, which a screen reader reads after its title. */
function AlertDialogDescription({ className, ...props }: ComponentProps<typeof AlertDialogPrimitive.Description>) {
    return (
        <AlertDialogPrimitive.Description
            data-slot="alert-dialog-description"
            className={cn('text-sm text-muted-foreground', className)}
            {...props}
        />
    )
}

/** Its answers, at its foot, the safe one first. */
function AlertDialogFooter({ className, ...props }: ComponentProps<'div'>) {
    return <div data-slot="alert-dialog-footer" className={cn('flex justify-end gap-2', className)} {...props} />
}

/** The answer that goes ahead, as a destructive button: what it loses, the question says. */
function AlertDialogAction({ className, ...props }: ComponentProps<typeof AlertDialogPrimitive.Action>) {
    return (
        <AlertDialogPrimitive.Action
            data-slot="alert-dialog-action"
            className={cn(buttonVariants({ variant: 'destructive', size: 'sm' }), className)}
            {...props}
        />
    )
}

/** The answer that loses nothing, which takes the focus as the question opens, and which Escape gives too. */
function AlertDialogCancel({ className, ...props }: ComponentProps<typeof AlertDialogPrimitive.Cancel>) {
    return (
        <AlertDialogPrimitive.Cancel
            data-slot="alert-dialog-cancel"
            className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), className)}
            {...props}
        />
    )
}

export {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogTitle,
}
