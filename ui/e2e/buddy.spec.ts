import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

import { NOW, screenshotWhole, settled, signIn, spentInAll, storeTheme, THEMES } from './helpers.ts'

// Tall enough that the rail has room for Sprig and its bubble under the mock's four working rows and `+1 more`.
test.use({ viewport: { width: 1280, height: 1260 } })

/** The longest Sprig waits before offering a tip unasked, in seconds (`WAIT_SECONDS` in buddy.tsx). */
const LONGEST_WAIT = 360

/**
 * Runs the page's installed clock in steps until Sprig offers a tip on its own, at a random time no later than
 * `LONGEST_WAIT`. The steps are shorter than a tip stays up, so one offered between two is still up after the second.
 */
async function waitForTip(page: Page, tip: Locator): Promise<void> {
    for (let seconds = 0; seconds < LONGEST_WAIT && !(await tip.isVisible()); seconds += 5) {
        await page.clock.runFor(5000)
    }
    await expect(tip).toBeVisible()
}

/**
 * Makes every `Math.random` on the page return 0, so Sprig picks the same tips on every run: its view's first holds
 * the bubble's room, and a click offers its second.
 */
async function fixRandom(page: Page): Promise<void> {
    await page.addInitScript(() => {
        Math.random = () => 0
    })
}

/**
 * Asks Sprig, or the Ghost in its place, for a tip from the keyboard, then lets go of the focus: no pointer moves its
 * eyes, no ring shows.
 */
async function askSprig(page: Page): Promise<void> {
    const sprig = page.getByTestId('buddy-sprig')
    await sprig.press('Enter')
    await sprig.blur()
    await expect(page.getByTestId('buddy-tip')).toBeVisible()
}

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('Sprig is off until Settings turns it on', async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    await expect(page.getByTestId('buddy')).toHaveCount(0)
    await expect(page.getByTestId('fun-sprig')).not.toBeChecked()

    await page.getByTestId('fun-sprig').click()
    await expect(page.getByTestId('buddy-sprig')).toBeVisible()
    await page.reload()
    await settled(page)
    await expect(page.getByTestId('buddy')).toBeVisible()
})

test("picking the Ghost in Settings turns it on in Sprig's place", async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    await expect(page.getByTestId('buddy')).toHaveCount(0)

    await page.getByTestId('companion-ghost').click()
    await expect(page.getByRole('complementary', { name: 'Ghost' })).toBeVisible()
    await expect(page.getByTestId('fun-sprig')).toBeChecked()
    await expect(page.getByTestId('fun-sprig')).toHaveAccessibleName('Ghost')
})

test('picking Sprig, already picked, turns it on', async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    await expect(page.getByTestId('companion-sprig')).toHaveAttribute('data-state', 'on')

    await page.getByTestId('companion-sprig').click()
    await expect(page.getByRole('complementary', { name: 'Sprig' })).toBeVisible()
    await expect(page.getByTestId('companion-sprig')).toHaveAttribute('data-state', 'on')
})

test.describe('turned on', () => {
    // As if turned on in Settings on an earlier visit; a choice made since, in the page, stands.
    test.beforeEach(async ({ page }) => {
        await page.addInitScript(() => {
            if (globalThis.localStorage.getItem('canopy-buddy') === null) {
                globalThis.localStorage.setItem('canopy-buddy', 'on')
            }
        })
    })

    test('Sprig offers a tip now and then, another on a click, and closes when told', async ({ page }) => {
        await page.clock.install()
        await page.goto('attention')
        await settled(page)
        const tip = page.getByTestId('buddy-tip')
        // A page arrives with no tip up: the first comes on Sprig's own time.
        await expect(tip).toBeHidden()
        await waitForTip(page, tip)
        const first = await tip.textContent()

        await page.getByTestId('buddy-another').click()
        await expect(tip).not.toHaveText(first ?? '')
        const second = await tip.textContent()
        await page.getByTestId('buddy-sprig').click()
        await expect(tip).not.toHaveText(second ?? '')
        const third = await tip.textContent()

        await page.getByTestId('buddy-close').click()
        await expect(tip).toBeHidden()
        await expect(page.getByTestId('buddy-sprig')).toBeVisible()

        // A new page offers no tip of its own, and the next comes on Sprig's time, never the one it last offered.
        await page.getByTestId('rail-settings').click()
        await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
        await expect(tip).toBeHidden()
        await waitForTip(page, tip)
        await expect(tip).not.toHaveText(third ?? '')
    })

    test('a tip is shown only on the view it was offered on, and closes on time', async ({ page }) => {
        await page.clock.install()
        await page.goto('attention')
        await settled(page)
        const tip = page.getByTestId('buddy-tip')
        await page.getByTestId('buddy-sprig').click()
        await expect(tip).toBeVisible()

        await page.getByTestId('rail-settings').click()
        await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
        await expect(tip).toBeHidden()
        await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Attention' }).click()
        await expect(tip).toBeVisible()
        await page.clock.runFor(21_000)
        await expect(tip).toBeHidden()
    })

    test('Sprig has its own tip for a list and one of its items, and keeps it for another filter', async ({ page }) => {
        // A page loaded anew has no last tip to skip: picked at random, a run's could be the same one for anywhere.
        await fixRandom(page)
        await page.goto('workspace/runs')
        await settled(page)
        const tip = page.getByTestId('buddy-tip')
        await page.getByTestId('buddy-sprig').click()
        await expect(tip).toBeVisible()
        const shown = await tip.textContent()

        // The same view filtered another way offers the same tip: the bubble stays as it was, not closed and opened.
        await tip.evaluate((el) => {
            el.dataset.kept = ''
        })
        const filters = page.getByRole('navigation', { name: 'Filter by state' })
        await filters.getByRole('link', { name: 'waiting on you' }).click()
        await expect(page).toHaveURL(/workspace\/runs\?state=blocked$/u)
        await expect(tip).toHaveText(shown ?? '')
        await expect(tip).toHaveAttribute('data-kept', '')

        // Closed, it stays closed on the same view.
        await page.getByTestId('buddy-close').click()
        await filters.getByRole('link', { name: 'all' }).click()
        await expect(page).toHaveURL(/workspace\/runs$/u)
        await expect(tip).toBeHidden()

        // A run's page is a view of its own, with a tip of its own.
        await page.goto('workspace/runs/39')
        await settled(page)
        await page.getByTestId('buddy-sprig').click()
        await expect(tip).toBeVisible()
        await expect(tip).not.toHaveText(shown ?? '')
    })

    test("Don't show me tips again turns Sprig off until Settings turns it back on", async ({ page }) => {
        await page.goto('settings')
        await settled(page)
        const buddy = page.getByTestId('buddy')
        await expect(page.getByTestId('fun-sprig')).toBeChecked()

        await page.getByTestId('buddy-sprig').click()
        await page.getByTestId('buddy-dismiss').click()
        await expect(buddy).toHaveCount(0)
        await expect(page.getByTestId('fun-sprig')).not.toBeChecked()
        await page.reload()
        await settled(page)
        await expect(buddy).toHaveCount(0)

        await page.getByTestId('fun-sprig').click()
        await expect(buddy).toBeVisible()
        await expect(page.getByTestId('buddy-sprig')).toBeVisible()
    })

    test("Settings puts a Ghost in Sprig's place, and the rail keeps it", async ({ page }) => {
        await page.goto('settings')
        await settled(page)
        await expect(page.getByRole('complementary', { name: 'Sprig' })).toBeVisible()

        await page.getByTestId('companion-ghost').click()
        const ghost = page.getByRole('complementary', { name: 'Ghost' })
        await expect(ghost).toBeVisible()
        await expect(page.getByTestId('fun-sprig')).toHaveAccessibleName('Ghost')
        await page.reload()
        await settled(page)
        await page.getByRole('button', { name: 'Ask Ghost for a tip' }).click()
        await expect(page.getByTestId('buddy-tip')).toContainText('Ghost')

        await page.getByTestId('companion-sprig').click()
        await expect(page.getByRole('complementary', { name: 'Sprig' })).toBeVisible()
    })

    test("the Ghost's eye follows the pointer", async ({ page }) => {
        await page.addInitScript(() => globalThis.localStorage.setItem('canopy-companion', 'ghost'))
        await page.goto('attention')
        await settled(page)
        const pupil = page.getByTestId('ghost-body').locator('[data-pupil]')
        await page.mouse.move(0, 0)
        await expect(pupil).toHaveAttribute('transform', /^translate\(-[\d.]+ -[\d.]+\)$/u)
    })

    test('the Ghost flies around, its light swells and dims, faster at the rave, still under reduced motion', async ({
        page,
    }) => {
        // The Ghost's running animations, by name, and how long a round of each takes: a CSS animation by its name, a
        // leg of its flight, which a script starts, by its id.
        const moving = () =>
            page.evaluate(() =>
                Object.fromEntries(
                    document
                        .getAnimations()
                        .map((a): [string, unknown] => [
                            a instanceof CSSAnimation ? a.animationName : a.id,
                            a.effect?.getTiming().duration,
                        ])
                        .filter(([name]) => name.startsWith('ghost-')),
                ),
            )
        await page.addInitScript(() => globalThis.localStorage.setItem('canopy-companion', 'ghost'))
        await page.goto('settings')
        await settled(page)
        await expect.poll(moving).toMatchObject({
            'ghost-flight': expect.any(Number),
            'ghost-flight-shadow': expect.any(Number),
            'ghost-breathe': expect.any(Number),
            'ghost-iris': 11_000,
            'ghost-glow': 4200,
            'ghost-light': 4200,
        })

        await page.getByTestId('light-switch').click()
        await expect.poll(moving).toMatchObject({ 'ghost-glow': 1200, 'ghost-spin': 2400 })
        await page.getByTestId('light-switch').click()

        await page.emulateMedia({ reducedMotion: 'reduce' })
        await expect.poll(moving).toEqual({})
    })

    test("Sprig's eyes follow the pointer", async ({ page }) => {
        await page.goto('attention')
        await settled(page)
        const pupil = page.locator('[data-pupil]').first()
        await page.mouse.move(0, 0)
        await expect(pupil).toHaveAttribute('transform', /^translate\(-[\d.]+ -[\d.]+\)$/u)
    })

    test('Sprig types on its keyboard, new keys each burst, and holds them still under reduced motion', async ({
        page,
    }) => {
        const typing = () =>
            page.evaluate(
                () =>
                    document.getAnimations().filter((a) => a instanceof CSSAnimation && a.animationName === 'buddy-key')
                        .length,
            )
        await page.goto('attention')
        await settled(page)
        await expect(page.locator('[data-testid=buddy] [data-keyboard]')).toHaveCount(1)
        const keys = await typing()
        expect(keys).toBeGreaterThanOrEqual(4)
        expect(keys).toBeLessThanOrEqual(7)

        // The burst ends and the next one begins, on keys that are mounted anew: a burst lasts 5 seconds.
        const first = await page.evaluateHandle(() => new Set(document.querySelectorAll('[data-keyboard] rect')))
        await expect
            .poll(
                () =>
                    first.evaluate((rects) =>
                        [...document.querySelectorAll('[data-keyboard] rect')].every((rect) => !rects.has(rect)),
                    ),
                { timeout: 10_000 },
            )
            .toBe(true)
        expect(await typing()).toBeGreaterThanOrEqual(4)

        await page.emulateMedia({ reducedMotion: 'reduce' })
        await expect.poll(typing).toBe(0)
    })

    test('Sprig stands on the rail foot, never on the spend or the version', async ({ page }) => {
        await page.goto('settings')
        await settled(page)
        // At the page's foot, where the footer of a rail that scrolled with the page once sat under Sprig.
        await page.locator('[data-scroll-restoration-id=page]').evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
        const sprig = await page.getByTestId('buddy').boundingBox()
        const foot = await page.getByTestId('rail-foot').boundingBox()
        const spend = await page.getByTestId('rail-spend').boundingBox()
        if (sprig === null || foot === null || spend === null) {
            throw new Error('Sprig or the rail foot is not shown')
        }
        // The spend is the foot's top, and Sprig stands right on it.
        expect(Math.abs(spend.y - foot.y)).toBeLessThan(1)
        expect(Math.abs(sprig.y + sprig.height - foot.y)).toBeLessThan(1)
    })

    test('Sprig sits out a window whose rail has no room for it, and covers nothing in one that has', async ({
        page,
    }) => {
        await page.setViewportSize({ width: 1280, height: 700 })
        await page.goto('attention')
        await settled(page)
        const buddy = page.getByTestId('buddy')
        await expect(buddy).toBeHidden()
        await expect(page.getByTestId('buddy-sprig')).toBeHidden()

        await page.setViewportSize({ width: 1280, height: 1260 })
        await expect(buddy).toHaveAttribute('data-room', 'roomy')
        await askSprig(page)
        const sprig = await buddy.boundingBox()
        const working = await page.getByTestId('rail-working').boundingBox()
        const foot = await page.getByTestId('rail-foot').boundingBox()
        if (sprig === null || working === null || foot === null) {
            throw new Error('Sprig, the working runs, or the rail foot is not shown')
        }
        expect(working.y + working.height).toBeLessThanOrEqual(sprig.y)
        expect(sprig.y + sprig.height).toBeLessThanOrEqual(foot.y)
    })

    test("Sprig stands over the working runs a little in a laptop's window, and tips there only when asked", async ({
        page,
    }) => {
        // Tall enough for the figure alone over the mock's rail, whose four working rows end in `+1 more`, and short
        // enough that it rises over their foot.
        await page.setViewportSize({ width: 1280, height: 880 })
        await page.goto('attention')
        await settled(page)
        await expect(page.getByTestId('buddy')).toHaveAttribute('data-room', 'tight')
        const figure = page.getByTestId('buddy-sprig')
        await expect(figure).toBeVisible()
        // The tip would cover the runs working now, so it waits to be asked for.
        const tip = page.getByTestId('buddy-tip')
        await expect(tip).toBeHidden()
        const sprig = await figure.boundingBox()
        const working = await page.getByTestId('rail-working').boundingBox()
        if (sprig === null || working === null) {
            throw new Error('Sprig or the working runs are not shown')
        }
        const over = working.y + working.height - sprig.y
        expect(over).toBeGreaterThan(0)
        expect(over).toBeLessThanOrEqual(40)

        await figure.click()
        await expect(tip).toBeVisible()
        await page.getByTestId('buddy-close').click()
        await expect(tip).toBeHidden()
    })

    for (const companion of ['sprig', 'ghost'] as const) {
        test(`the ${companion} standing over the working runs takes none of their clicks`, async ({ page }) => {
            await page.addInitScript((picked) => {
                globalThis.localStorage.setItem('canopy-companion', picked)
            }, companion)
            await page.setViewportSize({ width: 1280, height: 880 })
            await page.goto('attention')
            await settled(page)
            await expect(page.getByTestId('buddy')).toHaveAttribute('data-room', 'tight')
            // A tip asked for and closed keeps its room, hidden, over the rows above.
            await askSprig(page)
            await page.getByTestId('buddy-close').click()
            await expect(page.getByTestId('buddy-tip')).toBeHidden()

            const rows = page.getByTestId('rail-working').getByRole('link')
            await expect(rows).not.toHaveCount(0)
            for (const row of await rows.all()) {
                // Each row takes its clicks across its width, under Sprig's head as well as beside it.
                const missed = await row.evaluate((link) => {
                    const box = link.getBoundingClientRect()
                    const y = box.bottom - 4
                    return [6, 16, 30, 44, box.width / 2, box.width - 6]
                        .map((x) => box.left + x)
                        .filter((x) => !link.contains(document.elementFromPoint(x, y)))
                })
                expect(missed).toEqual([])
            }
            // Sprig itself, within its slot, is still clicked, and so is a row once its tip closes.
            await page.getByTestId('buddy-sprig').click()
            await expect(page.getByTestId('buddy-tip')).toBeVisible()
            await page.getByTestId('buddy-close').click()
            await rows.last().click()
            await expect(page).toHaveURL(/workspace\/runs/u)
        })
    }

    test('a tight rail lets the tips Sprig would offer unasked pass, and a roomy one shows them', async ({ page }) => {
        await page.clock.install()
        await page.setViewportSize({ width: 1280, height: 980 })
        await page.goto('attention')
        await settled(page)
        const tip = page.getByTestId('buddy-tip')
        await expect(page.getByTestId('buddy')).toHaveAttribute('data-room', 'tight')
        await page.clock.runFor(LONGEST_WAIT * 2 * 1000)
        await expect(tip).toBeHidden()

        await page.setViewportSize({ width: 1280, height: 1260 })
        await expect(page.getByTestId('buddy')).toHaveAttribute('data-room', 'roomy')
        await waitForTip(page, tip)
        await page.clock.runFor(21_000)
        await expect(tip).toBeHidden()
    })

    test("Sprig's hats are bought with what canopy has spent, and worn one at a time", async ({ page }) => {
        // $400 in all buys a beanie and a party hat, but not a propeller cap.
        await spentInAll(page, 400)
        await page.goto('settings')
        await settled(page)
        const wallet = page.getByTestId('hats-wallet')
        await expect(wallet).toContainText('left of $400.00 spent')
        // The shop is folded under its wallet until opened.
        await expect(page.getByTestId('hat-party')).toHaveCount(0)
        await page.getByTestId('hats-toggle').click()
        await expect(page.getByTestId('hat-propeller-buy')).toBeDisabled()
        await expect(page.locator('[data-testid=buddy] [data-hat]')).toHaveCount(0)

        await page.getByTestId('hat-beanie-buy').click()
        await expect(wallet).toContainText('$150.00')
        await expect(page.locator('[data-testid=buddy] [data-hat=beanie]')).toHaveCount(1)
        await page.getByTestId('hat-party-buy').click()
        await expect(wallet).toContainText('$100.00')
        await expect(page.locator('[data-testid=buddy] [data-hat=party]')).toHaveCount(1)
        await expect(page.getByTestId('hat-propeller-buy')).toBeDisabled()

        // Owned, a hat goes on and comes off without spending again, and the wardrobe outlasts a reload.
        await page.getByTestId('hat-beanie-wear').click()
        await expect(page.locator('[data-testid=buddy] [data-hat=beanie]')).toHaveCount(1)
        await page.reload()
        await settled(page)
        await expect(wallet).toContainText('$100.00')
        await page.getByTestId('hats-toggle').click()
        await page.getByTestId('hat-beanie-wear').click()
        await expect(page.locator('[data-testid=buddy] [data-hat]')).toHaveCount(0)
        await expect(page.getByTestId('hat-party-wear')).toHaveText('Wear')
    })

    test("the Ghost's shells are bought from the hats' wallet, and one is always worn", async ({ page }) => {
        // $450 in all buys a party hat, then a Sprig Shell and a Pumpkin Shell, but not a Gilded Shell.
        await page.addInitScript(() => globalThis.localStorage.setItem('canopy-companion', 'ghost'))
        await spentInAll(page, 450)
        await page.goto('settings')
        await settled(page)
        await page.getByTestId('hats-toggle').click()
        await page.getByTestId('hat-party-buy').click()
        const wallet = page.getByTestId('shells-wallet')
        await expect(wallet).toContainText('$400.00')
        await expect(page.getByTestId('shell-generalist')).toHaveCount(0)
        await page.getByTestId('shells-toggle').click()
        // The Generalist Shell comes free and worn, and comes off only for another.
        await expect(page.getByTestId('shell-generalist-wear')).toHaveText('Worn')
        await expect(page.getByTestId('shell-generalist-wear')).toBeDisabled()
        await expect(page.locator('[data-testid=buddy] [data-shell=generalist]')).toHaveCount(1)
        await expect(page.getByTestId('shell-gilded-buy')).toBeDisabled()

        await page.getByTestId('shell-sprig-buy').click()
        await expect(wallet).toContainText('$300.00')
        await expect(page.getByTestId('hats-wallet')).toContainText('$300.00')
        await expect(page.locator('[data-testid=buddy] [data-shell=sprig]')).toHaveCount(1)
        await page.getByTestId('shell-pumpkin-buy').click()
        await expect(wallet).toContainText('$0.00')
        await expect(page.locator('[data-testid=buddy] [data-shell=pumpkin]')).toHaveCount(1)
        await expect(page.getByTestId('hat-beanie-buy')).toBeDisabled()

        // Owned, a shell goes back on without spending again, and the vault outlasts a reload.
        await page.getByTestId('shell-sprig-wear').click()
        await expect(page.locator('[data-testid=buddy] [data-shell=sprig]')).toHaveCount(1)
        await page.reload()
        await settled(page)
        await expect(wallet).toContainText('$0.00')
        await expect(page.locator('[data-testid=buddy] [data-shell=sprig]')).toHaveCount(1)
        await page.getByTestId('shells-toggle').click()
        await page.getByTestId('shell-generalist-wear').click()
        await expect(page.locator('[data-testid=buddy] [data-shell=generalist]')).toHaveCount(1)
        await expect(page.getByTestId('shell-sprig-wear')).toHaveText('Wear')
    })

    test('the Ghost in the Sprig Shell', async ({ page }) => {
        await page.addInitScript(() => {
            globalThis.localStorage.setItem('canopy-companion', 'ghost')
            globalThis.localStorage.setItem('canopy-shells', JSON.stringify({ owned: ['sprig'], worn: 'sprig' }))
        })
        await page.clock.setFixedTime(NOW)
        await fixRandom(page)
        await storeTheme(page, 'dark')
        await page.goto('attention')
        await settled(page)
        await askSprig(page)
        await expect(page.getByTestId('buddy')).toHaveScreenshot('ghost-sprig-dark.png')
    })

    test('the mock has spent enough for a party hat and nothing dearer', async ({ page }) => {
        await page.goto('settings')
        await settled(page)
        await expect(page.getByTestId('hats-wallet')).toContainText('$80.81')
        await page.getByTestId('hats-toggle').click()
        await expect(page.getByTestId('hat-party-buy')).toBeEnabled()
        await expect(page.getByTestId('hat-beanie-buy')).toBeDisabled()
        await expect(page.getByTestId('hat-beanie-buy')).toHaveAttribute('title', '$169.19 short')
    })

    for (const theme of THEMES) {
        test(`Sprig in a top hat in ${theme}`, async ({ page }) => {
            await page.addInitScript(() => {
                globalThis.localStorage.setItem('canopy-hats', JSON.stringify({ owned: ['top'], worn: 'top' }))
            })
            await page.clock.setFixedTime(NOW)
            await fixRandom(page)
            await storeTheme(page, theme)
            await page.goto('attention')
            await settled(page)
            await askSprig(page)
            await expect(page.getByTestId('buddy')).toHaveScreenshot(`buddy-hat-${theme}.png`)
        })

        test(`the Ghost in ${theme}`, async ({ page }) => {
            await page.addInitScript(() => globalThis.localStorage.setItem('canopy-companion', 'ghost'))
            await page.clock.setFixedTime(NOW)
            await fixRandom(page)
            await storeTheme(page, theme)
            await page.goto('attention')
            await settled(page)
            await askSprig(page)
            await expect(page.getByTestId('buddy')).toHaveScreenshot(`ghost-${theme}.png`)
        })

        test(`Sprig in ${theme}`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await fixRandom(page)
            await storeTheme(page, theme)
            await page.goto('attention')
            await settled(page)
            await askSprig(page)
            await expect(page.getByTestId('buddy')).toHaveScreenshot(`buddy-${theme}.png`)
        })
    }

    test('the attention page with Sprig in dark', async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await fixRandom(page)
        await storeTheme(page, 'dark')
        await page.goto('attention')
        await settled(page)
        await askSprig(page)
        await screenshotWhole(page, 'attention-sprig-dark.png')
    })
})
