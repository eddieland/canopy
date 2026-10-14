import { expect, test } from '@playwright/test'

import { NOW, screenshotWhole, settled, signIn, spentInAll, storeTheme, THEMES } from './helpers.ts'

// Tall enough that the rail has room for Sprig and its bubble under the mock's three working runs.
test.use({ viewport: { width: 1280, height: 1200 } })

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('Sprig is off until Settings turns it on', async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    await expect(page.getByTestId('buddy')).toHaveCount(0)
    await expect(page.getByTestId('fun-sprig')).not.toBeChecked()

    await page.getByTestId('fun-sprig').click()
    await expect(page.getByTestId('buddy-tip')).toBeVisible()
    await page.reload()
    await settled(page)
    await expect(page.getByTestId('buddy')).toBeVisible()
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

    test('Sprig offers a tip on every page, another on a click, and closes when told', async ({ page }) => {
        await page.goto('attention')
        await settled(page)
        const tip = page.getByTestId('buddy-tip')
        await expect(tip).toBeVisible()
        const first = await tip.textContent()

        await page.getByTestId('buddy-another').click()
        await expect(tip).not.toHaveText(first ?? '')
        const second = await tip.textContent()
        await page.getByTestId('buddy-sprig').click()
        await expect(tip).not.toHaveText(second ?? '')

        await page.getByTestId('buddy-close').click()
        await expect(tip).toBeHidden()
        await expect(page.getByTestId('buddy-sprig')).toBeVisible()

        // A new page, a new tip.
        await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Settings' }).click()
        await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
        await expect(tip).toBeVisible()
    })

    test('Sprig leaves its tip alone on another page offering the same one', async ({ page }) => {
        await page.goto('tickets')
        await settled(page)
        const tip = page.getByTestId('buddy-tip')
        const shown = await tip.textContent()

        // A ticket's page offers the same tip: the bubble stays as it was, not closed and opened again.
        await tip.evaluate((el) => {
            el.dataset.kept = ''
        })
        await page.getByTestId('tickets').getByRole('link', { name: 'ABC-102', exact: true }).click()
        await expect(page).toHaveURL(/tickets\/ABC-102$/u)
        await expect(tip).toHaveText(shown ?? '')
        await expect(tip).toHaveAttribute('data-kept', '')

        // Closed, it stays closed back on the list.
        await page.getByTestId('buddy-close').click()
        await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Tickets' }).click()
        await expect(page).toHaveURL(/tickets$/u)
        await expect(page.getByTestId('tickets')).toBeVisible()
        await expect(tip).toBeHidden()
    })

    test("Don't show me tips again turns Sprig off until Settings turns it back on", async ({ page }) => {
        await page.goto('settings')
        await settled(page)
        const buddy = page.getByTestId('buddy')
        await expect(page.getByTestId('fun-sprig')).toBeChecked()

        await page.getByTestId('buddy-dismiss').click()
        await expect(buddy).toHaveCount(0)
        await expect(page.getByTestId('fun-sprig')).not.toBeChecked()
        await page.reload()
        await settled(page)
        await expect(buddy).toHaveCount(0)

        await page.getByTestId('fun-sprig').click()
        await expect(buddy).toBeVisible()
        await expect(page.getByTestId('buddy-tip')).toBeVisible()
    })

    test("Sprig's eyes follow the pointer", async ({ page }) => {
        await page.goto('attention')
        await settled(page)
        const pupil = page.locator('[data-pupil]').first()
        await page.mouse.move(0, 0)
        await expect(pupil).toHaveAttribute('transform', /^translate\(-[\d.]+ -[\d.]+\)$/u)
    })

    test('Sprig stands above the rail footer, never on the version', async ({ page }) => {
        await page.goto('settings')
        await settled(page)
        // At the page's foot, where the footer of a rail that scrolled with the page once sat under Sprig.
        await page.locator('[data-scroll-restoration-id=page]').evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
        const sprig = await page.getByTestId('buddy').boundingBox()
        const footer = await page.getByTestId('rail-footer').boundingBox()
        if (sprig === null || footer === null) {
            throw new Error('Sprig or the rail footer is not shown')
        }
        expect(sprig.y + sprig.height).toBeLessThanOrEqual(footer.y)
    })

    test('Sprig sits out a window whose rail has no room for it, and covers nothing in one that has', async ({
        page,
    }) => {
        await page.setViewportSize({ width: 1280, height: 800 })
        await page.goto('attention')
        await settled(page)
        const buddy = page.getByTestId('buddy')
        await expect(buddy).toBeHidden()
        await expect(page.getByTestId('buddy-sprig')).toBeHidden()

        await page.setViewportSize({ width: 1280, height: 1200 })
        await expect(buddy).toBeVisible()
        const sprig = await buddy.boundingBox()
        const spend = await page.getByTestId('rail-spend').boundingBox()
        if (sprig === null || spend === null) {
            throw new Error('Sprig or the rail spend is not shown')
        }
        expect(spend.y + spend.height).toBeLessThanOrEqual(sprig.y)

        // A closed bubble keeps its room, so closing it never brings in a Sprig that had none.
        await page.getByTestId('buddy-close').click()
        await page.setViewportSize({ width: 1280, height: 800 })
        await expect(buddy).toBeHidden()
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

    test('the mock has spent too little for any hat', async ({ page }) => {
        await page.goto('settings')
        await settled(page)
        await expect(page.getByTestId('hats-wallet')).toContainText('$9.23')
        await page.getByTestId('hats-toggle').click()
        await expect(page.getByTestId('hat-party-buy')).toBeDisabled()
        await expect(page.getByTestId('hat-party-buy')).toHaveAttribute('title', '$40.77 short')
    })

    for (const theme of THEMES) {
        test(`Sprig in a top hat in ${theme}`, async ({ page }) => {
            await page.addInitScript(() => {
                globalThis.localStorage.setItem('canopy-hats', JSON.stringify({ owned: ['top'], worn: 'top' }))
            })
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, theme)
            await page.goto('attention')
            await settled(page)
            await expect(page.getByTestId('buddy')).toHaveScreenshot(`buddy-hat-${theme}.png`)
        })

        test(`Sprig in ${theme}`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await storeTheme(page, theme)
            await page.goto('attention')
            await settled(page)
            await expect(page.getByTestId('buddy')).toHaveScreenshot(`buddy-${theme}.png`)
        })
    }

    test('the attention page with Sprig in dark', async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await storeTheme(page, 'dark')
        await page.goto('attention')
        await settled(page)
        await expect(page.getByTestId('buddy')).toBeVisible()
        await screenshotWhole(page, 'attention-sprig-dark.png')
    })
})
