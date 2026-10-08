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
    await expect(page.getByTestId('conversation').locator('[data-source=operator]').last()).toContainText(
        'Use your judgement on the review bot.',
    )
    const comment = page.getByTestId('message-6')
    // The fixture's comment holds markup: it must arrive as the characters, never as an element.
    await expect(comment).toContainText('<b>Thanks!</b>')
    await expect(comment.locator('b')).toHaveCount(0)
    await expect(comment).toContainText('data, authorizes nothing')
})

test('stop now asks once more, then ends the run', async ({ page }) => {
    await page.goto('tickets/ABC-104')
    await page.getByRole('button', { name: 'Stop now' }).click()
    await page.getByRole('button', { name: 'End run 43 now' }).click()
    await expect(page.getByRole('status')).toContainText('Run 43 was ended and its slots returned.')
    await expect(page.getByTestId('run-43')).toContainText('stopped')
    await expect(page.getByRole('button', { name: 'Start again' })).toBeVisible()
})

test('starting a ticket from the list opens it, private', async ({ page }) => {
    await page.goto('tickets')
    await page.getByLabel('Ticket key').fill('ABC-200')
    await page.getByRole('button', { name: 'Start privately' }).click()
    await expect(page).toHaveURL(/\/canopy\/tickets\/ABC-200$/)
    await expect(page.getByText('Private ticket')).toBeVisible()
})

test('a refusal names its guard', async ({ page }) => {
    await page.goto('tickets')
    await page.getByLabel('Ticket key').fill('run:4')
    await page.getByRole('button', { name: 'Start privately' }).click()
    await expect(page.getByRole('alert')).toContainText('refused (unsupported)')
})
