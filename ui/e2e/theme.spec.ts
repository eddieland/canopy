import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { PALETTE_KEY, settled, signIn, STORAGE_KEY, storePalette, storeTheme, windowWidth } from './helpers.ts'

declare global {
    // A `var` in `declare global` is a property of globalThis, where the page's scripts set these.
    var canopyThemeProbe: { atBody?: string; atDomContentLoaded?: string; scheme?: string } | undefined
    var canopyViewTransitions: number | undefined
}

test.describe('no flash of the wrong theme', () => {
    test('a reload with dark stored has the class before the body, and at DOMContentLoaded', async ({ page }) => {
        await storeTheme(page, 'dark')
        // Records <html>'s class when <body> is first parsed (before any module script runs) and at DOMContentLoaded.
        await page.addInitScript(() => {
            const seen: NonNullable<typeof globalThis.canopyThemeProbe> = {}
            globalThis.canopyThemeProbe = seen
            new MutationObserver((_, observer) => {
                if (document.querySelector('body') !== null) {
                    seen.atBody = document.documentElement.className
                    observer.disconnect()
                }
            }).observe(document, { childList: true, subtree: true })
            document.addEventListener('DOMContentLoaded', () => {
                seen.atDomContentLoaded = document.documentElement.className
                seen.scheme = document.documentElement.style.colorScheme
            })
        })
        await page.goto('workspace/runs')
        await page.reload()
        const seen = await page.evaluate(() => globalThis.canopyThemeProbe)
        expect(seen?.atBody).toMatch(/\bdark\b/u)
        expect(seen?.atDomContentLoaded).toMatch(/\bdark\b/u)
        expect(seen?.scheme).toBe('dark')
    })

    test('with nothing stored it follows the system theme', async ({ page }) => {
        await page.emulateMedia({ colorScheme: 'dark' })
        await page.goto('workspace/runs')
        await expect(page.locator('html')).toHaveClass(/\bdark\b/u)
        await page.emulateMedia({ colorScheme: 'light' })
        await expect(page.locator('html')).not.toHaveClass(/\bdark\b/u)
    })
})

test.describe('the toggle', () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
        // Counts view transitions, to tell the animated switch from the instant one.
        await page.addInitScript(() => {
            globalThis.canopyViewTransitions = 0
            const original = document.startViewTransition.bind(document)
            document.startViewTransition = ((...args: Parameters<typeof original>) => {
                globalThis.canopyViewTransitions = (globalThis.canopyViewTransitions ?? 0) + 1
                return original(...args)
            }) as typeof document.startViewTransition
        })
    })

    test('switches with a view transition, persists, and survives a reload', async ({ page }) => {
        await storeTheme(page, 'light')
        await page.goto('workspace/runs')
        await settled(page)
        const toggle = page.getByTestId('theme-toggle')
        await expect(toggle).toHaveAccessibleName('Switch to dark theme')

        await toggle.click()

        await expect(page.locator('html')).toHaveClass(/\bdark\b/u)
        await expect(toggle).toHaveAccessibleName('Switch to light theme')
        expect(await page.evaluate(() => globalThis.canopyViewTransitions)).toBe(1)
        expect(await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)).toBe('dark')
        // Mid-reveal, for the record: the new theme grows from the button.
        await page.screenshot({ path: test.info().outputPath('toggle-done.png') })
    })

    test('swaps instantly when reduced motion is preferred', async ({ page }) => {
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await storeTheme(page, 'light')
        await page.goto('workspace/runs')
        await settled(page)
        await page.getByTestId('theme-toggle').click()
        await expect(page.locator('html')).toHaveClass(/\bdark\b/u)
        expect(await page.evaluate(() => globalThis.canopyViewTransitions)).toBe(0)
    })

    test('the settings page picks a theme from the keyboard', async ({ page }) => {
        await storeTheme(page, 'light')
        await page.goto('settings')
        await settled(page)
        const themes = page.getByRole('radiogroup', { name: 'Theme' })
        // The arrows move between the themes, Space picks one, and Tab leaves for the next group's pick.
        await page.getByTestId('theme-light').focus()
        await page.keyboard.press('ArrowRight')
        await expect(themes.getByRole('radio', { name: 'Dark' })).toBeFocused()
        await page.keyboard.press('Space')
        await expect(page.locator('html')).toHaveClass(/\bdark\b/u)
        await expect(themes.getByRole('radio', { name: 'Dark' })).toHaveAttribute('aria-checked', 'true')
        await page.keyboard.press('Tab')
        await expect(page.getByTestId('palette-light-lavender')).toBeFocused()
    })

    test('a change in one tab reaches the others', async ({ context }) => {
        const first = await context.newPage()
        const second = await context.newPage()
        await signIn(first)
        await first.goto('settings')
        await second.goto('workspace/runs')
        await settled(second)

        await first.getByTestId('theme-dark').click()
        await expect(second.locator('html')).toHaveClass(/\bdark\b/u)

        await first.getByTestId('theme-system').click()
        await expect(second.locator('html')).toHaveAttribute('data-theme', 'system')
    })
})

test.describe('palettes', () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
    })

    test("the settings page picks the dark theme's palette, and the canvas follows", async ({ page }) => {
        await storeTheme(page, 'dark')
        await page.goto('settings')
        await settled(page)
        const canvas = () =>
            page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--background'))
        const before = await canvas()

        await page.getByTestId('palette-dark-grey').click()

        await expect(page.locator('html')).toHaveAttribute('data-dark-palette', 'grey')
        await expect(
            page.getByRole('radiogroup', { name: 'Dark palette' }).getByRole('radio', { name: 'Grey' }),
        ).toHaveAttribute('aria-checked', 'true')
        await expect.poll(canvas).not.toBe(before)
        expect(await page.evaluate((key) => localStorage.getItem(key), PALETTE_KEY)).toBe(
            '{"light":"lavender","dark":"grey"}',
        )
    })

    // Light has eleven palettes, more than fit beside their description in a narrow window: there the picker drops
    // under it, and wraps where it is wider than the panel, so every palette stays inside the panel and in reach.
    for (const width of [1024, 820]) {
        test(`the settings page keeps each palette picker inside its panel at ${width}px`, async ({ page }) => {
            await storeTheme(page, 'light')
            await page.goto('settings')
            await settled(page)
            await windowWidth(page, width)
            for (const name of ['Light palette', 'Dark palette']) {
                const picker = page.getByRole('radiogroup', { name })
                const edges = await picker.evaluate((group) => {
                    const panel = group.parentElement?.parentElement
                    if (!panel) {
                        throw new Error('the picker is in no panel')
                    }
                    return {
                        panel: panel.getBoundingClientRect().right,
                        items: [...group.children].map((item) => item.getBoundingClientRect().right),
                    }
                })
                expect(Math.max(...edges.items), name).toBeLessThanOrEqual(edges.panel)
            }
        })
    }

    test("the header's toggle offers the shown theme's palettes on hover, and stays open to try another", async ({
        page,
    }) => {
        await storeTheme(page, 'dark')
        await page.goto('workspace/runs')
        await settled(page)
        // The reveal's own animations, on the view transition's pseudo-elements; the logo's breathing never ends.
        const revealing = () =>
            page.evaluate(
                () =>
                    document
                        .getAnimations()
                        .filter((animation) => animation.effect instanceof KeyframeEffect)
                        .filter((animation) => (animation.effect as KeyframeEffect).pseudoElement !== null).length,
            )

        await page.getByTestId('theme-toggle').hover()
        const card = page.getByTestId('palette-card')
        await card.getByRole('radio', { name: 'Forest' }).click()
        await expect(page.locator('html')).toHaveAttribute('data-dark-palette', 'forest')
        await expect.poll(revealing).toBe(0)

        // The reveal took the pointer from the page while it ran; the card is still there for the next pick.
        await expect(card).toBeVisible()
        await card.getByRole('radio', { name: 'Plum' }).click()
        await expect(page.locator('html')).toHaveAttribute('data-dark-palette', 'plum')
        await expect(card.getByRole('radio', { name: 'Plum' })).toHaveAttribute('aria-checked', 'true')
        await expect(page.locator('html')).toHaveClass(/\bdark\b/u)
        await expect.poll(revealing).toBe(0)
        await expect(card).toBeVisible()
        // For the record: the card over the header, in the palette just picked.
        await page.screenshot({ path: test.info().outputPath('palette-card.png') })

        await page.mouse.move(10, 400)
        await expect(card).toBeHidden()
    })

    test("a pick from the keyboard during the last pick's reveal leaves the card open", async ({ page }) => {
        await storeTheme(page, 'dark')
        await page.goto('workspace/runs')
        await settled(page)
        const revealing = () =>
            page.evaluate(
                () =>
                    document
                        .getAnimations()
                        .filter((animation) => animation.effect instanceof KeyframeEffect)
                        .filter((animation) => (animation.effect as KeyframeEffect).pseudoElement !== null).length,
            )

        await page.getByTestId('theme-toggle').hover()
        const card = page.getByTestId('palette-card')
        // The click leaves the focus on Forest; the arrow and Space pick Plum while Forest's reveal still runs, which
        // cuts that reveal short. The pointer stirs on the card while Plum's runs, as a hand does.
        const forest = card.getByRole('radio', { name: 'Forest' })
        const box = await forest.boundingBox()
        await forest.click()
        await page.keyboard.press('ArrowDown')
        await expect(card.getByRole('radio', { name: 'Plum' })).toBeFocused()
        await page.keyboard.press('Space')
        if (box !== null) {
            await page.mouse.move(box.x + box.width / 2 + 1, box.y + box.height / 2)
        }
        await expect(page.locator('html')).toHaveAttribute('data-dark-palette', 'plum')
        await expect.poll(revealing).toBe(0)
        await expect(card).toBeVisible()
    })

    test('a reload with a palette stored has it before the body', async ({ page }) => {
        await storeTheme(page, 'light')
        await storePalette(page, 'light', 'solarized')
        await page.addInitScript(() => {
            new MutationObserver((_, observer) => {
                if (document.querySelector('body') !== null) {
                    document.documentElement.dataset.paletteAtBody = document.documentElement.dataset.lightPalette
                    observer.disconnect()
                }
            }).observe(document, { childList: true, subtree: true })
        })
        await page.goto('workspace/runs')
        await expect(page.locator('html')).toHaveAttribute('data-palette-at-body', 'solarized')
    })

    test('a pick in one tab reaches the others, on any page', async ({ context }) => {
        const first = await context.newPage()
        const second = await context.newPage()
        await signIn(first)
        await first.goto('settings')
        await second.goto('workspace/runs')
        await settled(second)

        await first.getByTestId('palette-light-off-white').click()

        await expect(second.locator('html')).toHaveAttribute('data-light-palette', 'off-white')
    })
})

test.describe('the guide under a mono palette', () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
    })

    for (const [theme, palette] of [
        ['dark', 'gruvbox'],
        ['dark', 'pulp'],
        ['dark', 'monokai'],
        ['light', 'gruvbox'],
        ['light', 'pulp'],
        ['light', 'acme'],
    ] as const) {
        test(`${theme} ${palette} sets the app in mono and the guide in Plex Sans`, async ({ page }) => {
            await storeTheme(page, theme)
            await storePalette(page, theme, palette)
            await page.goto('guide/settings')
            await settled(page)

            await expect(page.locator('body')).toHaveCSS('font-family', /^"IBM Plex Mono Compact"/u)
            const guide = page.getByTestId('guide-page')
            await expect(guide.getByRole('paragraph').first()).toHaveCSS('font-family', /^"IBM Plex Sans Variable"/u)
            await expect(guide.locator('code').first()).toHaveCSS('font-family', /^"IBM Plex Mono"/u)
        })
    }
})

test.describe("Pulp's Ben-Day tone", () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
    })

    for (const theme of ['dark', 'light'] as const) {
        test(`${theme} draws no tone by default, and Pulp prints it ramped`, async ({ page }) => {
            await storeTheme(page, theme)
            await page.goto('workspace/runs')
            await settled(page)
            for (const layer of await canvasTone(page)) {
                expect(layer).toEqual({ image: 'none', mask: 'none', composite: 'add' })
            }

            await storePalette(page, theme, 'pulp')
            await page.reload()
            await settled(page)
            for (const layer of await canvasTone(page)) {
                expect(layer.image).toMatch(/^radial-gradient\(/u)
                expect(layer.mask).toMatch(/^linear-gradient\(/u)
            }
        })
    }
})

test.describe("Starry Skies's stars", () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
        await storeTheme(page, 'dark')
        await storePalette(page, 'dark', 'starry-skies')
    })

    test('prints its stars on both layers, masked, twinkles them, and sends its meteors', async ({ page }) => {
        await page.goto('workspace/runs')
        await settled(page)
        for (const layer of await canvasTone(page)) {
            expect(layer.image).toMatch(/^radial-gradient\(/u)
            expect(layer.mask).toMatch(/^linear-gradient\(/u)
        }
        expect(await skyMotion(page)).toEqual(['star-shimmer', 'twinkle', 'meteor', 'meteor-2'])
        const streak = { image: expect.stringMatching(/^linear-gradient\(/u), mask: 'none', turn: '162deg', long: true }
        expect(await crosser(page)).toEqual({ ...streak, color: false })
        // Its two meteors are two of a kind, and its aurora blooms whole: a palette that sets no knob for the second
        // crosser or for the aurora's mask draws both as it did before there were any.
        expect(await crosser(page, '::after')).toEqual(await crosser(page))
        expect(await aurora(page)).toEqual({ image: expect.stringMatching(/^linear-gradient\(90deg, /u), mask: 'none' })
    })

    test('hangs its moon under the panels, its phase cut by a mask, and no other palette does', async ({ page }) => {
        await page.goto('workspace/runs')
        await settled(page)
        expect(await moon(page)).toEqual({
            image: expect.stringMatching(/^radial-gradient\(/u),
            mask: expect.stringMatching(/^radial-gradient\(/u),
            zIndex: '-1',
            drawn: true,
        })

        await storePalette(page, 'dark', 'black')
        await page.reload()
        await settled(page)
        expect(await moon(page)).toEqual({ image: 'none', mask: 'none', zIndex: '-1', drawn: true })
    })

    test('holds its stars still and draws no meteor under reduced motion', async ({ page }) => {
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await page.goto('workspace/runs')
        await settled(page)
        expect(await skyMotion(page)).toEqual(['none', 'none', 'none', 'none'])
        expect(await page.evaluate(() => getComputedStyle(document.body, '::before').content)).toBe('none')
    })

    test('draws no meteor on another palette', async ({ page }) => {
        await storePalette(page, 'dark', 'black')
        await page.goto('workspace/runs')
        await settled(page)
        expect(await skyMotion(page)).toEqual(['none', 'none', 'none', 'none'])
    })
})

test.describe("Komorebi's light", () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
        await storeTheme(page, 'light')
        await storePalette(page, 'light', 'komorebi')
    })

    test('lays sun and leaf shadows on the two layers, masked, dims them, and lets its leaves fall', async ({
        page,
    }) => {
        await page.goto('workspace/runs')
        await settled(page)
        const [light, shade] = await canvasTone(page)
        expect(light?.image).toMatch(/^radial-gradient\(/u)
        expect(light?.mask).toMatch(/^linear-gradient\(/u)
        // The shade is one color, cut to its leaves by its two tiles, inside the same clearing as the light: the rail,
        // the header, and the title. Each tile is in the stylesheet, a `data:` URL.
        expect(shade?.image).toBe('none')
        expect(shade?.mask).toMatch(/^linear-gradient\(.+linear-gradient\(.+(?:, url\("data:image\/svg[^"]+"\)){2}$/u)
        expect(await skyMotion(page)).toEqual([
            'dapple',
            'dapple-shade',
            'leaf-fall, leaf-rock',
            'leaf-fall-2, leaf-rock',
        ])
        expect(await crosser(page)).toEqual({
            image: 'none',
            color: true,
            mask: expect.stringMatching(/^url\("data:image\/svg[^"]+"\)$/u),
            turn: '0deg',
            long: false,
        })
        // Both leaves are the one leaf, and its aurora blooms whole, as before the second crosser and the aurora's
        // mask were knobs.
        expect(await crosser(page, '::after')).toEqual(await crosser(page))
        expect(await aurora(page)).toEqual({ image: expect.stringMatching(/^linear-gradient\(90deg, /u), mask: 'none' })
    })

    test('carries its leaves in the stylesheet, so no mask waits on a file, and the page loads each', async ({
        page,
    }) => {
        const files = svgFiles(page)
        await page.goto('workspace/runs')
        await settled(page)
        // The sprays' two tiles, the bough, and a falling leaf: each a `data:` image, which the content security policy
        // must let the page load, and none a file among the build's assets. Left to files, the shadows would be
        // missing until the files came.
        expect(await maskImages(page)).toEqual([true, true, true, true])
        expect(files).toEqual([])
    })

    test("casts its bough's shadow under the panels, swaying, and no other palette does", async ({ page }) => {
        await page.goto('workspace/runs')
        await settled(page)
        // It darkens what is under it, as every shadow of Komorebi's does, so two of them go no deeper than one.
        expect(await bough(page)).toEqual({
            painted: true,
            image: 'none',
            mask: expect.stringMatching(/^url\("data:image\/svg[^"]+"\)$/u),
            blend: 'darken',
            zIndex: '-1',
            motion: 'bough-sway',
        })
        expect(await shadeBlend(page)).toEqual(['normal', 'darken', 'darken', 'darken'])

        await storePalette(page, 'light', 'sage')
        await page.reload()
        await settled(page)
        expect(await bough(page)).toEqual(NO_BOUGH)
        expect(await shadeBlend(page)).toEqual(['normal', 'normal', 'normal', 'normal'])
    })

    test('holds still and drops no leaf under reduced motion', async ({ page }) => {
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await page.goto('workspace/runs')
        await settled(page)
        expect(await skyMotion(page)).toEqual(['none', 'none', 'none', 'none'])
        expect((await bough(page)).motion).toBe('none')
        expect(await page.evaluate(() => getComputedStyle(document.body, '::before').content)).toBe('none')
    })

    test('keeps its light and shade off the rail, the header, and the page title', async ({ page }) => {
        await page.goto('workspace/runs')
        await settled(page)
        const [light, shade] = await clearedTone(page)
        // A layer shows only where both gradients do: added instead, each would let it through where the other
        // clears. The shade's two tiles add to each other, inside them.
        expect(light?.composite).toBe('intersect, add')
        expect(shade?.composite).toBe('intersect, intersect, add, add')
    })
})

test.describe("Koi Pond's water", () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
        await storeTheme(page, 'light')
        await storePalette(page, 'light', 'koi-pond')
    })

    test('deepens the water on one layer, nets light on the other, masked, and only the light breathes', async ({
        page,
    }) => {
        await page.goto('workspace/runs')
        await settled(page)
        const [water, light] = await canvasTone(page)
        expect(water?.image).toMatch(/^radial-gradient\(.*linear-gradient\(/u)
        expect(water?.mask).toMatch(/^linear-gradient\(/u)
        // The light is one color, cut to its nets by the tile, then cleared over the pads and wherever the water is
        // cleared. The tile is in the stylesheet, a `data:` URL.
        expect(light?.image).toBe('none')
        expect(light?.mask).toMatch(/^url\("data:image\/svg[^"]+"\), radial-gradient\(.*linear-gradient\(/u)
        expect(await skyMotion(page)).toEqual(['none', 'pond-glimmer', 'koi-swim', 'pond-ripple'])
    })

    test('sends a koi and opens a ripple, each a thing of its own, both unseen at rest', async ({ page }) => {
        await page.goto('workspace/runs')
        await settled(page)
        // The koi is a drawing with colors of its own; the ripple is the light's color through a mask of its rings.
        expect(await crosser(page)).toEqual({
            image: expect.stringMatching(/^url\("[^"]*koi[^"]*\.svg"\)$/u),
            color: false,
            mask: 'none',
            turn: '0deg',
            long: false,
        })
        expect(await crosser(page, '::after')).toEqual({
            image: 'none',
            color: true,
            mask: expect.stringMatching(/^url\("data:image\/svg[^"]+"\)$/u),
            turn: '0deg',
            long: false,
        })
        const atRest = await page.evaluate(() =>
            (['::before', '::after'] as const).map((layer) => {
                for (const animation of document.getAnimations()) {
                    animation.currentTime = 0
                }
                return getComputedStyle(document.body, layer).opacity
            }),
        )
        expect(atRest).toEqual(['0', '0'])
    })

    test('floats its pads in the corner under the panels, a drawing, still, and no other palette does', async ({
        page,
    }) => {
        await page.goto('workspace/runs')
        await settled(page)
        await windowWidth(page, 1720)
        // Nothing of the pond's is a shadow, so each layer paints plainly over the last, and none darkens it.
        expect(await bough(page)).toEqual({
            painted: false,
            image: expect.stringMatching(/^url\("[^"]*pads[^"]*\.svg"\)$/u),
            mask: 'none',
            blend: 'normal',
            zIndex: '-1',
            motion: 'none',
        })
        expect(await shadeBlend(page)).toEqual(['normal', 'normal', 'normal', 'normal'])
        // Its drawings are files the page fetches itself, which the content security policy must allow.
        const drawings = await page.evaluate(() => {
            const root = document.querySelector('#root')
            return [root ? getComputedStyle(root, '::after') : null, getComputedStyle(document.body, '::before')].map(
                (style) => style?.backgroundImage.slice(5, -2) ?? '',
            )
        })
        for (const drawing of drawings) {
            expect((await page.request.get(drawing)).headers()['content-type']).toBe('image/svg+xml')
        }

        await storePalette(page, 'light', 'sage')
        await page.reload()
        await settled(page)
        expect(await bough(page)).toEqual(NO_BOUGH)
    })

    // The guide sets its prose on the canvas, so the pads take only the room it leaves: right of its text column,
    // whole where that is wide enough, and none in a window as narrow as 1280px, where they would lie behind the text.
    test('gives its pads only the room the guide leaves beside its text', async ({ page }) => {
        await page.goto('guide/overview')
        await settled(page)
        const room = () =>
            page.evaluate(() => {
                const root = document.querySelector('#root')
                const text = document.querySelector('[data-testid=guide-page]')
                if (!root || !text) {
                    throw new Error('the page has no #root or no guide page')
                }
                const style = getComputedStyle(root, '::after')
                const wide = Number.parseFloat(style.backgroundSize)
                // The drawing lies against the right of its box, less the offset its position names.
                const right = Number.parseFloat(style.left) + Number.parseFloat(style.width)
                const gap = Number.parseFloat(style.backgroundPositionX.replace(/^calc\(100% - (.*)\)$/u, '$1'))
                return { wide, left: right - gap - wide, text: text.getBoundingClientRect().right }
            })
        await windowWidth(page, 1720)
        const open = await room()
        const rem = await page.evaluate(() => Number.parseFloat(getComputedStyle(document.documentElement).fontSize))
        expect(open.wide).toBeCloseTo(14.5 * rem, 0)
        expect(open.left).toBeGreaterThan(open.text)
        await windowWidth(page, 1440)
        const narrower = await room()
        expect(narrower.wide).toBeGreaterThan(0)
        expect(narrower.wide).toBeLessThan(open.wide)
        expect(narrower.left).toBeGreaterThan(narrower.text)
        await windowWidth(page, 1280)
        expect((await room()).wide).toBe(0)
    })

    test('cuts the aurora to a waterline in the section colors', async ({ page }) => {
        await page.goto('workspace/runs')
        await settled(page)
        expect(await aurora(page)).toEqual({
            image: expect.stringMatching(/^linear-gradient\(90deg, /u),
            mask: expect.stringMatching(/^url\("data:image\/svg[^"]+"\)$/u),
        })
    })

    test('carries its masks in the stylesheet, so none waits on a file, and fetches only its two drawings', async ({
        page,
    }) => {
        const files = svgFiles(page)
        await page.goto('workspace/runs')
        await settled(page)
        // The net, the ripple, and the wave: each a `data:` image, which the content security policy must let the
        // page load. A mask left to a file would paint its layer flat until the file came.
        expect(await maskImages(page)).toEqual([true, true, true])
        // Only the pads and the koi are files among the build's assets: a drawing not yet arrived paints nothing.
        expect(files.filter((path) => !/\/(?:pads|koi)-[^/]*\.svg$/u.test(path))).toEqual([])
    })

    test('holds still and sends no koi under reduced motion, its pads still afloat', async ({ page }) => {
        await page.emulateMedia({ reducedMotion: 'reduce' })
        await page.goto('workspace/runs')
        await settled(page)
        await windowWidth(page, 1720)
        expect(await skyMotion(page)).toEqual(['none', 'none', 'none', 'none'])
        for (const which of ['::before', '::after']) {
            expect(await page.evaluate((layer) => getComputedStyle(document.body, layer).content, which)).toBe('none')
        }
        // The still pond is whole without them: the koi that lives in the corner is part of the pads' drawing.
        expect((await bough(page)).image).toMatch(/pads/u)
    })

    test('keeps its water and light off the rail, the header, and the page title', async ({ page }) => {
        await page.goto('workspace/runs')
        await settled(page)
        const [water, light] = await clearedTone(page)
        // The light's net and its clearing over the pads show only inside the two gradients, as the water does.
        expect(water?.composite).toBe('intersect, add')
        expect(light?.composite).toBe('intersect, intersect, intersect, add')
    })

    // Each crosser's path is clamped against the rail, so a narrow window moves it right rather than let it reach
    // the rail or a page's title: stepped through its whole period, each stays in the band along the window's foot.
    for (const width of [1720, 1280, 1024]) {
        test(`keeps its koi and its ripple in the band along the foot, clear of the rail, at ${width}px`, async ({
            page,
        }) => {
            await page.goto('workspace/runs')
            await settled(page)
            await windowWidth(page, width)
            const rem = await page.evaluate(() =>
                Number.parseFloat(getComputedStyle(document.documentElement).fontSize),
            )
            for (const which of ['::before', '::after'] as const) {
                const reach = await crossing(page, which)
                expect(reach.seen).toBeGreaterThan(0)
                expect(reach.left).toBeGreaterThanOrEqual(23 * rem)
                expect(reach.top).toBeGreaterThanOrEqual((page.viewportSize()?.height ?? 0) - 9.5 * rem)
            }
        })
    }
})

/** The animations the sky runs: the canvas's two layers, then its two meteors, each by name, or none. */
function skyMotion(page: Page): Promise<string[]> {
    return page.evaluate(() =>
        [
            [document.documentElement, '::before'],
            [document.documentElement, '::after'],
            [document.body, '::before'],
            [document.body, '::after'],
        ].map(([element, layer]) => getComputedStyle(element as Element, layer as string).animationName),
    )
}

/** What the moon's box paints, the mask that cuts its phase, where it sits in the stack, and whether it has a box. */
function moon(page: Page): Promise<{ image: string; mask: string; zIndex: string; drawn: boolean }> {
    return page.evaluate(() => {
        const root = document.querySelector('#root')
        if (!root) {
            throw new Error('the page has no #root')
        }
        const style = getComputedStyle(root, '::before')
        return {
            image: style.backgroundImage,
            mask: style.maskImage,
            zIndex: style.zIndex,
            drawn: style.content !== 'none' && Number.parseFloat(style.width) > 0,
        }
    })
}

/** One of the two things that cross the canvas, the first unless the second is asked for. */
interface Crosser {
    /** The image it paints, or none. */
    image: string
    /** Whether it paints a color. */
    color: boolean
    /** The mask that cuts it, or none. */
    mask: string
    /** Its turn. */
    turn: string
    /** Whether it is a streak, far longer than thick. */
    long: boolean
}

/** What crosses the canvas: what `which` of the two paints, its mask, its turn, and its shape. */
function crosser(page: Page, which: '::before' | '::after' = '::before'): Promise<Crosser> {
    return page.evaluate((layer) => {
        const style = getComputedStyle(document.body, layer)
        return {
            image: style.backgroundImage,
            color: style.backgroundColor !== 'rgba(0, 0, 0, 0)',
            mask: style.maskImage,
            turn: style.rotate,
            long: Number.parseFloat(style.width) > 10 * Number.parseFloat(style.height),
        }
    }, which)
}

/**
 * How near the rail and how high a crosser comes while it shows in the window: its animation stepped through one
 * period, a quarter of a second at a time, and at each step where it is seen and its middle is in the window, its
 * box's left and top edges, at its size then. `seen` counts those steps.
 */
function crossing(page: Page, which: '::before' | '::after'): Promise<{ seen: number; left: number; top: number }> {
    return page.evaluate((layer) => {
        const animation = document
            .getAnimations()
            .find(
                ({ effect }) =>
                    effect instanceof KeyframeEffect &&
                    effect.target === document.body &&
                    effect.pseudoElement === layer,
            )
        const period = Number(animation?.effect?.getComputedTiming().duration)
        if (!animation || !Number.isFinite(period)) {
            throw new Error(`nothing crosses on body${layer}`)
        }
        animation.pause()
        const reach = { seen: 0, left: Infinity, top: Infinity }
        for (let time = 0; time < period; time += 250) {
            animation.currentTime = time
            const style = getComputedStyle(document.body, layer)
            // Where its middle is: its box's own place, moved by `translate`, then by `transform`, whose scale and
            // `scale`'s size it.
            const matrix = new DOMMatrixReadOnly(style.transform)
            const [dx = 0, dy = 0] =
                style.translate === 'none' ? [] : style.translate.split(' ').map((part) => Number.parseFloat(part))
            const scale = style.scale === 'none' ? 1 : Number.parseFloat(style.scale)
            const size = Math.abs(matrix.a * matrix.d - matrix.b * matrix.c) ** 0.5 * scale
            const half = (Number.parseFloat(style.width) / 2) * size
            const x = Number.parseFloat(style.left) + Number.parseFloat(style.width) / 2 + dx + matrix.e
            const y = Number.parseFloat(style.top) + Number.parseFloat(style.height) / 2 + dy + matrix.f
            if (Number(style.opacity) > 0 && y < innerHeight && x < innerWidth) {
                reach.seen += 1
                reach.left = Math.min(reach.left, x - half)
                reach.top = Math.min(reach.top, y - half)
            }
        }
        animation.play()
        return reach
    }, which)
}

/** The corner's box: what it paints, a color or an image, the mask that cuts it, and how it lies and moves. */
interface Bough {
    /** Whether it paints a color. */
    painted: boolean
    /** The image it paints, or none. */
    image: string
    /** The mask that cuts it, or none. */
    mask: string
    /** How it blends with what is under it. */
    blend: string
    /** Where it sits in the stack. */
    zIndex: string
    /** Its animation's name, or none. */
    motion: string
}

/** The corner's box on a palette that lays nothing there. */
const NO_BOUGH: Bough = { painted: false, image: 'none', mask: 'none', blend: 'normal', zIndex: '-1', motion: 'none' }

/**
 * What the corner's box paints, the mask that cuts it, how it blends with what is under it, where it sits in the
 * stack, and its sway.
 */
function bough(page: Page): Promise<Bough> {
    return page.evaluate(() => {
        const root = document.querySelector('#root')
        if (!root) {
            throw new Error('the page has no #root')
        }
        const style = getComputedStyle(root, '::after')
        return {
            painted: style.content !== 'none' && style.backgroundColor !== 'rgba(0, 0, 0, 0)',
            image: style.backgroundImage,
            mask: style.maskImage,
            blend: style.mixBlendMode,
            zIndex: style.zIndex,
            motion: style.animationName,
        }
    })
}

/** How the canvas's two layers, then what crosses it, blend with what lies under them: the first layer never does. */
function shadeBlend(page: Page): Promise<string[]> {
    return page.evaluate(() =>
        [
            [document.documentElement, '::before'],
            [document.documentElement, '::after'],
            [document.body, '::before'],
            [document.body, '::after'],
        ].map(([element, layer]) => getComputedStyle(element as Element, layer as string).mixBlendMode),
    )
}

/**
 * Whether the page itself loads each `data:` image a palette's masks name, under its own policy, each image once:
 * those of the canvas's second layer, the corner's box, the two crossers, and the aurora, in that order.
 */
function maskImages(page: Page): Promise<boolean[]> {
    return page.getByTestId('aurora').evaluate((line) => {
        const root = document.querySelector('#root')
        if (!root) {
            throw new Error('the page has no #root')
        }
        const styles = [
            getComputedStyle(document.documentElement, '::after'),
            getComputedStyle(root, '::after'),
            getComputedStyle(document.body, '::before'),
            getComputedStyle(document.body, '::after'),
            getComputedStyle(line),
        ]
        const urls = new Set(
            styles.flatMap((style) =>
                [...style.maskImage.matchAll(/url\("(data:[^"]*)"\)/gu)].map(([, url]) => url ?? ''),
            ),
        )
        return Promise.all(
            [...urls].map((url) => {
                const image = new Image()
                image.src = url
                return image.decode().then(
                    () => true,
                    () => false,
                )
            }),
        )
    })
}

/** The SVG files among the build's assets that the page asks for from here on, by path: it fills as the page asks. */
function svgFiles(page: Page): string[] {
    const asked: string[] = []
    page.on('request', (request) => {
        const { pathname } = new URL(request.url())
        if (pathname.includes('/assets/') && pathname.endsWith('.svg')) {
            asked.push(pathname)
        }
    })
    return asked
}

/** The aurora along the header's foot: the image it paints and the mask that cuts it, or none. */
function aurora(page: Page): Promise<{ image: string; mask: string }> {
    return page.getByTestId('aurora').evaluate((line) => {
        const style = getComputedStyle(line)
        return { image: style.backgroundImage, mask: style.maskImage }
    })
}

/** One of the canvas's two tone layers: its background, its mask, and how the mask's layers combine. */
interface Tone {
    /** The image it paints, or none. */
    image: string
    /** The mask that cuts it, or none. */
    mask: string
    /** How each layer of the mask combines with those under it. */
    composite: string
}

/** What the canvas's two tone layers paint, the dots and their swell. */
function canvasTone(page: Page): Promise<Tone[]> {
    return page.evaluate(() =>
        (['::before', '::after'] as const).map((layer) => {
            const style = getComputedStyle(document.documentElement, layer)
            return { image: style.backgroundImage, mask: style.maskImage, composite: style.maskComposite }
        }),
    )
}

/**
 * The canvas's two layers on a palette that keeps both off the rail, the header, and a page's title, once it has held
 * them to that: the rail ends within 14rem of the window's left and the title within 12.5rem of its top, and each
 * layer's mask is clear up to those two lines (Komorebi's `--shade-clear`, Koi Pond's `--pond-clear`).
 */
async function clearedTone(page: Page): Promise<Tone[]> {
    const rem = await page.evaluate(() => Number.parseFloat(getComputedStyle(document.documentElement).fontSize))
    const title = await page.getByRole('heading', { level: 1 }).boundingBox()
    const rail = await page.getByRole('navigation').first().boundingBox()
    expect((rail?.x ?? 0) + (rail?.width ?? Infinity)).toBeLessThanOrEqual(14 * rem)
    expect((title?.y ?? 0) + (title?.height ?? Infinity)).toBeLessThanOrEqual(12.5 * rem)
    const layers = await canvasTone(page)
    expect(layers).toHaveLength(2)
    for (const layer of layers) {
        expect(layer.mask).toContain(`linear-gradient(90deg, rgba(0, 0, 0, 0) ${14 * rem}px`)
        expect(layer.mask).toContain(`linear-gradient(rgba(0, 0, 0, 0) ${12.5 * rem}px`)
    }
    return layers
}

test.describe("Pulp's lettering", () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
    })

    for (const theme of ['dark', 'light'] as const) {
        test(`${theme} pulp letters only a section's title in its own face, in the same line box`, async ({ page }) => {
            await storeTheme(page, theme)
            await page.goto('attention')
            await settled(page)
            const title = page.getByRole('heading', { level: 1, name: 'Attention' })
            await expect(title).not.toHaveCSS('font-family', /Bangers/u)
            const before = await title.boundingBox()

            await storePalette(page, theme, 'pulp')
            await page.reload()
            await settled(page)

            await expect(title).toHaveCSS('font-family', /^"Bangers Title"/u)
            // Within a pixel: the face's line box can land a fraction of one off the default's.
            expect((await title.boundingBox())?.height).toBeCloseTo(before?.height ?? Number.NaN, 0)
            await page.goto('workspace/runs/39')
            await settled(page)
            await expect(page.getByRole('heading', { level: 1 })).toHaveCSS('font-family', /^"IBM Plex Mono Compact"/u)
        })
    }
})

// Pulp tilts its name's plate (`--wordmark-tilt`), a transform, which moves nothing; the plate, its ring, and its drop
// are shadows, which take no room. So what they draw has to fit in the room the name had: clear of the logo, of the
// stream's pills, and of the header's edges and its aurora, at the operator's width and at the narrow strip's.
test.describe("Pulp's name plate", () => {
    test.beforeEach(async ({ page }) => {
        await signIn(page)
    })

    test('the default palette draws the name untilted', async ({ page }) => {
        await storeTheme(page, 'dark')
        await page.goto('attention')
        await settled(page)
        await expect(page.getByTestId('wordmark')).toHaveCSS('transform', 'none')
    })

    for (const theme of ['light', 'dark'] as const) {
        for (const width of [1720, 820]) {
            test(`${theme} at ${width}px tilts the plate and it clears what is beside it`, async ({ page }) => {
                await storeTheme(page, theme)
                await storePalette(page, theme, 'pulp')
                await page.goto('attention')
                await settled(page)
                await windowWidth(page, width)
                const wordmark = page.getByTestId('wordmark')
                await expect(wordmark).not.toHaveCSS('transform', 'none')
                const box = (locator: typeof wordmark) =>
                    locator.evaluate((element) => {
                        const { top, right, bottom, left } = element.getBoundingClientRect()
                        return { top, right, bottom, left, font: Number.parseFloat(getComputedStyle(element).fontSize) }
                    })
                const name = await box(wordmark)
                const mark = await box(page.getByTestId('mark'))
                const pills = await box(page.getByTestId('stream-status'))
                const header = await box(page.getByTestId('app-header'))
                // The frame's block, its ring at a line and a half at most, and the drop's 3px past them; the aurora's
                // 4px strip along the header's foot.
                const reach = 0.25 * name.font + 1.5
                expect(name.left - reach).toBeGreaterThan(mark.right)
                expect(name.right + reach + 3).toBeLessThan(pills.left)
                expect(name.top - reach).toBeGreaterThan(header.top)
                expect(name.bottom + reach + 3).toBeLessThan(header.bottom - 4)
            })
        }
    }
})
