import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

// A row's cells as a person reads them: its head, then each cell but a bar's, which is the eye's alone.
const READ = 'th, td:not([aria-hidden])'

test('the nav opens Tools under Reports: each agent by its calls, then each server and tool', async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Tools' }).click()
    await expect(page).toHaveURL(/\/reports\/tools$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tools')
    // The mock's day of offers (canopy/serve/mock/tool_use.py) and the calls its runs recorded.
    await expect(page.locator('main header p')).toHaveText(
        '3 servers and 7 tools offered over 7 days · 4 never called · 292 calls, 15 failed',
    )
    await expect(page.getByTestId('tools-window-7')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('tools-agent-table').getByRole('rowheader')).toHaveText([
        'canopy-worker',
        'canopy-worker-private',
        'canopy-overseer',
        'canopy-reviewer',
        'canopy-chore-deps',
        'canopy-planner',
        'canopy-chore',
    ])
    await expect(page.getByTestId('tools-agent-canopy-worker').locator(READ)).toHaveText([
        'canopy-worker',
        '4',
        '0',
        '3',
        '7',
        '5',
        '160',
        '12',
        '105.6k',
    ])
    await expect(page.getByTestId('tools-offers')).toContainText('No offer on record for 9 of 30 runs')
    // The most called first; a server's tool is listed by its calls, with no count of the runs offered it.
    const rows = page.getByTestId('tools-row-table')
    await expect(rows.getByRole('rowheader').first()).toHaveText('bash')
    await expect(page.getByTestId('tools-row-tool-github_pull_request_read').locator(READ)).toHaveText([
        'github_pull_request_read',
        'of github',
        '–',
        '–',
        '27',
        '0',
        '86.5k',
    ])
    // The error tracker's server: offered to every worker's run, called by none.
    await expect(page.getByTestId('tools-row-server-sentry').locator(READ)).toHaveText([
        'sentry',
        'MCP server',
        '6',
        'never',
        '0',
        '0',
        '0',
    ])
    await expect(page.getByTestId('tools-names')).toContainText('An offer names a server, not its tools')
})

test("an agent's name narrows the rows to its own, least called first what to deny it, and back", async ({ page }) => {
    await page.goto('reports/tools')
    await settled(page)
    await page.getByTestId('tools-agent-table').getByRole('link', { name: 'canopy-reviewer' }).click()
    await expect(page).toHaveURL(/\/reports\/tools\?agent=canopy-reviewer$/u)
    await expect(page.getByTestId('tools-scope')).toHaveText('canopy-reviewer')
    await expect(page.getByTestId('tools-count')).toHaveText('7 of 12')
    await page.getByTestId('tools-sort-least').click()
    await expect(page).toHaveURL(/\/reports\/tools\?agent=canopy-reviewer&order=least$/u)
    // What it was offered and never called leads, the servers first among equals.
    await expect(page.getByTestId('tools-row-table').getByRole('rowheader')).toHaveText([
        'github',
        'jira',
        'glob',
        'grep',
        'bash',
        'read',
        'skill',
    ])
    await page.getByTestId('tools-rows').getByRole('link', { name: 'every agent' }).click()
    await expect(page).toHaveURL(/\/reports\/tools\?order=least$/u)
    await expect(page.getByTestId('tools-count')).toHaveText('12')
})

test('the window is kept in the address beside the order', async ({ page }) => {
    await page.goto('reports/tools?order=failed')
    await settled(page)
    await expect(page.getByTestId('tools-row-table').getByRole('rowheader').first()).toHaveText('bash')
    await page.getByTestId('tools-window-30').click()
    await expect(page).toHaveURL(/\/reports\/tools\?order=failed&days=30$/u)
    await expect(page.locator('main header p')).toHaveText(
        '3 servers and 7 tools offered over 30 days · 4 never called · 297 calls, 15 failed',
    )
})

test('the reports page has a card for the Tools report, its line over 30 days', async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await expect(page.getByTestId('reports-card-tools-line')).toHaveText(
        '3 servers and 7 tools offered over 30 days · 4 never called · 297 calls, 15 failed',
    )
    await page.getByTestId('reports-card-tools').click()
    await expect(page).toHaveURL(/\/reports\/tools\?days=30$/u)
})
