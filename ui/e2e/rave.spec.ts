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
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Runs' }).click()
    await expect(page).toHaveURL(/\/runs$/u)
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
