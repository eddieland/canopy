import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * The lightswitch rave, an Easter egg (src/components/shell/rave.tsx): flipped on by the light switch in the Settings
 * Fun panel's header, the lights go off and on over the whole app, with party beams sweeping through them, until the
 * switch is flipped back. Off until then. Kept in localStorage like the theme, so it outlasts a reload, and synced
 * across tabs, so every tab raves together.
 */

/** Whether the rave is on. */
export type RaveSetting = 'on' | 'off'

/** Where localStorage keeps the setting. */
export const STORAGE_KEY = 'canopy-rave'
/** The setting until the light switch is flipped: off. */
export const DEFAULT: RaveSetting = 'off'

/** The setting as stored, or the default for anything it does not recognize. */
export function parseRave(raw: string | null): RaveSetting {
    return raw === 'on' || raw === 'off' ? raw : DEFAULT
}

/** Whether the rave is on. Re-renders on a change from this tab or another. */
export function useRave(): RaveSetting {
    return useStoredSetting(setting)
}

/**
 * Calls `listener` each time the rave starts, from this tab or another, never for a rave already on when it is called.
 * Returns the function that stops it.
 */
export function onRaveStart(listener: () => void): () => void {
    return setting.subscribe(() => {
        if (setting.get() === 'on') {
            listener()
        }
    })
}

/** Stores the setting and applies it now. */
export function setRave(next: RaveSetting): void {
    setting.set(next)
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseRave, serialize: (value: RaveSetting) => value })
