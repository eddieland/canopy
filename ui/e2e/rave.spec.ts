import { expect, test } from '@playwright/test'
import type { Locator } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

/** The animation running on the rave's dark, or `none` when it holds still. */
function animation(rave: Locator): Promise<string> {
    return rave.locator('.rave-dark').evaluate((dark) => getComputedStyle(dark).animationName)
}

test('the light switch starts the rave over every page, and it lasts until flipped back', async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    const rave = page.getByTestId('rave')
    const lightSwitch = page.getByRole('switch', { name: 'Lightswitch rave' })
    await expect(rave).toHaveCount(0)
    await expect(lightSwitch).not.toBeChecked()

    await lightSwitch.click()
    await expect(lightSwitch).toBeChecked()
    await expect(rave).toBeVisible()
    expect(await animation(rave)).toBe('rave-switch')

    // It takes no pointer: the page under it works as ever, and the rave goes along.
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Workspace' }).click()
    await expect(page).toHaveURL(/\/workspace$/u)
    await expect(rave).toBeVisible()
    await page.reload()
    await settled(page)
    await expect(rave).toBeVisible()

    await page.goto('settings')
    await settled(page)
    await lightSwitch.click()
    await expect(lightSwitch).not.toBeChecked()
    await expect(rave).toHaveCount(0)
    await page.reload()
    await settled(page)
    await expect(rave).toHaveCount(0)
})

test('under reduced motion the rave holds still, the lights off', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('settings')
    await settled(page)
    await page.getByRole('switch', { name: 'Lightswitch rave' }).click()
    const rave = page.getByTestId('rave')
    await expect(rave).toBeVisible()
    expect(await animation(rave)).toBe('none')
    await expect(rave.locator('.rave-dark')).toHaveCSS('opacity', '0.6')
})

test.describe('with Sprig on', () => {
    // Tall enough that the rail has room for Sprig under the mock's four working rows.
    test.use({ viewport: { width: 1280, height: 1200 } })

    test('Sprig dances to it, waving its glow sticks, and holds still under reduced motion', async ({ page }) => {
        await page.addInitScript(() => globalThis.localStorage.setItem('canopy-buddy', 'on'))
        await page.goto('settings')
        await settled(page)
        const sprig = page.getByTestId('buddy')
        const sticks = sprig.getByTestId('buddy-glow-sticks')
        await expect(sticks).toHaveCount(0)

        await page.getByRole('switch', { name: 'Lightswitch rave' }).click()
        await expect(sticks).toBeVisible()
        const animations = () =>
            sprig.evaluate((buddy) =>
                [buddy.querySelector('[data-testid="buddy-body"]'), buddy.querySelector('.animate-buddy-wave')].map(
                    (drawn) => (drawn === null ? null : getComputedStyle(drawn).animationName),
                ),
            )
        expect(await animations()).toEqual(['buddy-dance', 'buddy-wave'])

        await page.emulateMedia({ reducedMotion: 'reduce' })
        expect(await animations()).toEqual(['none', 'none'])

        await page.getByRole('switch', { name: 'Lightswitch rave' }).click()
        await expect(sticks).toHaveCount(0)
    })
})
