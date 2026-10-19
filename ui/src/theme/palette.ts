import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

import type { ResolvedTheme } from './store'

/**
 * The palette each theme draws its neutrals from, chosen apart for light and for dark: indigo, whose canvas carries
 * the accent's hue, or grey, the neutral one the 2026-10-19 exploration drew for Mailroom. Kept in localStorage and
 * synced across tabs; the inline script in index.html applies it before first paint, and this module afterwards.
 */

/** A set of neutrals a theme can wear. */
export type Palette = 'indigo' | 'grey'

/** The palette picked for each theme. */
export type Palettes = Readonly<Record<ResolvedTheme, Palette>>

/** Shared with index.html's inline script. */
export const STORAGE_KEY = 'canopy-palette'
/** Each theme's palette until the operator picks one. */
export const DEFAULT: Palettes = { light: 'indigo', dark: 'indigo' }

const PALETTES = new Set<string>(['indigo', 'grey'])

/** The setting as stored, as JSON, with the default for a theme it does not name or a palette it does not know. */
export function parsePalettes(raw: string | null): Palettes {
    let stored: unknown = null
    try {
        stored = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: the defaults.
    }
    const pick = (theme: ResolvedTheme): Palette => {
        const value: unknown = typeof stored === 'object' && stored !== null ? Reflect.get(stored, theme) : undefined
        return typeof value === 'string' && PALETTES.has(value) ? (value as Palette) : DEFAULT[theme]
    }
    return { light: pick('light'), dark: pick('dark') }
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parsePalettes, serialize: JSON.stringify })
/** The stored setting, applied to <html> each time it changes while a component reads it. */
const palettes: typeof setting = {
    ...setting,
    subscribe: (listener) =>
        setting.subscribe(() => {
            apply(setting.get())
            listener()
        }),
}

/** Each theme's palette. Re-renders, and puts it on <html>, on a change from this tab or another. */
export function usePalettes(): Palettes {
    return useStoredSetting(palettes)
}

/** Picks `palette` for `theme` and applies it now, synchronously, so a view transition can snapshot the result. */
export function setPalette(theme: ResolvedTheme, palette: Palette): void {
    const next = { ...setting.get(), [theme]: palette }
    setting.set(next)
    apply(next)
}

/** Puts each theme's palette on <html>, where tokens.css reads it. */
function apply(next: Palettes): void {
    const root = document.documentElement
    root.dataset.lightPalette = next.light
    root.dataset.darkPalette = next.dark
}
