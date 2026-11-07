import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// What a run changed (DESIGN §45), on its page and its ticket's runs list, as the mock records it: run 39 kept both
// diffs, run 40 left its fix unpushed, run 37 kept none, and task 1's run kept its own change.

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("a run's page shows what it changed, and toggles to its branch against the base", async ({ page }) => {
    await page.goto('workspace/runs/39')
    await settled(page)
    const diff = page.getByRole('region', { name: /^Diff: web · 71c3e0a\.\.9b2f4c6$/u })
    await expect(diff.getByTestId('diff-file')).toHaveCount(2)
    await expect(diff.getByTestId('diff-file').first()).toContainText('controller.abort()')
    await diff.getByRole('radio', { name: 'Branch vs base' }).click()
    await expect(diff.getByText(/^The whole branch against its base/u)).toBeVisible()
    await expect(diff.getByTestId('diff-file')).toHaveCount(2)
    // Over the transcript.
    const panels = await page.locator('main h2').allTextContents()
    expect(panels.indexOf('Diff')).toBeLessThan(panels.indexOf('Transcript'))
})

test("an unpushed run's diff is marked as work not on origin, and one not kept says why", async ({ page }) => {
    await page.goto('workspace/runs/40')
    await settled(page)
    await expect(page.getByTestId('run-change-range')).toHaveText('web · a40d2f9..d8e61b3')
    await expect(page.getByTestId('run-change-unpushed')).toContainText('Work not on origin')
    await expect(page.getByTestId('diff-file')).toContainText('frameLocator')

    await page.goto('workspace/runs/37')
    await settled(page)
    await expect(page.getByTestId('run-change')).toContainText(
        'no diff kept: the run left no branch on origin and no commit of its own in its slot',
    )
    await expect(page.getByTestId('diff-file')).toHaveCount(0)
})

test("a task run's page shows its diff as a worker run's does", async ({ page }) => {
    await page.goto('tasks/1/runs/1')
    await settled(page)
    await expect(page.getByTestId('run-change-range')).toHaveText('web · 2c9a17e..5e0b7c2')
    await expect(page.getByTestId('diff-file')).toContainText('date-fns')
})

test("a ticket's runs list names each run's range, opening the run", async ({ page }) => {
    await page.goto('tickets/ABC-099')
    await settled(page)
    const ranges = page.getByTestId('ticket-runs').getByTestId('run-range')
    await expect(ranges).toHaveText(['web 9b2f4c6..e3a7d91', 'web 71c3e0a..9b2f4c6'])
    await ranges.last().click()
    await expect(page).toHaveURL(/\/workspace\/runs\/39$/u)
})
