import { Check, X } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { Toast, ToastDescription, ToastProvider, ToastTitle, ToastViewport } from '@/components/ui/toast'
import { ToastContext } from '@/hooks/use-toast'
import { addToast, closeToast } from '@/lib/toasts'
import type { ToastItem } from '@/lib/toasts'
import { cn } from '@/lib/utils'

/** How long a toast shows, unless the pointer or the focus holds it. */
const TOAST_MS = 3000

/**
 * Gives `children` `useToast`, and shows the toasts it is asked for over the page's bottom right corner: at most
 * `MAX_TOASTS`, the newest last, each closing on its own after 3 seconds. `main.tsx` renders one around the router.
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
                        data-testid="toast"
                        onOpenChange={(open) => {
                            if (!open) {
                                setToasts((shown) => closeToast(shown, toast.id))
                            }
                        }}
                    >
                        {toast.tone === 'done' ? (
                            <Check aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
                        ) : (
                            <X aria-hidden className="mt-0.5 size-4 shrink-0 text-status-failed" />
                        )}
                        <div className="min-w-0">
                            <ToastTitle>{toast.title}</ToastTitle>
                            {toast.detail !== undefined && (
                                <ToastDescription
                                    className={cn('line-clamp-2 font-mono text-xs break-all', 'text-muted-foreground')}
                                >
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
