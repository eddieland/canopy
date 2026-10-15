import { createContext, use } from 'react'

import type { NewToast } from '@/lib/toasts'

// What a toast does outside a `Toaster`: nothing, as there is nowhere to show it.
function ignore() {
    // Nowhere to show it.
}

/**
 * What `useToast` gives, set by the `Toaster` the shell renders. Outside one, as in a unit test, a toast goes nowhere,
 * so a component that shows one renders anywhere.
 */
export const ToastContext = createContext<(toast: NewToast) => void>(ignore)

/** A function showing a toast at the bottom center of the window, saying what an action did: `Copied branch`. */
export function useToast(): (toast: NewToast) => void {
    return use(ToastContext)
}
