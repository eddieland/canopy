import { expect, test } from '@playwright/test'

// Served under /canopy, signing nobody in, with the mock journal changing every 250 ms (playwright.config.ts). The
// writes happen here, not on the root server, whose screenshots need its journal as seeded.

test('the app works under a path prefix', async ({ page }) => {
    await page.goto('')
    await expect(page).toHaveURL(/\/canopy\/attention$/)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Runs' }).click()
    await expect(page).toHaveURL(/\/canopy\/runs$/)
    await page.reload()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
})

test('stream events update the cache without refetching', async ({ page }) => {
    const fetches: string[] = []
    page.on('request', (request) => {
        if (request.resourceType() === 'fetch') fetches.push(new URL(request.url()).pathname)
    })
    await page.goto('runs')
    await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'open')

    // The mock journal adds a cent to run 41's cost every 250 ms: the page must follow it.
    const cost = page.getByTestId('run-41').getByTestId('run-cost')
    const seen = new Set<string>()
    await expect
        .poll(
            async () => {
                seen.add((await cost.textContent()) ?? '')
                return seen.size
            },
            { timeout: 5_000 },
        )
        .toBeGreaterThan(2)

    // One fetch of the runs on load; everything after came over the stream.
    expect(fetches.filter((path) => path.endsWith('/api/runs'))).toHaveLength(1)
})

test('a reply answers the waiting question, and a retry records nothing new', async ({ page }) => {
    await page.goto('tickets/ABC-102')
    await expect(page.getByText('waits on your answer')).toBeVisible()
    const form = page.getByRole('form', { name: 'Reply' })
    await form.getByRole('textbox').fill('Blue, to match the toolbar.')
    await form.getByRole('button', { name: 'Reply' }).click()
    await expect(form.getByRole('status')).toContainText('answering message 5')
    const conversation = page.getByTestId('conversation')
    const mine = conversation.locator('[data-source=operator]').last()
    await expect(mine).toContainText('Blue, to match the toolbar.')
    await expect(mine).toContainText('via web')
    await expect(page.getByText('waits on your answer')).toHaveCount(0)

    // No tick has read it yet: the reply says so, and the inbox keeps the question, marked answered, until one does.
    await expect(mine).toContainText('waiting for the next tick')
    await page.goto('attention')
    const item = page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'awaiting reply' })
    await expect(item).toContainText('answered')
    await item.click()
    await expect(page.getByTestId('answered-note')).toContainText('leaves at the next tick')
})

test('a public ticket takes a reply that stays in canopy, and its tracker comment is shown as text', async ({
    page,
}) => {
    await page.goto('tickets/ABC-101')
    const form = page.getByRole('form', { name: 'Reply' })
    await expect(form.getByRole('textbox')).toHaveAttribute('placeholder', /never on the ticket/)
    await form.getByRole('textbox').fill('Use your judgement on the review bot.')
    await form.getByRole('button', { name: 'Reply' }).click()
    await expect(form.getByRole('status')).toContainText('Recorded message')
    // Other tests reply to the same ticket at the same time, so find this reply by its text, not as the last one.
    await expect(
        page
            .getByTestId('conversation')
            .locator('[data-source=operator]')
            .filter({ hasText: 'Use your judgement on the review bot.' }),
    ).toHaveCount(1)
    const comment = page.getByTestId('message-6')
    // The fixture's comment holds markup: it must arrive as the characters, never as an element.
    await expect(comment).toContainText('<b>Thanks!</b>')
    await expect(comment.locator('b')).toHaveCount(0)
    await expect(comment).toContainText('data, authorizes nothing')
})

test('Enter sends a reply and Shift+Enter starts a new line', async ({ page }) => {
    await page.goto('tickets/ABC-101')
    const form = page.getByRole('form', { name: 'Reply' })
    await expect(form.getByRole('button', { name: 'Reply' })).toHaveAttribute('aria-keyshortcuts', 'Enter')
    const box = form.getByRole('textbox')
    await box.fill('First line.')
    await box.press('Shift+Enter')
    await box.pressSequentially('Second line.')
    await expect(box).toHaveValue('First line.\nSecond line.')
    await box.press('Enter')
    await expect(form.getByRole('status')).toContainText('Recorded message')
    await expect(box).toHaveValue('')
    // toContainText collapses whitespace, so read the text itself: the line break must arrive as one.
    const mine = page.getByTestId('conversation').locator('[data-source=operator]').filter({ hasText: 'Second line.' })
    await expect.poll(() => mine.textContent()).toContain('First line.\nSecond line.')
})

test("a chore's finding is answered from the attention list with a note its next run reads", async ({ page }) => {
    await page.goto('attention')
    await page.getByTestId('attention-list').getByRole('link').filter({ hasText: 'lodash-advisory' }).click()
    const detail = page.getByTestId('attention-detail')
    const form = detail.getByRole('form', { name: 'Note' })
    await form.getByRole('textbox').fill('Leave out lodash-advisory until 2026-10-15: the upgrade is merging.')
    await form.getByRole('button', { name: 'Add note' }).click()
    await expect(form.getByRole('status')).toContainText(/Recorded message \d+ on chore:deps\. Its next run reads it\./)
    const mine = detail.getByTestId('conversation').locator('[data-source=operator]').last()
    await expect(mine).toContainText('until 2026-10-15')
    await expect(mine).toContainText('via web')
    await expect(mine).toContainText('waiting for the next run')

    await detail.getByRole('link', { name: 'chore:deps' }).click()
    await expect(page.getByTestId('chore-notes').locator('[data-source=operator]').last()).toContainText(
        'until 2026-10-15',
    )
})

test('the settings page asks the loop to read its config again and says what it found', async ({ page }) => {
    await page.goto('settings')
    await page.getByTestId('config-reload').click()
    // The mock runs no loop, so its config never changes.
    await expect(page.getByRole('status').filter({ hasText: 'Nothing changed' })).toContainText(
        'The loop runs on it from now on.',
    )
})

test('under Ctrl+Enter, Enter starts a new line and Ctrl+Enter sends', async ({ page }) => {
    await page.goto('settings')
    await page.getByTestId('send-key-mod-enter').click()
    await expect(page.getByTestId('send-key-mod-enter')).toHaveAttribute('aria-checked', 'true')
    // Pressing the key that is on keeps it on: one is always picked.
    await page.getByTestId('send-key-mod-enter').click()
    await expect(page.getByTestId('send-key-mod-enter')).toHaveAttribute('aria-checked', 'true')
    await page.goto('tickets/ABC-101')
    const form = page.getByRole('form', { name: 'Reply' })
    // Chromium on Linux: the button names Ctrl, not ⌘.
    await expect(form.getByRole('button', { name: 'Reply' })).toHaveAttribute('aria-keyshortcuts', 'Control+Enter')
    const box = form.getByRole('textbox')
    await box.fill('One.')
    await box.press('Enter')
    await box.pressSequentially('Two.')
    await expect(box).toHaveValue('One.\nTwo.')
    await box.press('ControlOrMeta+Enter')
    await expect(form.getByRole('status')).toContainText('Recorded message')
    await expect(box).toHaveValue('')
})

test('stop now asks once more, then ends the run', async ({ page }) => {
    await page.goto('tickets/ABC-104')
    await page.getByRole('button', { name: 'Stop now' }).click()
    await page.getByRole('button', { name: 'End run 43 now' }).click()
    await expect(page.getByRole('status')).toContainText('Run 43 was ended and its slots returned.')
    await expect(page.getByTestId('run-43')).toContainText('stopped')
    await expect(page.getByRole('button', { name: 'Start again' })).toBeVisible()
})

test('forget asks for the key typed out, then forgets the branch and PR', async ({ page }) => {
    await page.goto('tickets/ABC-103')
    await page.getByRole('button', { name: 'Forget' }).click()
    const challenge = page.getByRole('form', { name: 'Forget' })
    const forget = challenge.getByRole('button', { name: 'Forget ABC-103' })
    await expect(forget).toBeDisabled()
    await challenge.getByLabel('Type ABC-103 to confirm').fill('ABC-10')
    await expect(forget).toBeDisabled()
    await challenge.getByLabel('Type ABC-103 to confirm').fill('ABC-103')
    await forget.click()
    await expect(page.getByRole('status')).toContainText(
        'ABC-103 is forgotten: its next implement starts over on a new branch. canopy no longer tracks branch ' +
            'agent/ABC-103-billing-v2, https://github.com/acme/web/pull/91.',
    )
    await expect(challenge).toHaveCount(0)
    await expect(page.getByText('none yet')).toBeVisible()
})

test('starting a ticket from the list opens it, private', async ({ page }) => {
    await page.goto('tickets')
    await page.getByLabel('Ticket key').fill('ABC-200')
    await page.getByRole('button', { name: 'Start privately' }).click()
    await expect(page).toHaveURL(/\/canopy\/tickets\/ABC-200$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-200')
    await expect(page.locator('header').getByText('private', { exact: true })).toBeVisible()
})

test('a refusal names its guard', async ({ page }) => {
    await page.goto('tickets')
    await page.getByLabel('Ticket key').fill('run:4')
    await page.getByRole('button', { name: 'Start privately' }).click()
    await expect(page.getByRole('alert')).toContainText('refused (unsupported)')
})

test('the header pauses the loop and resumes it, as canopy pause and resume do', async ({ page }) => {
    await page.goto('attention')
    const control = page.getByTestId('loop-pause')
    await expect(control).toHaveAttribute('data-paused', 'false')
    await control.getByRole('button', { name: 'Pause' }).click()
    await expect(control).toHaveAttribute('data-paused', 'true')
    await expect(control).toContainText('paused · 0s')
    await expect(control.getByText('paused')).toHaveAttribute('title', /from the web UI$/)

    // The pause is the journal's: another page reads it back, as the loop does.
    await page.reload()
    await expect(control).toHaveAttribute('data-paused', 'true')
    await control.getByRole('button', { name: 'Resume' }).click()
    await expect(control).toHaveAttribute('data-paused', 'false')
    await expect(control).not.toContainText('paused')
})
