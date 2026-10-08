import { vi } from 'vitest'

/** Stubs matchMedia so `(prefers-color-scheme: dark)` matches when `dark`, and lets a test flip it later. */
export function stubSystemTheme(dark: boolean): { set(dark: boolean): void } {
    let matches = dark
    const listeners = new Set<() => void>()
    vi.stubGlobal(
        'matchMedia',
        vi.fn((query: string) => ({
            get matches() {
                return query.includes('dark') ? matches : false
            },
            media: query,
            addEventListener: (_: string, listener: () => void) => listeners.add(listener),
            removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
        })),
    )
    return {
        set(next) {
            matches = next
            for (const listener of listeners) listener()
        },
    }
}
