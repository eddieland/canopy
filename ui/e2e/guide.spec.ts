import { expect, test } from '@playwright/test'

import { FULL_RAIL, settled, signIn, storeTheme, windowWidth } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the rail's foot opens the guide at its first page, its pages listed by group beside it", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.getByTestId('rail-guide').click()
    await expect(page).toHaveURL(/\/guide\/overview$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('The web UI')
    await expect(page).toHaveTitle(/^(?:\(\d+\) )?The web UI · Guide · canopy$/u)
    const sidebar = page.getByRole('navigation', { name: 'Guide' })
    await expect(sidebar.getByRole('region', { name: 'Getting started' })).toBeVisible()
    await expect(sidebar.getByRole('link', { name: 'The web UI' })).toHaveAttribute('aria-current', 'page')
    await expect(sidebar.getByRole('link', { name: 'Signing in' })).not.toHaveAttribute('aria-current', 'page')
})

test('a page links to a heading on it, to the next page and back, and to a section of the app', async ({ page }) => {
    // Wide enough for On this page beside the article.
    await page.setViewportSize({ width: 1600, height: 900 })
    await page.goto('guide/overview')

    await page.getByRole('navigation', { name: 'On this page' }).getByRole('link', { name: 'The rail' }).click()
    await expect(page).toHaveURL(/\/guide\/overview#the-rail$/u)
    await expect(page.getByRole('heading', { level: 2, name: 'The rail' })).toBeInViewport()

    const steps = page.getByRole('navigation', { name: 'Previous and next' })
    await steps.getByRole('link', { name: /Next.*Signing in/u }).click()
    await expect(page).toHaveURL(/\/guide\/signing-in$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Signing in')
    await steps.getByRole('link', { name: /Previous.*The web UI/u }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('The web UI')

    await page.getByTestId('guide-page').getByRole('link', { name: 'Signing in', exact: true }).click()
    await page.getByTestId('guide-page').getByRole('link', { name: 'Settings' }).click()
    await expect(page).toHaveURL(/\/settings$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
})

test("a page's book opens the guide at the part about it, and the guide's own pages have none", async ({ page }) => {
    await page.goto('workspace/runs/39')
    await settled(page)
    await page.getByTestId('page-guide').click()
    await expect(page).toHaveURL(/\/guide\/runs#a-runs-page$/u)
    await expect(page.getByRole('heading', { level: 2, name: "A run's page" })).toBeInViewport()
    await expect(page.getByTestId('page-guide')).toHaveCount(0)
})

test('in a narrow pane, the guide pages fold into a toggle above the page', async ({ page }) => {
    await page.setViewportSize({ width: 800, height: 900 })
    await page.goto('guide/overview')
    await expect(page.getByRole('navigation', { name: 'Guide' })).toBeHidden()
    await page.getByRole('button', { name: 'Guide pages' }).click()
    await page.getByRole('navigation', { name: 'Guide' }).getByRole('link', { name: 'Signing in' }).click()
    await expect(page).toHaveURL(/\/guide\/signing-in$/u)
})

test("the guide's columns come in by the pane's width, and never take the article's measure", async ({ page }) => {
    await page.goto('guide/overview')
    await settled(page)
    const pane = page.getByTestId('guide')
    const article = page.getByTestId('guide-page')
    const pages = page.getByRole('navigation', { name: 'Guide' })
    const headings = page.getByRole('navigation', { name: 'On this page' })
    // The article's measure, max-w-3xl: it keeps that, or the whole pane when the pane is narrower.
    const measure = 768
    for (const width of [960, FULL_RAIL - 1, FULL_RAIL, 1279, 1280, 1440]) {
        await windowWidth(page, width)
        const room = (await pane.boundingBox())?.width ?? 0
        const text = (await article.boundingBox())?.width ?? 0
        expect(Math.abs(text - Math.min(measure, room)), `at ${width}px`).toBeLessThanOrEqual(1)
    }
    // At 1024px the whole rail leaves the article nearly its measure, and the page list waits for room.
    await windowWidth(page, FULL_RAIL)
    expect((await article.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(700)
    await expect(pages).toBeHidden()
    await expect(page.getByRole('button', { name: 'Guide pages' })).toBeVisible()
    // At 1280px the page list is beside it; at 1600px, On this page too.
    await windowWidth(page, 1280)
    await expect(pages).toBeVisible()
    await expect(headings).toBeHidden()
    await windowWidth(page, 1600)
    await expect(headings).toBeVisible()
    expect((await article.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(measure - 1)
})

test("a code block is colored by its fence's language once the grammar loads", async ({ page }) => {
    await page.goto('guide/config-files')
    const config = page.getByTestId('guide-page').locator('pre').last()
    await expect(config).toHaveAttribute('data-highlighted', 'true')
    // The same characters, a comment muted and a string in its own color.
    await expect(config).toContainText('labels = ["agent-ready-yourname"]')
    await expect(config.getByText(/^# Your queue\./u)).toHaveClass('text-muted-foreground')
    await expect(config.getByText('"agent-ready-yourname"', { exact: true }).first()).toHaveClass('text-syntax-string')
})

test('a diagram is drawn as its picture, named for a screen reader, and drawn again in the other theme', async ({
    page,
}) => {
    await storeTheme(page, 'dark')
    await page.goto('guide/how-the-loop-works')
    const guide = page.getByTestId('guide-page')
    for (const name of [
        'The loop: a tick, then a wait until the next one',
        'A run, from the worktree it leases to how it ends',
        "A ticket's usual path, from ready to merged",
    ]) {
        const diagram = guide.getByRole('img', { name })
        await expect(diagram).toBeVisible()
        expect(await diagram.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(100)
    }
    await expect(guide.getByText('accTitle', { exact: false })).toHaveCount(0)

    const run = guide.getByRole('img', { name: 'A run, from the worktree it leases to how it ends' })
    const dark = await run.getAttribute('src')
    await page.getByTestId('theme-toggle').click()
    await expect(run).not.toHaveAttribute('src', dark ?? '')
})

test('a page the guide does not have is the 404', async ({ page }) => {
    await page.goto('guide/no-such-page')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Nothing here')
})
