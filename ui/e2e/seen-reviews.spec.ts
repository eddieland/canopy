import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { NOW, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await signIn(page)
    // A browser that has read the reviews before and seen none of them, so every result in the mock journal is new.
    // Only when nothing is stored yet: what the test marks seen outlasts its navigations.
    await page.addInitScript(() => {
        if (localStorage.getItem('canopy-seen-reviews') === null) {
            localStorage.setItem('canopy-seen-reviews', '[]')
        }
    })
})

/** How many new reviews the Reviews nav item counts, from the words it says them in on hover: 0 when it shows none. */
async function counted(page: Page): Promise<number> {
    const count = page.getByRole('navigation', { name: 'Main' }).getByTestId('nav-reviews-count')
    if ((await count.count()) === 0) {
        return 0
    }
    return Number(/^(\d+) new reviews? to read$/u.exec((await count.getAttribute('title')) ?? '')?.[1])
}

test('the nav counts the reviews not opened, until each is opened or all are marked seen', async ({ page }) => {
    await page.goto('reviews')
    await settled(page)
    const total = await counted(page)
    expect(total).toBeGreaterThan(1)
    const fresh = page
        .getByTestId('reviews')
        .getByRole('listitem')
        .filter({ has: page.getByText('new', { exact: true }) })
    await expect(fresh).toHaveCount(total)

    await fresh
        .first()
        .getByRole('link', { name: /^review:\d+$/u })
        .click()
    await expect(page).toHaveURL(/\/reviews\/\d+$/u)
    await expect.poll(() => counted(page)).toBe(total - 1)

    await page.goBack()
    await expect(fresh).toHaveCount(total - 1)
    await page.getByRole('button', { name: `mark ${total - 1} seen` }).click()
    await expect.poll(() => counted(page)).toBe(0)
    await expect(fresh).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^mark \d+ seen$/u })).toHaveCount(0)
})
