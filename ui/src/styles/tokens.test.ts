import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { PALETTES } from '@/theme/palette'
import type { ResolvedTheme } from '@/theme/store'

// Every color token that is text, read against what it sits on, in both themes, at WCAG AA for small text
// (ui/DESIGN.md, "Tokens"). The colors are the ones tokens.css writes, converted from oklch as a browser does; a tint
// is the token at that strength over its base, as Tailwind's `bg-status-failed/12` paints it.

const AA = 4.5
// WCAG's non-text contrast: a chart's marks against what they sit on.
const GRAPHICS = 3

type Rgb = [number, number, number]
type Oklch = [number, number, number]
type Theme = Record<string, Oklch>

// How a theme inks the nav's active label: in the token a palette that draws the highlight as a solid block names
// (`--nav-on-ink`), else in its section's color shaded toward black by `--nav-label-shade`, on the highlight's tint.
interface NavLabel {
    ink: string | undefined
    shade: number
}

const css = readFileSync(resolve(import.meta.dirname, 'tokens.css'), 'utf8')
// Each theme's default, then every other palette in PALETTES, which sets some tokens over its theme's default, so each
// is that default with those replaced. A palette with no rule here fails, as theme() throws.
const DEFAULTS: Record<ResolvedTheme, Theme> = { light: theme(':root'), dark: theme('.dark') }
const THEMES: Record<string, Theme> = Object.fromEntries(
    (['light', 'dark'] as const).flatMap((mode) =>
        PALETTES[mode].map((palette, index) => [
            `${palette} ${mode}`,
            index === 0 ? DEFAULTS[mode] : { ...DEFAULTS[mode], ...theme(paletteRule(mode, palette)) },
        ]),
    ),
)
// The same, for the nav's active label: a palette keeps its default's shade unless it sets its own.
const NAV_DEFAULTS: Record<ResolvedTheme, NavLabel> = { light: navLabel(':root', 0), dark: navLabel('.dark', 0) }
const NAV: Record<string, NavLabel> = Object.fromEntries(
    (['light', 'dark'] as const).flatMap((mode) =>
        PALETTES[mode].map((palette, index) => [
            `${palette} ${mode}`,
            index === 0 ? NAV_DEFAULTS[mode] : navLabel(paletteRule(mode, palette), NAV_DEFAULTS[mode].shade),
        ]),
    ),
)

// Text tokens, each read on the canvas, a surface, and a raised surface.
const TEXT = [
    'foreground',
    'muted-foreground',
    'accent',
    'status-running',
    'status-blocked',
    'status-stopped',
    'status-done',
    'status-failed',
    'section-attention',
    'section-workspace',
    'section-tickets',
    'section-tasks',
    'section-pull-requests',
    'section-chores',
    'section-reports',
    'section-memory',
    'section-settings',
    'diff-add',
    'diff-del',
    'syntax-key',
    'syntax-string',
    'syntax-number',
    'syntax-literal',
    'proposal-change',
    'proposal-decline',
    'proposal-ask',
]
const BASES = ['background', 'surface', 'surface-raised']
const SECTIONS = TEXT.filter((name) => name.startsWith('section-'))
// The nav's highlight on the section shown (`SECTION_TINT` in src/lib/sections.ts).
const NAV_TINT = 0.24
// The rail's own fill over the canvas (`bg-surface/60` in src/components/shell/app-shell.tsx).
const RAIL = 0.6

// The spend chart's series: fills on a panel's surface, never text (ui/DESIGN.md, "Tokens").
const SERIES = [
    'spend-overseer',
    'spend-idle',
    'spend-workers',
    'spend-plans',
    'spend-chores',
    'spend-reviews',
    'spend-tasks',
    'spend-dry-run',
    'spend-outside',
    // The CI page's red checks, the same kind of fill.
    'check-1',
    'check-2',
    'check-3',
    'check-4',
    'check-other',
    // The Reviews page's first reviews by wait, the same kind of fill.
    'wait-1',
    'wait-2',
    'wait-3',
    'wait-4',
    // The checklist page's answers, the same kind of fill.
    'answer-pass',
    'answer-fixed',
    'answer-held',
    'answer-na',
    'answer-unanswered',
]
// A transcript's context chart: fills on a panel's surface, and on the raised one behind the call picked.
const CONTEXT = ['context-carried', 'context-added']

// Inline code's chip: its own ink at the strength tokens.css mixes it (`--code-chip`), over what the text sits on.
const CODE_CHIP = codeChip()
// The operator's bubble in a conversation (`TONE` in src/components/conversation.tsx).
const REPLY = 0.18

// A status word also sits on its own tint: a chip (10%) in a selected inbox row (the accent at 14%), a destructive
// button (12%, 20% hovered), a question's bubble (12%) on a raised surface. So does a feedback plan's proposal, a chip.
const TINTED = TEXT.filter((name) => name.startsWith('status-') || name.startsWith('proposal-'))

describe.each(Object.entries(THEMES))('%s theme', (themeName, colors) => {
    const coords = (name: string): Oklch => {
        const value = colors[name]
        if (value === undefined) {
            throw new Error(`tokens.css sets no --${name} in this theme`)
        }
        return value
    }
    const token = (name: string): Rgb => srgb(...coords(name))

    it('reads every text token on the canvas and surfaces', () => {
        const low = TEXT.flatMap((name) =>
            BASES.map((base) => below(`${name} on ${base}`, token(name), token(base))),
        ).filter((line) => line !== null)
        expect(low).toEqual([])
    })

    it('reads every status and proposal on its own tint', () => {
        const selected = over(token('accent'), 0.14, token('surface'))
        const low = TINTED.flatMap((name) => {
            const fg = token(name)
            return [
                below(`${name} on its 10% in a selected row`, fg, over(fg, 0.1, selected)),
                below(`${name} on its 12% on surface-raised`, fg, over(fg, 0.12, token('surface-raised'))),
                below(`${name} on its 20% on surface`, fg, over(fg, 0.2, token('surface'))),
            ]
        }).filter((line) => line !== null)
        expect(low).toEqual([])
    })

    // The rail is the surface at 60% over the canvas beside the page, and the surface itself in the sheet under `lg`.
    // A shade toward black, as `color-mix(in oklab, ..., black)` paints it, scales the color's lightness and chroma.
    it("reads the nav's active label on its highlight", () => {
        const rails = { rail: over(token('surface'), RAIL, token('background')), sheet: token('surface') }
        const nav = NAV[themeName]
        if (nav === undefined) {
            throw new Error(`no nav label for ${themeName}`)
        }
        const { ink, shade } = nav
        const low = SECTIONS.flatMap((section) => {
            if (ink !== undefined) {
                return [below(`${ink} on ${section}'s block`, token(ink), token(section))]
            }
            const [l, c, h] = coords(section)
            const label = srgb(l * (1 - shade), c * (1 - shade), h)
            return Object.entries(rails).map(([where, rail]) =>
                below(`${section}'s label on its 24% in the ${where}`, label, over(token(section), NAV_TINT, rail)),
            )
        }).filter((line) => line !== null)
        expect(low).toEqual([])
    })

    it("reads a diff's marks on their line's tint", () => {
        const low = ['diff-add', 'diff-del']
            .map((name) => below(`${name} on its 12%`, token(name), over(token(name), 0.12, token('surface'))))
            .filter((line) => line !== null)
        expect(low).toEqual([])
    })

    it("reads a diff's code colors on an added or removed line's tint", () => {
        const code = ['foreground', 'muted-foreground', ...TEXT.filter((name) => name.startsWith('syntax-'))]
        const low = code
            .flatMap((name) =>
                ['diff-add', 'diff-del'].map((line) =>
                    below(`${name} on ${line} 12%`, token(name), over(token(line), 0.12, token('surface'))),
                ),
            )
            .filter((line) => line !== null)
        expect(low).toEqual([])
    })

    it("sets the spend chart's series apart from the surface they sit on", () => {
        const low = SERIES.map((name) => {
            const ratio = contrast(token(name), token('surface'))
            return ratio < GRAPHICS ? `${name} on surface: ${ratio.toFixed(2)}:1` : null
        }).filter((line) => line !== null)
        expect(low).toEqual([])
    })

    it("sets the context chart's fills apart from the surfaces they sit on", () => {
        const low = CONTEXT.flatMap((name) =>
            ['surface', 'surface-raised'].map((base) => {
                const ratio = contrast(token(name), token(base))
                return ratio < GRAPHICS ? `${name} on ${base}: ${ratio.toFixed(2)}:1` : null
            }),
        ).filter((line) => line !== null)
        expect(low).toEqual([])
    })

    it('reads the accent foreground on the accent', () => {
        expect(contrast(token('accent-foreground'), token('accent'))).toBeGreaterThanOrEqual(AA)
    })

    // Code in a line sits on a tint of its ink: on the canvas and the panels, in each bubble of a conversation, the
    // operator's on the accent's 18%, and in canopy's note, which is muted.
    it('reads inline code on its chip', () => {
        const ink = token('foreground')
        const muted = token('muted-foreground')
        const grounds = {
            ...Object.fromEntries(BASES.map((base) => [base, token(base)])),
            'a reply': over(token('accent'), REPLY, token('surface')),
        }
        const low = [
            ...Object.entries(grounds).map(([where, ground]) =>
                below(`code on its chip on ${where}`, ink, over(ink, CODE_CHIP, ground)),
            ),
            below('muted code on its chip in a note', muted, over(muted, CODE_CHIP, token('surface'))),
        ].filter((line) => line !== null)
        expect(low).toEqual([])
    })

    // The approved band, a live readout, and the newer-build notice set accent text on the accent's own 14%.
    it('reads the accent on its own tint', () => {
        const low = ['surface', 'surface-raised']
            .map((base) =>
                below(`accent on its 14% on ${base}`, token('accent'), over(token('accent'), 0.14, token(base))),
            )
            .filter((line) => line !== null)
        expect(low).toEqual([])
    })
})

// A palette whose every line is mono sets code at its line's size: a smaller copy of the same face reads as a mistake.
describe('inline code size', () => {
    it.each(
        (['light', 'dark'] as const).flatMap((mode) =>
            PALETTES[mode].slice(1).map((palette) => [`${palette} ${mode}`, paletteRule(mode, palette)]),
        ),
    )('%s sets code at full size if and only if its face is mono', (_name, selector) => {
        const body = rule(selector)
        expect(body.includes('--code-size: 1em;')).toBe(body.includes('--face: var(--face-mono);'))
    })
})

/** The strength `--code-chip` mixes its ink at, as a fraction; a chip written another way fails rather than passes. */
function codeChip(): number {
    const percent = /--code-chip: color-mix\(in oklab, currentColor ([\d.]+)%, transparent\);/u.exec(css)?.[1]
    if (percent === undefined) {
        throw new Error('tokens.css sets --code-chip in a form this test does not read')
    }
    return Number(percent) / 100
}

/** The selector of the rule that sets `palette` over `mode`'s default. */
function paletteRule(mode: ResolvedTheme, palette: string): string {
    return mode === 'light'
        ? `:root[data-light-palette='${palette}']:not(.dark)`
        : `.dark[data-dark-palette='${palette}']`
}

/** The opaque oklch tokens a rule sets, by name. */
function theme(selector: string): Theme {
    const body = rule(selector)
    const colors: Theme = {}
    for (const [, name, l, c, h] of body.matchAll(/--([\w-]+): oklch\(([\d.]+) ([\d.]+) ([\d.]+)\)/gu)) {
        colors[name ?? ''] = [Number(l), Number(c), Number(h)]
    }
    return colors
}

/**
 * How a rule inks the nav's active label: the token it names when it draws the highlight as a block, and the shade
 * it sets, as a fraction, or `shade` when it sets none.
 */
function navLabel(selector: string, shade: number): NavLabel {
    const body = rule(selector)
    const ink = body.includes('--nav-block: 1;') ? /--nav-on-ink: var\(--([\w-]+)\)/u.exec(body)?.[1] : undefined
    const own = /--nav-label-shade: ([\d.]+)%/u.exec(body)?.[1]
    return { ink, shade: own === undefined ? shade : Number(own) / 100 }
}

/** The body of the rule for `selector`. */
function rule(selector: string): string {
    const start = css.indexOf(`\n${selector} {`)
    if (start === -1) {
        throw new Error(`tokens.css has no rule for ${selector}`)
    }
    return css.slice(start, css.indexOf('\n}', start))
}

/** A line naming the pair when it reads below AA, else null. */
function below(pair: string, fg: Rgb, bg: Rgb): string | null {
    const ratio = contrast(fg, bg)
    return ratio < AA ? `${pair}: ${ratio.toFixed(2)}:1` : null
}

/** `fg` at `alpha` over `bg`, composited in sRGB as a browser paints a translucent color. */
function over(fg: Rgb, alpha: number, bg: Rgb): Rgb {
    const [r, g, b] = bg
    return [fg[0] * alpha + r * (1 - alpha), fg[1] * alpha + g * (1 - alpha), fg[2] * alpha + b * (1 - alpha)]
}

/** WCAG 2's contrast ratio of two sRGB colors. */
function contrast(a: Rgb, b: Rgb): number {
    const [x, y] = [luminance(a), luminance(b)]
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

/** WCAG 2's relative luminance of an sRGB color. */
function luminance(rgb: Rgb): number {
    const [r, g, b] = rgb.map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)) as Rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** An oklch color as gamma-encoded sRGB, each channel clipped to 0..1 (CSS Color 4's conversion). */
function srgb(l: number, c: number, h: number): Rgb {
    const a = c * Math.cos((h * Math.PI) / 180)
    const b = c * Math.sin((h * Math.PI) / 180)
    const lms = [
        l + 0.3963377774 * a + 0.2158037573 * b,
        l - 0.1055613458 * a - 0.0638541728 * b,
        l - 0.0894841775 * a - 1.291485548 * b,
    ]
    const [x, y, z] = lms.map((v) => v ** 3) as Rgb
    const linear = [
        4.0767416621 * x - 3.3077115913 * y + 0.2309699292 * z,
        -1.2684380046 * x + 2.6097574011 * y - 0.3413193965 * z,
        -0.0041960863 * x - 0.7034186147 * y + 1.707614701 * z,
    ]
    return linear.map((v) => {
        const clipped = Math.min(1, Math.max(0, v))
        return clipped <= 0.0031308 ? 12.92 * clipped : 1.055 * clipped ** (1 / 2.4) - 0.055
    }) as Rgb
}
