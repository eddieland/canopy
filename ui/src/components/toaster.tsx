import { Check, History, X } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { Toast, ToastDescription, ToastProvider, ToastTitle, ToastViewport } from '@/components/ui/toast'
import { ToastContext } from '@/hooks/use-toast'
import { addToast, closeToast } from '@/lib/toasts'
import type { ToastItem } from '@/lib/toasts'

/** How long a toast shows, unless the pointer or the focus holds it. */
const TOAST_MS = 3000
/** How long the note of what changed while away shows: a line to read on coming back, not a confirmation. */
const NOTE_MS = 8000

/** Each tone's icon: the accent for what went as asked and for a note, `status-failed` for what did not. */
const ICONS: Record<ToastItem['tone'], ReactNode> = {
    done: <Check aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />,
    failed: <X aria-hidden className="mt-0.5 size-4 shrink-0 text-status-failed" />,
    note: <History aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />,
}

/**
 * Gives `children` `useToast`, and shows the toasts it is asked for at the bottom center of the window: at most
 * `MAX_TOASTS`, the newest last, each closing on its own after 3 seconds, or 8 for a note. `main.tsx` renders one
 * around the router.
 */
export function Toaster({
    children,
}: {
    /** What may show a toast. */
    children: ReactNode
}) {
    const [toasts, setToasts] = useState<readonly ToastItem[]>([])
    return (
        <ToastContext value={(toast) => setToasts((shown) => addToast(shown, toast))}>
            <ToastProvider duration={TOAST_MS}>
                {children}
                {toasts.map((toast) => (
                    <Toast
                        key={toast.id}
                        open={toast.open}
                        duration={toast.tone === 'note' ? NOTE_MS : undefined}
                        data-testid="toast"
                        onOpenChange={(open) => {
                            if (!open) {
                                setToasts((shown) => closeToast(shown, toast.id))
                            }
                        }}
                    >
                        {ICONS[toast.tone]}
                        <div className="min-w-0">
                            <ToastTitle>{toast.title}</ToastTitle>
                            {toast.detail !== undefined && (
                                <ToastDescription className="truncate font-mono text-xs text-muted-foreground">
                                    {toast.detail}
                                </ToastDescription>
                            )}
                        </div>
                    </Toast>
                ))}
                <ToastViewport />
            </ToastProvider>
        </ToastContext>
    )
}
