import { expect, test } from '@playwright/test'

import { plan, settled, signIn, writePlan } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("settings sets a plan's text size, which the plan keeps after a reload", async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    await expect(page.getByTestId('plan-text-normal')).toHaveAttribute('aria-checked', 'true')
    const sample = page.getByTestId('plan-text-sample').locator('p').last()
    await expect(sample).toHaveCSS('font-size', '16px')
    await page.getByTestId('plan-text-large').click()
    await expect(page.getByTestId('plan-text-large')).toHaveAttribute('aria-checked', 'true')
    // The sample under the choice shows the size picked before a plan is opened.
    await expect(sample).toHaveCSS('font-size', '18px')

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
    await page.getByTestId('plan-text-tiny').click()
    await page.goto('plan-editor')
    await settled(page)
    await expect(plan(page)).toHaveCSS('font-size', '12px')

    await page.goto('settings')
    await settled(page)
    await page.getByTestId('plan-text-normal').click()
    await page.goto('plan-editor')
    await settled(page)
    await expect(plan(page)).toHaveCSS('font-size', '16px')
})

test("a plan's table and a diagram's caption keep their step under its text at every size", async ({ page }) => {
    await page.goto('plan-editor')
    await settled(page)
    await writePlan(
        page,
        '# Plan\n\n| Key | Default |\n| --- | --- |\n| `retry.limit` | 4 |\n\n```mermaid\npie\n  "a": 1\n```\n',
    )
    const doc = plan(page)
    const table = doc.getByRole('table')
    const caption = doc.getByText(/^Not drawn:/u)
    await expect(table).toHaveCSS('font-size', '14px')
    await expect(caption).toHaveCSS('font-size', '14px')
    // As wide as what it holds, not the plan's measure.
    const widths = await table.evaluate((element) => ({
        table: element.getBoundingClientRect().width,
        plan: element.closest('.plan-doc')?.getBoundingClientRect().width ?? 0,
    }))
    expect(widths.table).toBeLessThan(widths.plan / 2)

    await page.goto('settings')
    await settled(page)
    await page.getByTestId('plan-text-tiny').click()
    await page.goto('plan-editor')
    await settled(page)
    await writePlan(page, '# Plan\n\n| Key | Default |\n| --- | --- |\n| `retry.limit` | 4 |\n')
    // Tiny's 12px body, a step down: under it, never over it, as a fixed size was.
    await expect(plan(page).getByRole('table')).toHaveCSS('font-size', '10.5px')
})
