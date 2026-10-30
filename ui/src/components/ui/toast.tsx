// shadcn/ui Toast, Radix base, ported by hand; see button.tsx. shadcn now ships sonner in its place, a dependency of
// its own; Radix's Toast is already in the radix-ui package. Only the parts the toaster uses, on `surface` with a
// palette's edge and floating shadow (ui/DESIGN.md, "Shape and space").
import { Toast as ToastPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** Holds the toasts and their viewport: how long each shows, and that a swipe down closes one. */
function ToastProvider(props: ComponentProps<typeof ToastPrimitive.Provider>) {
    return <ToastPrimitive.Provider swipeDirection="down" {...props} />
}

/**
 * Where the toasts show, stacked at the bottom center of the window, the newest last. F8 moves the focus to it, and
 * Escape there closes the toast focused. It is a landmark a screen reader can find even while empty.
 */
function ToastViewport({ className, ...props }: ComponentProps<typeof ToastPrimitive.Viewport>) {
    return (
        <ToastPrimitive.Viewport
            data-slot="toast-viewport"
            className={cn(
                'fixed bottom-4 left-1/2 z-50 flex w-80 max-w-[calc(100vw-2rem)] -translate-x-1/2 flex-col gap-2',
                'outline-none',
                className,
            )}
            {...props}
        />
    )
}

/**
 * One toast. A screen reader announces it as it opens. It closes when its time runs out, which the pointer over it
 * or the focus in it holds off, or when swiped down. It rises in and fades out (`animate-toast`).
 */
function Toast({ className, ...props }: ComponentProps<typeof ToastPrimitive.Root>) {
    return (
        <ToastPrimitive.Root
            data-slot="toast"
            className={cn(
                'animate-toast flex items-start gap-2 rounded-md border border-edge bg-surface px-3 py-2',
                'text-foreground shadow-float',
                'outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
                'data-[swipe=move]:translate-y-(--radix-toast-swipe-move-y) data-[swipe=cancel]:translate-y-0',
                'data-[swipe=end]:translate-y-(--radix-toast-swipe-end-y)',
                className,
            )}
            {...props}
        />
    )
}

/** What the toast says happened, which a screen reader reads first. */
function ToastTitle({ className, ...props }: ComponentProps<typeof ToastPrimitive.Title>) {
    return <ToastPrimitive.Title data-slot="toast-title" className={cn('text-sm', className)} {...props} />
}

/** The line under the title, which a screen reader reads after it. */
function ToastDescription(props: ComponentProps<typeof ToastPrimitive.Description>) {
    return <ToastPrimitive.Description data-slot="toast-description" {...props} />
}

export { Toast, ToastDescription, ToastProvider, ToastTitle, ToastViewport }
