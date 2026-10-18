import { expect, test } from '@playwright/test'

import { signIn } from './helpers.ts'

// A page whose read fails says so, with a way to read again, in place of the skeleton, rather than shimmer as if the
// read were still coming (ui/DESIGN.md, Primitives, PanelLoading). Each case: the page, the read that fails, and a
// glob for it that matches nothing else the page reads.
const PAGES = [
    { page: 'runs/39', read: '**/api/runs/39' },
    { page: 'tickets/ABC-102', read: '**/api/tickets/ABC-102' },
    { page: 'tickets/ABC-105/plan', read: '**/api/tickets/ABC-105/plans' },
    { page: 'ticks/2', read: '**/api/ticks/2' },
    { page: 'chores/deps', read: '**/api/chores/deps' },
    { page: 'reviews/4', read: '**/api/reviews/4' },
    { page: 'spend', read: '**/api/spend/breakdown*' },
    { page: 'search?q=web', read: '**/api/search*' },
    { page: 'worktrees', read: '**/api/worktrees' },
] as const

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

for (const { page: path, read } of PAGES) {
    test(`${path} says its read failed, and reads again`, async ({ page }) => {
        let failing = true
        await page.route(read, async (route) => {
            await (failing ? route.fulfill({ status: 500, json: { detail: 'database is locked' } }) : route.fallback())
        })
        await page.goto(path)
        const failed = page.getByTestId('panel-failed')
        await expect(failed.getByRole('alert')).toHaveText(
            'could not read it: the server answered 500: database is locked',
        )
        await expect(page.getByTestId('panel-skeleton')).toHaveCount(0)
        failing = false
        await failed.getByRole('button', { name: 'Read again' }).click()
        await expect(failed).toHaveCount(0)
    })
}

test('a read that gets no answer says canopy did not answer, and what serves the page', async ({ page }) => {
    await page.route('**/api/runs/39', (route) => route.abort())
    await page.goto('runs/39')
    await expect(page.getByTestId('panel-failed').getByRole('alert')).toContainText('canopy did not answer')
    await expect(page.getByTestId('panel-failed').getByRole('alert')).toContainText('canopy loop')
})

test("a failed read's notice keeps the skeleton's height, so nothing moves", async ({ page }) => {
    await page.goto('runs/39')
    let release: (() => void) | undefined
    const held = new Promise<void>((resolve) => {
        release = resolve
    })
    await page.route('**/api/runs/41', async (route) => {
        await held
        await route.fulfill({ status: 500, json: { detail: 'database is locked' } })
    })
    await page.goto('runs/41')
    const pending = await page.getByTestId('panel-skeleton').boundingBox()
    release?.()
    const failed = await page.getByTestId('panel-failed').boundingBox()
    // Within a pixel: layout rounds the same height to a hair either side of it.
    expect(failed?.height).toBeCloseTo(pending?.height ?? 0, 0)
})

test('the worktrees with no pool at all say how to make them', async ({ page }) => {
    await page.route('**/api/worktrees', (route) => route.fulfill({ json: [] }))
    await page.goto('worktrees')
    await expect(page.getByTestId('pools')).toContainText('no pools yet: canopy workspace sync makes one for each')
})
