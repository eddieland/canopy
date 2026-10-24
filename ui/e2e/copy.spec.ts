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

test('a copy shows a toast saying what it copied, which closes on its own', async ({ page }) => {
    await page.goto('tickets/ABC-103')
    await page.getByRole('button', { name: 'Copy branch' }).click()
    const toast = page.getByTestId('toast')
    await expect(toast).toContainText('Copied branch')
    await expect(toast).toContainText('agent/ABC-103-billing-v2')
    await expect(toast).toHaveCount(0, { timeout: 6000 })
})

test('a copy the browser refuses says so in its toast', async ({ page }) => {
    await page.goto('tickets/ABC-103')
    await page.evaluate(() => {
        navigator.clipboard.writeText = () => Promise.reject(new Error('refused'))
    })
    await page.getByRole('button', { name: 'Copy branch' }).click()
    await expect(page.getByTestId('toast')).toContainText('Could not copy branch')
    await expect(page.getByRole('button', { name: 'Could not copy branch' })).toBeVisible()
})

test("a review's commit copies whole, though the page shows its first 7 characters", async ({ page }) => {
    await page.goto('pull-requests/reviews/4')
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
    // Whole, though the page shows it from the workspace root: a shell it is pasted into may be anywhere.
    await slot.getByRole('button', { name: "Copy slot 1's path" }).click()
    expect(await clipboard(page)).toBe(`${await workspaceRoot(page)}/.treehouse/web-3f9c2a1b/1/web`)
})

test("a run's worktree and log paths copy whole, though the page shows them from the workspace root", async ({
    page,
}) => {
    await page.goto('runs/41')
    const root = await workspaceRoot(page)
    await page.getByRole('button', { name: 'Copy worktree path' }).click()
    expect(await clipboard(page)).toBe(`${root}/.treehouse/web-3f9c2a1b/1/web`)
    await page.getByRole('button', { name: 'Copy log path' }).click()
    expect(await clipboard(page)).toBe(`${root}/.canopy/runs/41.log`)
})

test("a run's paths have no copy button while the server's meta cannot be read, not one copying them short", async ({
    page,
}) => {
    await page.route('**/api/meta', (route) => route.abort())
    await page.goto('runs/41')
    await expect(page.getByText('.canopy/runs/41.log')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Copy log path' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Copy worktree path' })).toHaveCount(0)
})

test("a session id copies from its run's row, its button showing only while the row is hovered", async ({ page }) => {
    await page.goto('runs')
    await settled(page)
    const row = page.getByTestId('run-41')
    const copy = row.getByRole('button', { name: 'Copy session id' })
    await expect(copy).toHaveCSS('opacity', '0')
    await row.hover()
    await expect(copy).toHaveCSS('opacity', '1')
    await copy.click()
    expect(await clipboard(page)).toBe('ses_mock41')
})

test("a chore run's session id copies from its row", async ({ page }) => {
    await page.goto('chores/deps')
    await settled(page)
    const row = page.getByTestId('chore-run-2')
    await row.hover()
    await row.getByRole('button', { name: 'Copy session id' }).click()
    expect(await clipboard(page)).toBe('ses_chore2')
})

test("a chore run's log path copies whole, from its page and from its row", async ({ page }) => {
    await page.goto('chores/deps/runs/2')
    const root = await workspaceRoot(page)
    await page.getByRole('button', { name: 'Copy log path' }).click()
    expect(await clipboard(page)).toBe(`${root}/.canopy/chore-runs/deps/2.log`)
    await page.goto('chores/deps')
    await settled(page)
    const row = page.getByTestId('chore-run-2')
    await row.hover()
    await row.getByRole('button', { name: 'Copy log path' }).click()
    expect(await clipboard(page)).toBe(`${root}/.canopy/chore-runs/deps/2.log`)
})

test("a tick's output path copies whole, though the page shows it from the workspace root", async ({ page }) => {
    await page.goto('runs/ticks/2')
    await page.getByRole('button', { name: 'Copy output path' }).click()
    expect(await clipboard(page)).toBe(`${await workspaceRoot(page)}/.canopy/ticks/2.log`)
})

/** The workspace root the server's meta gives, which a path shown from it is joined to when copied. */
async function workspaceRoot(page: Page): Promise<string> {
    const meta = (await (await page.request.get('api/meta')).json()) as { workspace_root: string }
    return meta.workspace_root
}

/** What the page's clipboard holds. */
function clipboard(page: Page): Promise<string> {
    return page.evaluate(() => navigator.clipboard.readText())
}
