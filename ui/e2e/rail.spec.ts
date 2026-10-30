import { expect, test } from '@playwright/test'

import { NOW, settled, signIn, spentInWindows, storePalette, storeTheme } from './helpers.ts'

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
    await expect(working.getByRole('link', { name: '+1 more' })).toHaveAttribute('href', /\/workspace\/runs$/u)
    await expect(page.getByTestId('rail-run-41')).toContainText('Sign in with SSO')
    await expect(page.getByTestId('rail-chore-build-health')).toContainText('chore run #4')
    await expect(page.getByTestId('rail-task-6')).toContainText("Add a dark launch screen to match the app's theme.")

    await page.getByTestId('rail-run-41').click()
    await expect(page).toHaveURL(/\/workspace\/runs\/41$/u)
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
        /^Pull requests/u,
        'Workspace',
        'Chores',
        'Reports',
        /^Memory/u,
    ])

    await page.getByTestId('rail-settings').click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
    // Out of the nav, Settings is no item for its highlight to land on.
    await expect(page.getByTestId('nav-highlight')).toHaveClass(/\bopacity-0\b/u)
})

test('the rail shows the spend of the last day and the last 30, and the version at its foot', async ({ page }) => {
    const spend = (await (await page.request.get('api/spend')).json()) as { day: { cost_usd: number } }
    await page.goto('workspace/ticks')
    await settled(page)
    await expect(page.getByTestId('rail-spend-24h')).toHaveText(`$${spend.day.cost_usd.toFixed(2)}`)
    await expect(page.getByTestId('rail-spend-30d')).toHaveText(/^\$\d+\.\d\d$/u)
    await expect(page.getByTestId('rail-footer')).toContainText(/canopy \S+/u)
    await expect(page.getByTestId('rail-version')).toHaveAttribute(
        'href',
        'https://github.com/eddieland/canopy/releases',
    )
})

test("the rail's spend at an operator's figures: two rows set alike, the costs right-aligned", async ({ page }) => {
    await spentInWindows(page, 412.07, 3118.94)
    await storeTheme(page, 'dark')
    await page.goto('attention')
    await settled(page)
    const spend = page.getByTestId('rail-spend')
    await expect(spend.getByTestId('rail-spend-24h')).toHaveText('$412.07')
    await expect(spend.getByTestId('rail-spend-30d')).toHaveText('$3,118.94')
    // Each cost on its own row, the 30 days under the 24 hours, their right edges one line.
    const rect = (testId: string): Promise<DOMRect> =>
        spend.getByTestId(testId).evaluate((el) => el.getBoundingClientRect().toJSON() as DOMRect)
    const day = await rect('rail-spend-24h')
    const month = await rect('rail-spend-30d')
    expect(month.top).toBeGreaterThanOrEqual(day.bottom)
    expect(Math.abs(month.right - day.right)).toBeLessThan(1)
    await expect(spend).toHaveScreenshot('rail-spend-dark.png')
})

test("the spend stands on the footer at the rail's foot, the room above it one gap", async ({ page }) => {
    await page.setViewportSize({ width: 1720, height: 1440 })
    await page.goto('attention')
    await settled(page)
    const rect = (testId: string): Promise<DOMRect> =>
        page.getByTestId(testId).evaluate((el) => el.getBoundingClientRect().toJSON() as DOMRect)
    const working = await rect('rail-working')
    const spend = await rect('rail-spend')
    const footer = await rect('rail-footer')
    // The spend sits right on the footer's hairline, and the footer on the window's foot.
    expect(Math.abs(footer.top - spend.bottom)).toBeLessThan(1)
    expect(Math.round(footer.bottom)).toBe(1440)
    // What the window leaves over is between what is working and the spend, not under the spend.
    expect(spend.top - working.bottom).toBeGreaterThan(400)

    // An 800px window still holds the rail whole: what is working ends above the foot, not cut off under it.
    await page.setViewportSize({ width: 1280, height: 800 })
    await expect
        .poll(async () => (await rect('rail-spend')).top - (await rect('rail-working')).bottom)
        .toBeGreaterThan(0)
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

// The default palette, and the two whose mono face runs wider than the sans.
for (const [theme, palette] of [
    ['dark', 'indigo'],
    ['dark', 'monokai'],
    ['light', 'gruvbox'],
] as const) {
    test(`the foot's buttons split the hairline's width in ${theme} ${palette}`, async ({ page }) => {
        await storeTheme(page, theme)
        await storePalette(page, theme, palette)
        await page.goto('attention')
        await settled(page)
        const rect = (testId: string): Promise<DOMRect> =>
            page.getByTestId(testId).evaluate((el) => el.getBoundingClientRect().toJSON() as DOMRect)
        const footer = await rect('rail-footer')
        const guide = await rect('rail-guide')
        const settings = await rect('rail-settings')
        expect(settings.top).toBe(guide.top)
        // Edge to edge on the hairline, half each.
        expect(Math.abs(guide.left - footer.left)).toBeLessThan(1)
        expect(Math.abs(settings.right - footer.right)).toBeLessThan(1)
        expect(Math.abs(settings.width - guide.width)).toBeLessThan(1)
        // Each label whole, not cut short.
        for (const testId of ['rail-guide', 'rail-settings']) {
            const button = page.getByTestId(testId)
            expect(await button.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
        }
    })
}
