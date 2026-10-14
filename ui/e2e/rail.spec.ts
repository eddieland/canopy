import { expect, test } from '@playwright/test'

import { NOW, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await signIn(page)
})

test('the rail lists the runs working now, the running ones first, on every page', async ({ page }) => {
    await page.goto('tickets')
    await settled(page)
    const working = page.getByTestId('rail-working')
    await expect(working.getByRole('link')).toHaveCount(3)
    await expect(working.getByRole('link').first()).toContainText('ABC-101')
    await expect(working.getByRole('link').nth(2)).toContainText('ABC-102')
    await expect(page.getByTestId('rail-run-42')).toContainText('waiting on you')
    await expect(page.getByTestId('rail-run-41')).toContainText('Sign in with SSO')

    await page.getByTestId('rail-run-41').click()
    await expect(page).toHaveURL(/\/runs\/41$/u)
    await expect(page.getByTestId('rail-run-41')).toBeVisible()
})

test('the rail shows the spend of the last day and the last 30, and the version at its foot', async ({ page }) => {
    const spend = (await (await page.request.get('api/spend')).json()) as { day: { cost_usd: number } }
    await page.goto('ticks')
    await settled(page)
    await expect(page.getByTestId('rail-spend-24h')).toHaveText(`$${spend.day.cost_usd.toFixed(2)}`)
    await expect(page.getByTestId('rail-spend-30d')).toHaveText(/^\$\d+\.\d\d$/u)
    await expect(page.getByTestId('rail-footer')).toContainText(/canopy \S+/u)
})

test('the version stays at the window foot on a page longer than the window', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 600 })
    await page.goto('settings')
    await settled(page)
    const scroller = page.locator('[data-scroll-restoration-id=page]')
    expect(await scroller.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)

    const version = page.getByTestId('rail-version')
    await expect(version).toBeInViewport()
    await scroller.evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
    await expect(version).toBeInViewport()
    const box = await page.getByTestId('rail-footer').boundingBox()
    expect(box === null ? 0 : Math.round(box.y + box.height)).toBe(600)
})
