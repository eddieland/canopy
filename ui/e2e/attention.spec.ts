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
    const reasons = ['worker failed', 'awaiting reply', 'repo missing', 'needs reviewer', 'lodash-advisory']
    for (const [index, reason] of reasons.entries()) {
        await expect(rows.nth(index)).toContainText(reason)
    }
    // A reason reads as words, and keeps the CLI's spelling on hover.
    await expect(rows.first().getByTitle('worker_failed')).toHaveText('worker failed')
    // A finding's id is the agent's text: its chip says `finding`, and the id sits beside its chore.
    await expect(rows.nth(4).getByText('finding', { exact: true })).toBeVisible()

    await expect(rows.first()).toHaveAttribute('aria-current', 'page')
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'ABC-100', exact: true })).toBeVisible()
    await expect(detail.getByRole('form', { name: 'Reply' })).toBeVisible()
})

test('choosing an item shows its thread and keeps the choice in the URL', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const list = page.getByTestId('attention-list')
    await list.getByRole('link').filter({ hasText: 'awaiting reply' }).click()

    await expect(page).toHaveURL(/\/attention\?item=/u)
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'ABC-102', exact: true })).toBeVisible()
    await expect(detail.getByTestId('message-5')).toContainText('Should the export button be red or blue?')
    await expect(detail.getByText('Reply to message 5')).toBeVisible()

    await page.reload()
    await expect(list.getByRole('link').filter({ hasText: 'awaiting reply' })).toHaveAttribute('aria-current', 'page')
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
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'repo missing' }).click()

    const detail = page.getByTestId('attention-detail')
    await expect(detail).toContainText('api is in the workspace map but has no clone')
    await expect(detail).toContainText('nothing to answer here')
    await expect(detail.getByRole('form', { name: 'Reply' })).toHaveCount(0)
})

test('the counters show the loop at a glance, and the nav counts the list by severity on every page', async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    await expect(page.getByTestId('counter-running')).toContainText('2')
    await expect(page.getByTestId('counter-waiting')).toContainText('1')
    await expect(page.getByTestId('counter-waiting')).toContainText('oldest')
    await expect(page.getByTestId('counter-attention')).toContainText('5')
    await expect(page.getByTestId('counter-attention')).toContainText('1 failed · 1 waiting · 3 more')

    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: /Runs/u }).click()
    await expect(page.getByTestId('nav-attention-failed')).toHaveText('1')
    await expect(page.getByTestId('nav-attention-waiting')).toHaveText('1')
    await expect(page.getByTestId('nav-attention-other')).toHaveText('3')
    // Told apart by color, so said in words too: on hover, and in the link's name.
    await expect(page.getByTestId('nav-attention-count')).toHaveAttribute(
        'title',
        '1 broken, 1 waiting on you, 3 other',
    )
    await expect(
        page
            .getByRole('navigation', { name: 'Main' })
            .getByRole('link', { name: /1 broken, 1 waiting on you, 3 other/u }),
    ).toHaveCount(1)
    await expect(page.getByTestId('counters')).toHaveCount(0)
})

test("a started ticket's item leads with the ticket's own actions, then its conversation and the reply", async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'awaiting reply' }).click()
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('button', { name: 'Stop', exact: true })).toBeVisible()
    await expect(detail.getByText('Private: workers read the ticket and write nothing to it.')).toBeVisible()
    // The same order as the ticket's own page: its actions foot what it is, above the thread you answer in.
    const actions = await detail.getByTestId('attention-actions').boundingBox()
    const reply = await detail.getByRole('textbox', { name: /^Reply/u }).boundingBox()
    expect(actions !== null && reply !== null && actions.y < reply.y).toBe(true)
    // The runs working now are the rail's, on every page; the attention page keeps no list of its own.
    await expect(page.getByTestId('workers')).toHaveCount(0)
})
