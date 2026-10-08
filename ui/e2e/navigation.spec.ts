import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the root redirects to the attention list', async ({ page }) => {
    await page.goto('')
    await expect(page).toHaveURL(/\/attention$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Attention')
})

test('the nav moves between pages without reloading the shell', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.evaluate(() => {
        document.querySelector('[data-testid=app-header]')?.setAttribute('data-marker', 'kept')
    })
    const nav = page.getByRole('navigation', { name: 'Main' })

    await nav.getByRole('link', { name: 'Runs' }).click()
    await expect(page).toHaveURL(/\/runs$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await expect(nav.getByRole('link', { name: 'Runs' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Worktrees' }).click()
    await expect(page).toHaveURL(/\/worktrees$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Worktrees')

    await nav.getByRole('link', { name: 'Tickets' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tickets')
    await page.getByTestId('tickets').getByRole('link', { name: 'ABC-102' }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-102$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-102')
    await expect(nav.getByRole('link', { name: 'Tickets' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
    await expect(page.getByTestId('app-header')).toHaveAttribute('data-marker', 'kept')
})

test('the side rail runs the full height of the page and its nav stays in view when scrolled', async ({ page }) => {
    await page.goto('tickets/ABC-102')
    await settled(page)
    const rail = page.locator('aside')
    const height = await page.evaluate(() => document.documentElement.scrollHeight)
    expect(height).toBeGreaterThan(page.viewportSize()?.height ?? 0)
    // From under the header to the page's foot, not just one viewport.
    expect(await rail.evaluate((el) => el.getBoundingClientRect().bottom + window.scrollY)).toBe(height)

    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    await expect(
        page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Attention' }),
    ).toBeInViewport()
})

test('search params are typed: a known state filters, an unknown one is dropped', async ({ page }) => {
    await page.goto('runs?state=blocked')
    const filters = page.getByRole('navigation', { name: 'Filter by state' })
    await expect(filters.getByRole('link', { name: 'blocked' })).toHaveAttribute('data-selected', 'true')
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'false')
    await expect(page.getByTestId('runs').locator('li')).toHaveCount(1)

    // The router leaves the URL as typed; what matters is the page never sees the value.
    await page.goto('runs?state=bogus')
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'true')
    await expect(page.getByTestId('runs').locator('li')).not.toHaveCount(1)
})

test('an unknown route renders the not-found page inside the shell', async ({ page }) => {
    await page.goto('nowhere')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Nothing here')
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
})

test('a ticket the journal does not know offers to start it', async ({ page }) => {
    await page.goto('tickets/ZZZ-9')
    await expect(page.getByText('canopy has no record of it')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start privately' })).toBeVisible()
})

test('the worktrees page shows each pool of the workspace and what holds each slot', async ({ page }) => {
    await page.goto('worktrees')
    await settled(page)
    await expect(page.getByTestId('pool-api')).toContainText('no clone; run `canopy workspace sync`')

    const web = page.getByTestId('pool-web')
    await expect(web.getByTestId('worktrees').locator('li')).toHaveCount(5)
    await expect(web.getByTestId('pool-size')).toHaveText('5 of size 4')
    await expect(web.getByTestId('pool-over')).toContainText('1 slot past the declared size')
    const working = web.getByTestId('worktree-1')
    await expect(working).toHaveAttribute('data-state', 'working')
    await expect(working).toContainText('agent/ABC-101-login')
    await expect(working).toContainText('.treehouse/web-3f9c2a1b/1/web')
    await expect(working).toContainText('opencode 48211')
    await expect(web.getByTestId('worktree-3')).toHaveAttribute('data-state', 'held')
    await expect(web.getByTestId('worktree-4')).toContainText('detached')
    await expect(web.getByTestId('worktree-5')).toHaveAttribute('data-state', 'dirty')

    // Run 43 holds a slot in two pools; each names it.
    const mobile = page.getByTestId('pool-mobile')
    await expect(mobile.getByTestId('pool-over')).toHaveCount(0)
    await expect(mobile.getByTestId('worktree-1')).toContainText('run:43')
    await expect(web.getByTestId('worktree-2')).toContainText('run:43')

    await working.getByRole('link', { name: 'ABC-101' }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-101$/)
    await page.goBack()

    const reads = page.waitForResponse((r) => r.url().endsWith('/api/worktrees'))
    await page.getByTestId('worktrees-refresh').click()
    expect((await reads).status()).toBe(200)
})

test('the worktrees page reads the pools again every 30 seconds, and only while it is open', async ({ page }) => {
    await page.clock.install()
    let reads = 0
    page.on('request', (r) => {
        if (r.url().endsWith('/api/worktrees')) reads += 1
    })
    await page.goto('worktrees')
    await settled(page)
    expect(reads).toBe(1)

    await page.clock.runFor(29_000)
    expect(reads).toBe(1)
    const next = page.waitForResponse((r) => r.url().endsWith('/api/worktrees'))
    await page.clock.runFor(1_000)
    expect((await next).status()).toBe(200)
    expect(reads).toBe(2)

    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Runs' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await page.clock.runFor(90_000)
    expect(reads).toBe(2)
})
