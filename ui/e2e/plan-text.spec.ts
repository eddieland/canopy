import { expect, test } from '@playwright/test'

import { plan, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("settings sets a plan's text size, which the plan keeps after a reload", async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    await expect(page.getByTestId('plan-text-normal')).toHaveAttribute('aria-checked', 'true')
    await page.getByTestId('plan-text-large').click()
    await expect(page.getByTestId('plan-text-large')).toHaveAttribute('aria-checked', 'true')

    await page.goto('plan-editor')
    await settled(page)
    const doc = plan(page)
    await expect(doc).toHaveCSS('font-size', '18px')
    await page.reload()
    await settled(page)
    await expect(plan(page)).toHaveCSS('font-size', '18px')

    await page.goto('settings')
    await settled(page)
    await page.getByTestId('plan-text-small').click()
    await page.goto('plan-editor')
    await settled(page)
    await expect(plan(page)).toHaveCSS('font-size', '14px')

    await page.goto('settings')
    await settled(page)
    await page.getByTestId('plan-text-normal').click()
    await page.goto('plan-editor')
    await settled(page)
    await expect(plan(page)).toHaveCSS('font-size', '16px')
})
