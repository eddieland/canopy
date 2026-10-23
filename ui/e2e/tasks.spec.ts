import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// A task's page (ui/DESIGN.md, "A task"), over the mock journal's tasks: task 1 done with a report, a draft PR, and two
// tickets; task 3 stopped; task 4 waiting on the operator's answer.

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the list opens a task's page, whose story starts with your instruction and whose report is laid out", async ({
    page,
}) => {
    await page.goto('tasks')
    await settled(page)
    await page.getByTestId('task-1').getByRole('link', { name: 'task:1', exact: true }).click()
    await expect(page).toHaveURL(/\/tasks\/1$/u)
    await settled(page)
    const story = page.getByTestId('conversation').getByRole('listitem')
    await expect(story.first()).toHaveAttribute('data-testid', 'instruction')
    await expect(story.first()).toContainText("The checkout page's bundle grew past 900 kB")
    const report = page.getByTestId('task-report')
    await expect(report.getByRole('heading', { name: 'Checkout bundle' })).toBeVisible()
    await expect(report).toContainText('from task:1#1')
})

test('what a task left names its commit, its draft PR, and the tickets it filed, each opening its page', async ({
    page,
}) => {
    await page.goto('tasks/1')
    await settled(page)
    const left = page.getByTestId('task-left')
    await expect(left.getByTestId('task-heads')).toContainText('task:1#1')
    await expect(left.getByRole('link', { name: 'acme/web#97', exact: true })).toBeVisible()
    await expect(left.getByRole('link', { name: 'ABC-120', exact: true })).toHaveAttribute(
        'href',
        /\/tickets\/ABC-120$/u,
    )
    await expect(left).toContainText('All of it is throwaway until you give it a pass of its own.')
})

test("a task's open question is marked, and the reply form beside it answers it", async ({ page }) => {
    await page.goto('tasks/4')
    await settled(page)
    await expect(page.getByTestId('conversation').getByText('waiting on you')).toBeVisible()
    const question = page.getByRole('region', { name: 'A question waiting on you' })
    await expect(question.getByRole('textbox', { name: /^Reply to message \d+$/u })).toBeVisible()
    await expect(page.getByTestId('task-actions').getByRole('button', { name: 'Stop', exact: true })).toBeVisible()
})

test('a refused reply to a task names its guard, and keeps what was written', async ({ page }) => {
    // Answered by the route, so the root server's journal never changes.
    await page.route('**/api/tasks/4/replies', (route) =>
        route.fulfill({ status: 409, json: { detail: { guard: 'stopped', reason: 'task:4 is stopped' } } }),
    )
    await page.goto('tasks/4')
    await settled(page)
    const form = page.getByRole('form', { name: 'Reply' })
    await form.getByRole('textbox').fill('Rename it in api too.')
    await form.getByRole('button', { name: 'Reply' }).click()
    await expect(form.getByRole('alert')).toHaveText('refused (stopped): task:4 is stopped')
    await expect(form.getByRole('textbox')).toHaveValue('Rename it in api too.')
})

test("a task's attachments are listed, and a file uploads as its own bytes under a plain name", async ({ page }) => {
    // Answered by the route, so the root server's journal never changes.
    const sent: { url: string; body: string | null }[] = []
    await page.route('**/api/tasks/1/attachments/*', async (route) => {
        sent.push({ url: route.request().url(), body: route.request().postData() })
        await route.fulfill({
            json: { attachment: { name: 'my-notes.md', size: 5, channel: 'web', added_at: '2026-10-08T12:00:00Z' } },
        })
    })
    await page.goto('tasks/1')
    await settled(page)
    const section = page.getByRole('region', { name: 'Attachments' })
    await expect(section.getByRole('listitem')).toContainText('importer-design-v2.md')
    await section
        .getByLabel('File to attach')
        .setInputFiles({ name: 'my notes.md', mimeType: 'text/markdown', buffer: Buffer.from('# Hi\n') })
    await expect(section.getByRole('status')).toHaveText(
        'Attached my-notes.md (5 bytes) to task:1; its next run reads it.',
    )
    expect(sent).toEqual([
        { url: expect.stringMatching(/\/api\/tasks\/1\/attachments\/my-notes\.md$/u), body: '# Hi\n' },
    ])
})

test('a stopped task takes no reply', async ({ page }) => {
    await page.goto('tasks/3')
    await settled(page)
    await expect(page.getByTestId('conversation')).toBeVisible()
    await expect(page.getByRole('form', { name: 'Reply' })).toHaveCount(0)
})

test("a task's run opens its page: what it said, in full, over its session's transcript", async ({ page }) => {
    await page.goto('tasks/1')
    await settled(page)
    await page.getByTestId('task-run-1').getByRole('link', { name: 'task:1#1', exact: true }).click()
    await expect(page).toHaveURL(/\/tasks\/1\/runs\/1$/u)
    await settled(page)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
        "task:1#1 The checkout page's bundle grew past 900 kB after the last two releases, and the first paint on a " +
            'mid-range phone is',
    )
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Tasks' })).toHaveAttribute(
        'data-status',
        'active',
    )
    await expect(page.locator('main dl').first()).toContainText('ABC-120')

    const transcript = page.getByTestId('transcript')
    await expect(transcript).toContainText('session ses_task1')
    const measure = transcript.getByTestId('transcript-tool').filter({ hasText: 'Measure the checkout bundle again' })
    await measure.locator('summary').click()
    await expect(measure).toContainText('612.48 kB')

    // Its task is its trail's step, linked there alone.
    await page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'task:1' }).click()
    await expect(page).toHaveURL(/\/tasks\/1$/u)

    await page.goto('tasks/1/runs/2')
    await expect(page.getByText('task:1 has no run 2')).toBeVisible()
})

test('a task canopy has no record of says so', async ({ page }) => {
    await page.goto('tasks/999')
    await settled(page)
    await expect(page.locator('main')).toContainText('canopy has no task:999')
})
