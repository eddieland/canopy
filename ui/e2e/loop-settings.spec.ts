import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// Loop settings over the mock's config, read only: nothing here saves.

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("a key's anchor opens the page at its row", async ({ page }) => {
    await page.goto('settings/limits#policy.max_resume_attempts')
    await settled(page)
    await expect(page.getByRole('textbox', { name: 'policy.max_resume_attempts' })).toBeInViewport()
})

test('the index takes you to a band, and marks the one in view', async ({ page }) => {
    await page.goto('settings/limits')
    await settled(page)
    const index = page.getByRole('navigation', { name: 'Bands' })
    await index.getByRole('link', { name: /^Guardrails/u }).click()
    await expect(page).toHaveURL(/#band-guardrails$/u)
    await expect(page.getByRole('heading', { name: 'Guardrails' })).toBeInViewport()
    await expect(index.getByRole('link', { name: /^Guardrails/u })).toHaveAttribute('data-current', 'true')
    await expect(index.getByRole('link', { name: /^Capacity/u })).not.toHaveAttribute('data-current')
})

test('?q= filters the rows to those whose label or key holds it, and Escape shows them all again', async ({ page }) => {
    await page.goto('settings/limits?q=flaky')
    await settled(page)
    const form = page.getByRole('form', { name: 'Loop settings' })
    await expect(form.getByRole('listitem')).toHaveCount(1)
    await expect(form.getByRole('textbox', { name: 'trust.max_flaky_kicks' })).toBeVisible()
    await expect(
        page.getByRole('navigation', { name: 'Bands' }).getByRole('link', { name: 'Capacity' }),
    ).toHaveAttribute('data-hidden', 'true')
    const filter = page.getByRole('searchbox', { name: 'Filter settings by label or key' })
    await filter.press('Escape')
    await expect(page).not.toHaveURL(/q=/u)
    await expect(form.getByRole('textbox', { name: 'capacity.max_workers' })).toBeVisible()
})
