import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the list is most severe first, and the most severe ticket opens beside it', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const rows = page.getByTestId('attention-list').getByRole('link')
    // Broken work, what waits on the operator, the rest by how long it has been open, then a chore's finding.
    await expect(rows).toHaveCount(5)
    const reasons = ['worker_failed', 'awaiting_reply', 'repo_missing', 'needs_reviewer', 'lodash-advisory']
    for (const [index, reason] of reasons.entries()) await expect(rows.nth(index)).toContainText(reason)

    await expect(rows.first()).toHaveAttribute('aria-current', 'page')
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'ABC-100' })).toBeVisible()
    await expect(detail.getByRole('form', { name: 'Reply' })).toBeVisible()
})

test('choosing an item shows its thread and keeps the choice in the URL', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const list = page.getByTestId('attention-list')
    await list.getByRole('link').filter({ hasText: 'awaiting_reply' }).click()

    await expect(page).toHaveURL(/\/attention\?item=/)
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'ABC-102' })).toBeVisible()
    await expect(detail.getByTestId('message-5')).toContainText('Should the export button be red or blue?')
    await expect(detail.getByText('Your answer to message 5')).toBeVisible()

    await page.reload()
    await expect(list.getByRole('link').filter({ hasText: 'awaiting_reply' })).toHaveAttribute('aria-current', 'page')
})

test("a chore's finding opens the chore's notes and a form for another", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'lodash-advisory' }).click()

    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'chore:deps' })).toBeVisible()
    await expect(detail.getByTestId('message-8')).toContainText("Leave out the docs site's lockfile")
    await expect(detail.getByTestId('message-8')).not.toContainText('waiting for the next run')
    await expect(detail.getByRole('form', { name: 'Note' })).toBeVisible()
    await expect(detail.getByRole('form', { name: 'Reply' })).toHaveCount(0)
})

test('an item about no ticket says so, with nothing to answer', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'repo_missing' }).click()

    const detail = page.getByTestId('attention-detail')
    await expect(detail).toContainText('api is in the workspace map but has no clone')
    await expect(detail).toContainText('Nothing to answer here')
    await expect(detail.getByRole('form', { name: 'Reply' })).toHaveCount(0)
})

test('the counters show the loop at a glance, and the nav counts the list on every page', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await expect(page.getByTestId('counter-running')).toContainText('2')
    await expect(page.getByTestId('counter-waiting')).toContainText('1')
    await expect(page.getByTestId('counter-waiting')).toContainText('oldest')
    await expect(page.getByTestId('counter-attention')).toContainText('5')
    await expect(page.getByTestId('counter-attention')).toContainText('1 failed · 1 waiting · 3 more')
    await expect(page.getByTestId('counter-spent-24h')).toContainText(/\$\d+\.\d\d/)
    await expect(page.getByTestId('counter-spent-30d')).toContainText(/\$\d+\.\d\d/)

    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: /Runs/ }).click()
    await expect(page.getByTestId('nav-attention-count')).toHaveText('5')
    await expect(page.getByTestId('counters')).toHaveCount(0)
})

test('the runs working now are listed under the attention list', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const workers = page.getByTestId('workers')
    await expect(workers.getByRole('listitem')).toHaveCount(2)
    await expect(workers.getByTestId('worker-41')).toContainText('ABC-101')
    await expect(workers.getByTestId('worker-41')).toContainText('implement')
    await expect(workers.getByTestId('worker-43')).toContainText('ABC-104')
})

test("a started ticket's item offers the ticket's own actions beside its thread", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'awaiting_reply' }).click()
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('button', { name: 'Stop', exact: true })).toBeVisible()
    await expect(detail.getByText('Private: workers read the ticket and write nothing to it.')).toBeVisible()
})
