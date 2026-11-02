import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

import type { ResolvedTheme } from './store'

/**
 * The palette each theme draws its neutrals from, chosen apart for light and for dark. Each theme's default carries
 * the accent's hue in its canvas: lavender, a pale lavender grey with white surfaces, and indigo, a deep indigo slate.
 * Light can wear off-white, a warm paper, sage, a soft green, or Solarized's, Nord's, Gruvbox's, or Rosé Pine Dawn's
 * light base tones instead. Dark can wear grey, the neutral one the 2026-10-19 exploration drew for Mailroom, a near
 * black, forest, a deep green, plum, a dark wine purple, or Solarized's, Gruvbox's, or Monokai's dark tones. Kept in
 * localStorage and synced across tabs; the inline script in index.html applies it before first paint, and this module
 * afterwards.
 */

/** Each theme's palettes, the default first. */
export const PALETTES = {
    light: ['lavender', 'off-white', 'sage', 'solarized', 'nord', 'gruvbox', 'rose-pine'],
    dark: ['indigo', 'grey', 'black', 'forest', 'plum', 'solarized', 'gruvbox', 'monokai'],
} as const

/** A set of neutrals `T` can wear. */
export type Palette<T extends ResolvedTheme = ResolvedTheme> = (typeof PALETTES)[T][number]

/** What each palette is called where the operator picks one: Settings, and the theme toggle's card. */
export const PALETTE_LABELS: { readonly [T in ResolvedTheme]: Readonly<Record<Palette<T>, string>> } = {
    light: {
        lavender: 'Lavender',
        'off-white': 'Off-white',
        sage: 'Sage',
        solarized: 'Solarized',
        nord: 'Nord',
        gruvbox: 'Gruvbox',
        'rose-pine': 'Rosé Pine',
    },
    dark: {
        indigo: 'Indigo',
        grey: 'Grey',
        black: 'Black',
        forest: 'Forest',
        plum: 'Plum',
        solarized: 'Solarized',
        gruvbox: 'Gruvbox',
        monokai: 'Monokai',
    },
}

/** `theme`'s palettes in order, the default first, each with its label. */
export function paletteOptions<T extends ResolvedTheme>(theme: T): { value: Palette<T>; label: string }[] {
    const labels: Readonly<Record<Palette<T>, string>> = PALETTE_LABELS[theme]
    const values: readonly Palette<T>[] = PALETTES[theme]
    return values.map((value) => ({ value, label: labels[value] }))
}

/** The palette picked for each theme. */
export interface Palettes {
    /** The light theme's. */
    readonly light: Palette<'light'>
    /** The dark theme's. */
    readonly dark: Palette<'dark'>
}

/** Shared with index.html's inline script. */
export const STORAGE_KEY = 'canopy-palette'
/** Each theme's palette until the operator picks one. */
export const DEFAULT: Palettes = { light: 'lavender', dark: 'indigo' }

/** The setting as stored, as JSON, with the default for a theme it does not name or a palette that theme lacks. */
export function parsePalettes(raw: string | null): Palettes {
    let stored: unknown = null
    try {
        stored = raw === null ? null : JSON.parse(raw)
    } catch {
        // Not JSON: the defaults.
    }
    const pick = (theme: ResolvedTheme): unknown =>
        typeof stored === 'object' && stored !== null ? Reflect.get(stored, theme) : undefined
    const light = pick('light')
    const dark = pick('dark')
    return {
        light: PALETTES.light.find((palette) => palette === light) ?? DEFAULT.light,
        dark: PALETTES.dark.find((palette) => palette === dark) ?? DEFAULT.dark,
    }
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

/** Each theme's palette as stored now, for code outside React. */
export function getPalettes(): Palettes {
    return setting.get()
}

/** Picks `palette` for `theme` and applies it now, synchronously, so a view transition can snapshot the result. */
export function setPalette<T extends ResolvedTheme>(theme: T, palette: Palette<T>): void {
    const next: Palettes = { ...setting.get(), [theme]: palette }
    setting.set(next)
    apply(next)
}

/** Puts each theme's palette on <html>, where tokens.css reads it. */
function apply(next: Palettes): void {
    const root = document.documentElement
    root.dataset.lightPalette = next.light
    root.dataset.darkPalette = next.dark
}
