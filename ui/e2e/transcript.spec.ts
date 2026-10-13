import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("a run's id opens its page, and its transcript opens each tool call to its input and output, as text", async ({
    page,
}) => {
    await page.goto('runs')
    await settled(page)
    await page.getByTestId('run-39').getByRole('link', { name: 'run:39' }).click()
    await expect(page).toHaveURL(/\/runs\/39$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('run:39')
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Runs' })).toHaveAttribute(
        'data-status',
        'active',
    )

    const transcript = page.getByTestId('transcript')
    await expect(transcript).toContainText('session ses_mock39')
    await expect(transcript).toContainText('7 tool calls, 1 failed')
    // Only the failure count takes the failure color, not the comma before it.
    await expect(transcript.locator('.text-status-failed', { hasText: 'failed' })).toHaveText('1 failed')
    await expect(transcript).toContainText('3 model calls')
    const tools = transcript.getByTestId('transcript-tool')
    await expect(tools).toHaveCount(7)

    // Closed until clicked; a file's markup is characters on the page, never elements.
    const read = tools.filter({ hasText: 'src/search/SearchBox.tsx' }).first()
    const output = read.getByText('return <input value={query}', { exact: false })
    await expect(output).toBeHidden()
    await read.locator('summary').click()
    await expect(output).toBeVisible()
    await expect(transcript.locator('input')).toHaveCount(0)
    // A failed call shows its error where a call's output goes.
    const missing = tools.filter({ hasText: 'useSearch.ts' }).first()
    await missing.locator('summary').click()
    await expect(missing).toContainText('File not found:')

    await transcript.getByRole('button', { name: 'Open all' }).click()
    await expect(transcript.locator('details[open]')).toHaveCount(7)
    await transcript.getByRole('button', { name: 'Close all' }).click()
    await expect(transcript.locator('details[open]')).toHaveCount(0)

    await page.getByRole('link', { name: 'ABC-099' }).first().click()
    await expect(page).toHaveURL(/\/tickets\/ABC-099$/)
})

test("a failed run's transcript ends in the runtime's error, and a running one's waits for it to end", async ({
    page,
}) => {
    await page.goto('runs/40')
    await settled(page)
    await expect(page.getByTestId('transcript-entries').locator('li').last()).toContainText(
        'APIErrorRate limited: retry after 60s',
    )

    await page.goto('runs/41')
    await settled(page)
    await expect(page.getByTestId('transcript')).toContainText('the session’s events reach the log when it ends')
})

test("a tick's page shows its overseer's session under its decisions", async ({ page }) => {
    await page.goto('ticks/2')
    await settled(page)
    const transcript = page.getByTestId('transcript')
    await expect(transcript).toContainText('session ses_tick2')
    await expect(transcript.getByTestId('transcript-tool')).toHaveCount(2)
    await expect(transcript).toContainText('Record the decision on ABC-101')

    // With --thinking, what the model thought, under its label.
    await expect(transcript.getByTestId('transcript-entries').locator('li').first()).toContainText(
        'thinkingNothing is waiting on me except ABC-101',
    )
    // A model call opens to its tokens by kind; Open all opens only the tool calls.
    const call = transcript.getByTestId('transcript-step')
    await expect(call).toHaveCount(1)
    const split = call.locator('dl')
    await expect(split).toBeHidden()
    await call.locator('summary').click()
    await expect(split).toHaveText('input2.3kcache read6.5kcache write512output930reasoning310')
    await transcript.getByRole('button', { name: 'Open all' }).click()
    await expect(transcript.locator('details[open]')).toHaveCount(2)
    await expect(split).toBeHidden()
})

test('a run that does not exist, or a path that names none, says so', async ({ page }) => {
    await page.goto('runs/99')
    await expect(page.getByText('no run 99')).toBeVisible()
    await page.goto('runs/two')
    await expect(page.getByText("not a run: a run's id is a positive number")).toBeVisible()
})
