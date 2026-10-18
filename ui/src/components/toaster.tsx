import { ArrowRight, Check, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { Toast, ToastDescription, ToastProvider, ToastTitle, ToastViewport } from '@/components/ui/toast'
import { ToastContext } from '@/hooks/use-toast'
import { addToast, closeToast } from '@/lib/toasts'
import type { NewToast, ToastItem } from '@/lib/toasts'
import { cn } from '@/lib/utils'

// Each tone's icon, and its color.
const TONES: Record<NewToast['tone'], { icon: LucideIcon; className: string }> = {
    done: { icon: Check, className: 'text-accent' },
    failed: { icon: X, className: 'text-status-failed' },
    moved: { icon: ArrowRight, className: 'text-accent' },
}

/** How long a toast shows, unless the pointer or the focus holds it. */
const TOAST_MS = 3000

/**
 * Gives `children` `useToast`, and shows the toasts it is asked for at the bottom center of the window: at most
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
                        <ToneIcon tone={toast.tone} />
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

function ToneIcon({ tone }: { tone: NewToast['tone'] }) {
    const { icon: Icon, className } = TONES[tone]
    return <Icon aria-hidden className={cn('mt-0.5 size-4 shrink-0', className)} />
}
