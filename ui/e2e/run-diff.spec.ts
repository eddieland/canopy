import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// What a run changed (DESIGN §45), on its page and its ticket's and its PR's runs lists, as the mock records it: run
// 39 kept its diff, run 40 left its fix unpushed, run 37 kept none, task 1's run kept its own change, and ABC-130's
// resume, under `post`, kept the diff PR 61's threads sit on.

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("a run's page sums up what it changed, over its transcript, and shows the diff when asked", async ({ page }) => {
    await page.goto('workspace/runs/39')
    await settled(page)
    const diff = page.getByRole('region', { name: /^Diff: web · 71c3e0a\.\.9b2f4c6$/u })
    await expect(diff.getByTestId('run-change-size')).toHaveText('2 files · +21 −3')
    await expect(diff.getByTestId('run-change-files').getByRole('listitem')).toHaveCount(2)
    await expect(diff.getByTestId('diff-file')).toHaveCount(0)
    // The branch against its base is the PR's page's.
    await expect(diff.getByRole('link', { name: 'branch vs base' })).toHaveAttribute('href', /pull-requests\/pr\?url=/u)
    // Over the transcript, a few lines tall rather than every line.
    const panels = await page.locator('main h2').allTextContents()
    expect(panels.indexOf('Diff')).toBeLessThan(panels.indexOf('Transcript'))

    // Its commits, oldest first, the second pushed by canopy after the worker left it, each opening on GitHub.
    const commits = diff.getByTestId('run-commit')
    await expect(commits).toHaveText([
        "5e1c0d2ABC-099: debounce the search box's fetch",
        '9b2f4c6ABC-099: test that search waits 250 mspushed by canopy',
    ])
    await expect(commits.first().getByRole('link', { name: '5e1c0d2' })).toHaveAttribute(
        'href',
        'https://github.com/acme/web/pull/88/commits/5e1c0d2a77777777777777777777777777777777',
    )

    await diff.getByRole('button', { name: 'Show diff' }).click()
    await expect(diff.getByTestId('diff-file')).toHaveCount(2)
    await expect(diff.getByTestId('diff-file').first()).toContainText('controller.abort()')
})

test("a PR's runs list reads as its branch's history, each run's commits under its range", async ({ page }) => {
    await page.goto(`pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/88')}`)
    await settled(page)
    const commits = page.getByTestId('pull-request-runs').getByTestId('run-commit')
    await expect(commits).toContainText([
        'ABC-099: cancel the timer on unmount',
        "ABC-099: debounce the search box's fetch",
        'ABC-099: test that search waits 250 ms',
    ])
})

test("an unpushed run's change is marked not on origin, and one not kept says why", async ({ page }) => {
    await page.goto('workspace/runs/40')
    await settled(page)
    await expect(page.getByTestId('run-change-range')).toHaveText('web · a40d2f9..d8e61b3')
    await expect(page.getByTestId('run-change').getByText('not on origin')).toBeVisible()
    await page.getByRole('button', { name: 'Show diff' }).click()
    await expect(page.getByTestId('diff-file')).toContainText('frameLocator')

    await page.goto('workspace/runs/37')
    await settled(page)
    await expect(page.getByTestId('run-change')).toContainText(
        'no diff kept: the run left no branch on origin and no commit of its own in its slot',
    )
    await expect(page.getByRole('button', { name: 'Show diff' })).toHaveCount(0)
})

test("a task run's page shows what it changed as a worker run's does", async ({ page }) => {
    await page.goto('tasks/1/runs/1')
    await settled(page)
    await expect(page.getByTestId('run-change-range')).toHaveText('web · 2c9a17e..5e0b7c2')
    await page.getByRole('button', { name: 'Show diff' }).click()
    await expect(page.getByTestId('diff-file')).toContainText('date-fns')
})

test("a ticket's runs list names each run's range and size, opening the run at its diff", async ({ page }) => {
    await page.goto('tickets/ABC-099')
    await settled(page)
    const ranges = page.getByTestId('ticket-runs').getByTestId('run-range')
    await expect(ranges).toHaveText(['web 9b2f4c6..e3a7d91 +26 −1', 'web 71c3e0a..9b2f4c6 +21 −3'])
    await ranges.last().click()
    await expect(page).toHaveURL(/\/workspace\/runs\/39#diff-web$/u)
    await expect(page.getByRole('region', { name: /^Diff: web/u }).getByTestId('diff-file')).toHaveCount(2)
})

test("a PR's runs list names each run's range, and its threads sit on the kept diff, no draft", async ({ page }) => {
    await page.goto(`pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/mobile/pull/61')}`)
    await settled(page)
    const ranges = page.getByTestId('pull-request-runs').getByTestId('run-range')
    await expect(ranges).toHaveText(['mobile 6161616..61a61a6 +23 −8'])
    const replies = page.getByTestId('review-replies')
    await expect(replies.getByTestId('diff-run')).toHaveText('Its threads sit on the branch as run:51 left it.')
    await expect(replies.getByTestId('draft-list')).toHaveCount(0)
    const file = page.getByTestId('diff-file').filter({ hasText: 'app/notify/push.ts' })
    await expect(file.getByTestId('review-thread')).toContainText('Back off between tries')
    await ranges.click()
    await expect(page).toHaveURL(/\/workspace\/runs\/51#diff-mobile$/u)
})
