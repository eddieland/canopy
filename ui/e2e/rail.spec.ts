import { expect, test } from '@playwright/test'

import { NOW, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await signIn(page)
})

test('the rail lists what is working now, the running runs, chore runs, and task runs first, on every page', async ({
    page,
}) => {
    await page.goto('tickets')
    await settled(page)
    const working = page.getByTestId('rail-working')
    // Four rows, then `+1 more`: ABC-102's run, waiting on you, comes after the four running.
    await expect(working.getByRole('link')).toHaveCount(5)
    // The chore run started ten minutes before the worker runs, and task 6's run between them.
    await expect(working.getByRole('link').first()).toContainText('build-health')
    await expect(working.getByRole('link').nth(1)).toContainText('ABC-101')
    await expect(working.getByRole('link').nth(2)).toContainText('task:6#6')
    await expect(working.getByRole('link').nth(3)).toContainText('ABC-104')
    await expect(working.getByRole('link', { name: '+1 more' })).toHaveAttribute('href', /\/runs$/u)
    await expect(page.getByTestId('rail-run-41')).toContainText('Sign in with SSO')
    await expect(page.getByTestId('rail-chore-build-health')).toContainText('chore run #4')
    await expect(page.getByTestId('rail-task-6')).toContainText("Add a dark launch screen to match the app's theme.")

    await page.getByTestId('rail-run-41').click()
    await expect(page).toHaveURL(/\/runs\/41$/u)
    await expect(page.getByTestId('rail-run-41')).toBeVisible()

    await page.getByTestId('rail-chore-build-health').click()
    await expect(page).toHaveURL(/\/chores\/build-health\/runs\/4$/u)

    await page.getByTestId('rail-task-6').click()
    await expect(page).toHaveURL(/\/tasks\/6\/runs\/6$/u)
    await expect(page.getByRole('heading', { level: 1 })).toContainText('task:6#6')
})

test("a worker run's row says what it is doing, as a quip until Settings turns them off", async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    // Run 43 resumes for a failed check and review feedback together. Run 42, waiting on the operator, is past the four
    // rows the rail shows, so the unit tests hold its plain words.
    const resuming = page.getByTestId('rail-phase-43')
    await expect(resuming).toHaveAttribute('title', 'fixing CI, addressing review')
    await expect(resuming).toHaveText(/CI.* \+1$/u)

    await page.getByTestId('fun-quips').click()
    await expect(resuming).toHaveText('fixing CI, addressing review')
    await page.reload()
    await settled(page)
    await expect(page.getByTestId('fun-quips')).not.toBeChecked()
    await expect(page.getByTestId('rail-phase-41')).toHaveText('implementing')
})

test('the nav lists the sections by how often the operator opens them, and the foot opens Settings', async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link')).toHaveText([
        /^Attention/u,
        'Tickets',
        'Tasks',
        'Pull requests',
        /^Reviews/u,
        'Runs',
        'Chores',
        'Spend',
        'Ticks',
        'Worktrees',
        /^Memory/u,
    ])

    await page.getByTestId('rail-settings').click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
    // Out of the nav, Settings is no item for its highlight to land on.
    await expect(page.getByTestId('nav-highlight')).toHaveClass(/\bopacity-0\b/u)
})

test('the rail shows the spend of the last day and the last 30, and the version at its foot', async ({ page }) => {
    const spend = (await (await page.request.get('api/spend')).json()) as { day: { cost_usd: number } }
    await page.goto('ticks')
    await settled(page)
    await expect(page.getByTestId('rail-spend-24h')).toHaveText(`$${spend.day.cost_usd.toFixed(2)}`)
    await expect(page.getByTestId('rail-spend-30d')).toHaveText(/^\$\d+\.\d\d$/u)
    await expect(page.getByTestId('rail-footer')).toContainText(/canopy \S+/u)
    await expect(page.getByTestId('rail-version')).toHaveAttribute(
        'href',
        'https://github.com/eddieland/canopy/releases',
    )
})

test('the version stays at the window foot on a page longer than the window', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 600 })
    await page.goto('settings')
    await settled(page)
    const scroller = page.locator('[data-scroll-restoration-id=page]')
    expect(await scroller.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)

    const version = page.getByTestId('rail-version')
    await expect(version).toBeInViewport()
    await scroller.evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
    await expect(version).toBeInViewport()
    const box = await page.getByTestId('rail-footer').boundingBox()
    expect(box === null ? 0 : Math.round(box.y + box.height)).toBe(600)
})
