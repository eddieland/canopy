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
    await expect(rows).toHaveCount(6)
    const reasons = [
        'worker failed',
        'drafts waiting',
        'awaiting reply',
        'repo missing',
        'needs reviewer',
        'lodash-advisory',
    ]
    for (const [index, reason] of reasons.entries()) {
        await expect(rows.nth(index)).toContainText(reason)
    }
    // A reason reads as words, and keeps the CLI's spelling on hover.
    await expect(rows.first().getByTitle('worker_failed')).toHaveText('worker failed')
    // A finding's id is the agent's text: its chip says `finding`, and the id sits beside its chore.
    await expect(rows.nth(5).getByText('finding', { exact: true })).toBeVisible()
    // An item about a ticket names it by its title too; a repository's has none to name.
    await expect(rows.first()).toContainText('Fix the flaky checkout test')
    await expect(rows.nth(3).getByText('untitled')).toHaveCount(0)

    await expect(rows.first()).toHaveAttribute('aria-current', 'page')
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'ABC-100', exact: true })).toBeVisible()
    await expect(detail.getByText('Fix the flaky checkout test')).toBeVisible()
})

test("a broken run's item leads with the run, and grants another try without leaving the page", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const detail = page.getByTestId('attention-detail')
    // The run that failed, as the ticket's Runs list shows it: what it said, and its page a click away.
    const run = detail.getByTestId('attention-run')
    await expect(run).toContainText('failed')
    await expect(run.getByRole('link', { name: 'run:40' })).toHaveAttribute('href', /\/runs\/40$/u)
    // The detail's own `run:40` links there too.
    await expect(detail.getByRole('link', { name: 'run:40' })).toHaveCount(2)
    await expect(detail.getByRole('button', { name: 'Allow one more' })).toBeVisible()
    // The run and the grant come before the ticket's own verbs, which sit quietly under the thread.
    const grant = await detail.getByTestId('grant-limits').boundingBox()
    const actions = await detail.getByTestId('attention-actions').boundingBox()
    const first = await run.boundingBox()
    expect(first !== null && grant !== null && actions !== null && first.y < grant.y && grant.y < actions.y).toBe(true)
    // A public ticket with nothing waiting has no open box, only a way to write its next worker a note.
    await expect(detail.getByRole('form', { name: 'Reply' })).toHaveCount(0)
    await detail.getByRole('button', { name: 'Show a note for its next worker' }).click()
    const field = detail.getByRole('form', { name: 'Reply' }).getByRole('textbox')
    await expect(field).toHaveAttribute('placeholder', /next worker reads it/u)
    await expect(field).not.toHaveAttribute('placeholder', /untrusted/u)
})

test("replies a run drafted lead to the PR's page, where each waits on its thread", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'drafts waiting' }).click()
    const detail = page.getByTestId('attention-detail')
    await detail.getByTestId('attention-drafts').getByRole('link', { name: 'Read the drafts on acme/web#88' }).click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
    // Each thread at its line, answered or not, and the review's body above the diff.
    await expect(page.getByTestId('review-thread')).toHaveCount(3)
    await expect(page.getByTestId('pr-drafts').getByTestId('draft')).toHaveCount(1)
    await expect(page.getByTestId('draft').and(page.locator('[data-status=waiting]'))).toHaveCount(3)
    await expect(page.getByRole('button', { name: 'Send 3 waiting' })).toBeVisible()
})

test("a PR waiting on a reviewer leads with its link out, the detail's one stop for the PR", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'needs reviewer' }).click()
    const detail = page.getByTestId('attention-detail')
    const action = detail.getByTestId('attention-pull-request').getByRole('link')
    await expect(action).toHaveText('acme/web#88 on GitHub')
    await expect(action).toHaveAttribute('href', 'https://github.com/acme/web/pull/88')
    // The head names the PR as text, so above the conversation the PR is one tab stop.
    const said = detail.getByText('acme/web#88 waits on a reviewer')
    await expect(said).toBeVisible()
    await expect(said.getByRole('link')).toHaveCount(0)
    const head = await said.boundingBox()
    const link = await action.boundingBox()
    const actions = await detail.getByTestId('attention-actions').boundingBox()
    expect(head !== null && link !== null && actions !== null && head.y < link.y && link.y < actions.y).toBe(true)
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
    // The head names the question; the conversation holds it, once, and the form is how to answer it.
    await expect(detail.getByTestId('awaiting-line')).toContainText('Waits on your answer to message 5, asked')
    await expect(detail.getByText('Should the export button be red or blue?')).toHaveCount(1)
    await expect(detail).not.toContainText('canopy reply')

    await page.reload()
    await expect(list.getByRole('link').filter({ hasText: 'awaiting reply' })).toHaveAttribute('aria-current', 'page')
})

test("a chore's finding opens the chore's notes and a form for another", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'lodash-advisory' }).click()

    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('link', { name: 'chore:deps' })).toBeVisible()
    // The finding as its chore's page has it: its title, then what it says of itself, then its link on its own line.
    const text = detail.getByTestId('finding-text')
    await expect(text).toContainText('lodash 4.17.20 has a prototype pollution advisory')
    await expect(text).toContainText('through an old date picker; 4.17.21 fixes it.')
    await expect(text.getByRole('link')).toHaveAttribute('href', 'https://github.com/advisories/GHSA-35jh-r3h4-6jhm')
    await expect(detail.getByTestId('message-8')).toContainText("Leave out the docs site's lockfile")
    await expect(detail.getByTestId('message-8')).not.toContainText('waiting for the next run')
    await expect(detail.getByRole('form', { name: 'Note' })).toBeVisible()
    await expect(detail.getByRole('form', { name: 'Reply' })).toHaveCount(0)
})

test('an item about no ticket offers the command that fixes it, with nothing to answer', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'repo missing' }).click()

    const detail = page.getByTestId('attention-detail')
    await expect(detail).toContainText('api is in the workspace map but has no clone')
    const command = detail.getByTestId('attention-command')
    await expect(command).toContainText('canopy workspace sync')
    await expect(command.getByRole('button', { name: 'Copy command' })).toBeVisible()
    await expect(command).toContainText('Nothing to answer here')
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
    await expect(page.getByTestId('counter-attention')).toContainText('6')
    await expect(page.getByTestId('counter-attention')).toContainText('1 broken, 2 waiting on you, 3 other')

    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: /Runs/u }).click()
    await expect(page.getByTestId('nav-attention-failed')).toHaveText('1')
    await expect(page.getByTestId('nav-attention-waiting')).toHaveText('2')
    await expect(page.getByTestId('nav-attention-other')).toHaveText('3')
    // Told apart by color, so said in words too: on hover, and in the link's name.
    await expect(page.getByTestId('nav-attention-count')).toHaveAttribute(
        'title',
        '1 broken, 2 waiting on you, 3 other',
    )
    await expect(
        page
            .getByRole('navigation', { name: 'Main' })
            .getByRole('link', { name: /1 broken, 2 waiting on you, 3 other/u }),
    ).toHaveCount(1)
    await expect(page.getByTestId('counters')).toHaveCount(0)
})

test("a question's item is answered in its reply, with the ticket's own actions a quiet row under it", async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'awaiting reply' }).click()
    const detail = page.getByTestId('attention-detail')
    await expect(detail.getByRole('button', { name: 'Stop', exact: true })).toBeVisible()
    // Whether the ticket is private is said once, as its page's chip says it, over the conversation it decides.
    await expect(detail.getByText('private', { exact: true })).toBeVisible()
    // The reply is what the item asks for, so the ticket's verbs come after it.
    const actions = await detail.getByTestId('attention-actions').boundingBox()
    const reply = await detail.getByRole('textbox', { name: /^Reply/u }).boundingBox()
    expect(actions !== null && reply !== null && reply.y < actions.y).toBe(true)
    // The runs working now are the rail's, on every page; the attention page keeps no list of its own.
    await expect(page.getByTestId('workers')).toHaveCount(0)
})
