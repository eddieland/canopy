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

test("a row's directory narrows the list to the sessions that ran there, and Back undoes it", async ({ page }) => {
    await page.goto('workspace/sessions')
    const rows = page.getByTestId('sessions').getByTestId('session')
    await expect(rows).toHaveCount(5)
    await page.getByRole('link', { name: '…/acme/infra' }).first().click()
    await expect(page).toHaveURL(/\/workspace\/sessions\?directory=%2Fhome%2Fop%2Facme%2Finfra$/u)
    // The deploy question and its subagent, which ran there too; the count follows them.
    await expect(rows).toHaveCount(2)
    await expect(page.getByTestId('sessions-count')).toHaveText('2')
    await expect(page.getByTestId('sessions-directory')).toContainText('…/acme/infra')

    await page.goBack()
    await expect(page).toHaveURL(/\/workspace\/sessions$/u)
    await expect(rows).toHaveCount(5)
    await expect(page.getByTestId('sessions-directory')).toHaveCount(0)

    await page.goForward()
    await expect(rows).toHaveCount(2)
    await page.getByRole('link', { name: 'Clear the directory' }).click()
    await expect(page).toHaveURL(/\/workspace\/sessions$/u)
    await expect(rows).toHaveCount(5)
})

test("a directory sessions.exclude names lists nothing, though asked for by its link's flag", async ({ page }) => {
    await page.goto('workspace/sessions?archived=true&directory=%2Fhome%2Fop%2Fclients%2Fglobex')
    await expect(page.getByTestId('sessions-directory')).toContainText('…/clients/globex')
    await expect(page.getByText('no session outside canopy in /home/op/clients/globex yet')).toBeVisible()
    await expect(page.getByText('Globex invoice export totals')).toHaveCount(0)
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

test('a cost and a comparison narrow the list to the sessions within it, kept in the address', async ({ page }) => {
    await page.goto('workspace/sessions')
    const rows = page.getByTestId('sessions').getByTestId('session')
    await expect(rows).toHaveCount(5)
    const filter = page.getByRole('group', { name: 'Filter by cost' })
    await expect(filter.getByRole('radio', { name: 'at least' })).toBeChecked()

    await filter.getByRole('textbox', { name: 'Cost in dollars' }).fill('1.12')
    await expect(page).toHaveURL(/\/workspace\/sessions\?cost=gte(:|%3A)1\.12$/u)
    await expect(rows).toHaveCount(2)
    await expect(rows.nth(0)).toContainText('XYZ-12 implement')
    await expect(rows.nth(1)).toContainText('Bisect the flaky checkout test')

    await filter.getByRole('radio', { name: 'more than' }).click()
    await expect(page).toHaveURL(/\/workspace\/sessions\?cost=gt(:|%3A)1\.12$/u)
    await expect(rows).toHaveCount(1)

    // Below the cheapest of them, only the subagent, in a row of its own: its cost is its own.
    await filter.getByRole('radio', { name: 'less than' }).click()
    await filter.getByRole('textbox', { name: 'Cost in dollars' }).fill('0.2')
    await expect(rows).toHaveCount(1)
    await expect(rows.nth(0)).toContainText('Find where deploy.sh waits on the health check')
    await filter.getByRole('textbox', { name: 'Cost in dollars' }).fill('0.1')
    await expect(page.getByText('no session outside canopy that cost less than $0.10')).toBeVisible()

    // The bound holds through the other filters, and clearing it lists every session again.
    await expect(page.getByRole('link', { name: 'archived' })).toHaveAttribute('href', /cost=lt(:|%3A)0\.1/u)
    await filter.getByRole('button', { name: 'Clear the cost' }).click()
    await expect(page).toHaveURL(/\/workspace\/sessions$/u)
    await expect(rows).toHaveCount(5)
})
