import { expect, test } from '@playwright/test'

import { signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the sessions page opens on yours, with the archived and canopy's each a filter away", async ({ page }) => {
    await page.goto('workspace/sessions')
    await expect(page.getByRole('heading', { name: 'Sessions outside canopy' })).toBeVisible()
    const rows = page.getByTestId('sessions').getByTestId('session')
    // The mock's own, newest first, the deploy question's subagent under it; the client's never, the archived not yet.
    await expect(rows).toHaveCount(5)
    await expect(rows.nth(1)).toContainText('Find where deploy.sh waits on the health check')
    await expect(rows.nth(1)).toContainText('subagent')
    await expect(page.getByText('Globex invoice export totals')).toHaveCount(0)
    await expect(page.getByText("Try the new router's loaders")).toHaveCount(0)
    await expect(page.getByTestId('sessions-progress')).toContainText('Read every session updated up to')

    const archived = page.getByRole('link', { name: 'archived' })
    await expect(archived).toHaveAttribute('aria-pressed', 'false')
    await archived.click()
    await expect(page).toHaveURL(/\/workspace\/sessions\?archived=true$/u)
    await expect(archived).toHaveAttribute('aria-pressed', 'true')
    await expect(rows).toHaveCount(6)
    await expect(rows.filter({ hasText: "Try the new router's loaders" })).toContainText('archived')

    await page.getByRole('navigation', { name: 'Whose sessions' }).getByRole('link', { name: "canopy's" }).click()
    await expect(page.getByRole('heading', { name: "canopy's sessions" })).toBeVisible()
    await rows
        .filter({ hasText: 'ABC-101 implement', hasNotText: 'subagent' })
        .getByRole('link', { name: 'run:41' })
        .click()
    await expect(page).toHaveURL(/\/workspace\/runs\/41$/u)
})

for (const { path, list } of [
    { path: 'workspace/sessions', list: 'sessions' },
    { path: 'search?q=deploy', list: 'search-sessions-outside' },
]) {
    test(`${path}: a row's copy button shows while the pointer is over the row, and names its session`, async ({
        page,
    }) => {
        await page.goto(path)
        const row = page
            .getByTestId(list)
            .getByTestId('session')
            .filter({ hasText: 'Why does the deploy script hang on staging?', hasNotText: 'subagent' })
        const copy = row.getByRole('button', {
            name: 'Copy reopen command of Why does the deploy script hang on staging?',
        })
        // Hidden until the row is hovered: a button on every line would be noise.
        await page.getByRole('heading', { level: 1 }).hover()
        await expect(copy).toHaveCSS('opacity', '0')
        await row.getByText('Why does the deploy script hang on staging?', { exact: true }).hover()
        await expect(copy).toHaveCSS('opacity', '1')
    })
}
