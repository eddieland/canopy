import { expect, type Locator, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

/** Resolves once `highlight` sits exactly on `link`, as it does once its slide has ended. */
async function covers(highlight: Locator, link: Locator): Promise<void> {
    await expect(async () => {
        const [h, l] = await Promise.all([highlight.boundingBox(), link.boundingBox()])
        expect(h?.y).toBeCloseTo(l?.y ?? Number.NaN, 0)
    }).toPass()
}

test('the nav highlight slides to the item a navigation lands on', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    const highlight = page.getByTestId('nav-highlight')
    await covers(highlight, nav.getByRole('link', { name: 'Attention' }))

    await nav.getByRole('link', { name: 'Worktrees' }).click()
    await covers(highlight, nav.getByRole('link', { name: 'Worktrees' }))

    await page.getByRole('link', { name: 'Tickets' }).click()
    await page.getByTestId('tickets').getByRole('link', { name: 'ABC-102' }).click()
    await covers(highlight, nav.getByRole('link', { name: 'Tickets' }))
})

test('under reduced motion, counters read their values and nothing waits on an animation', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('attention')
    await settled(page)
    await expect(page.getByTestId('counter-attention')).toContainText('5')
    const running = await page.evaluate(() => document.getAnimations().map((a) => a.constructor.name))
    expect(running).toEqual([])
})
