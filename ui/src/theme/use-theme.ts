import { useSyncExternalStore } from 'react'

import { getSnapshot, subscribe, type ThemeSnapshot } from './store'

/** The current theme preference and what it resolves to. Re-renders on a change from any tab or the system. */
export function useTheme(): ThemeSnapshot {
    return useSyncExternalStore(subscribe, getSnapshot)
}
