import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.use({ permissions: ['clipboard-read', 'clipboard-write'] })

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("a ticket's branch copies from beside it, and the button says it did", async ({ page }) => {
    await page.goto('tickets/ABC-103')
    const copy = page.getByRole('button', { name: 'Copy branch' })
    await copy.click()
    expect(await clipboard(page)).toBe('agent/ABC-103-billing-v2')
    await expect(page.getByRole('button', { name: 'Copied branch' })).toBeVisible()
    // Then it reads Copy again.
    await expect(copy).toBeVisible()
})

test("a review's commit copies whole, though the page shows its first 7 characters", async ({ page }) => {
    await page.goto('reviews/4')
    const commit = page.getByRole('button', { name: 'Copy commit' })
    await commit.click()
    expect(await clipboard(page)).toMatch(/^[0-9a-f]{40}$/u)
})

test("a slot's copy buttons show only while its row is hovered, and copy its path and branch", async ({ page }) => {
    await page.goto('worktrees')
    await settled(page)
    const slot = page.getByTestId('pool-web').getByTestId('worktree-1')
    const branch = slot.getByRole('button', { name: 'Copy branch' })
    await expect(branch).toHaveCSS('opacity', '0')
    await slot.hover()
    await expect(branch).toHaveCSS('opacity', '1')
    await branch.click()
    expect(await clipboard(page)).toBe('agent/ABC-101-login')
    await slot.getByRole('button', { name: "Copy slot 1's path" }).click()
    expect(await clipboard(page)).toBe('.treehouse/web-3f9c2a1b/1/web')
})

/** What the page's clipboard holds. */
function clipboard(page: Page): Promise<string> {
    return page.evaluate(() => navigator.clipboard.readText())
}
