import { expect, test } from '@playwright/test'

// Served under /canopy, with mock events every 250 ms (playwright.config.ts).

test('the app works under a path prefix', async ({ page }) => {
    await page.goto('')
    await expect(page).toHaveURL(/\/canopy\/sessions$/)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Worktrees' }).click()
    await expect(page).toHaveURL(/\/canopy\/worktrees$/)
    await page.reload()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Worktrees')
})

test('stream events update the cache without refetching', async ({ page }) => {
    const fetches: string[] = []
    page.on('request', (request) => {
        if (request.resourceType() === 'fetch') fetches.push(new URL(request.url()).pathname)
    })
    await page.goto('sessions')
    await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'open')

    // The mock stream cycles run:41 through running, blocked, idle, done: the counters must move.
    const running = page.getByTestId('live-readouts').locator('.readout').first()
    const seen = new Set<string>()
    await expect
        .poll(
            async () => {
                seen.add((await running.textContent()) ?? '')
                return seen.size
            },
            { timeout: 5_000 },
        )
        .toBeGreaterThan(1)

    // One fetch per list on load; everything after came over the stream.
    expect(fetches.filter((path) => path.endsWith('/api/sessions'))).toHaveLength(1)
})
