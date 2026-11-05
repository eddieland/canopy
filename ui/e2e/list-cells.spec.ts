import { expect, test } from '@playwright/test'

import { growFigures, NOW, settled, signIn } from './helpers.ts'

// A list row's cell cuts what overflows it, never draws over the next column (ui/DESIGN.md, `ListRow`): grown to a
// long-lived journal's figures (growFigures), its ids and counts are wider than the mock's, and still each stays in
// its box.
const PAGES = [
    'workspace/runs',
    'tickets',
    'pull-requests',
    'pull-requests/reviews',
    'tasks',
    'workspace/ticks',
    'workspace/worktrees',
    'memory',
    'chores',
] as const

// The reads those pages list their rows from: growing every read under `/api` makes a page's stream flaky.
const READS = /\/api\/(?:runs|tickets|pull-requests|reviews|review-requests|tasks|ticks|worktrees|memory|chores)/u

for (const width of [1280, 1720]) {
    for (const path of PAGES) {
        test(`${path} keeps each cell's text in its column at ${width}px`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await signIn(page)
            await growFigures(page, READS)
            await page.setViewportSize({ width, height: 900 })
            await page.goto(path)
            await settled(page)
            await expect(page.locator('main li').first()).toBeVisible()
            const spilled = await page.locator('main li').evaluateAll((rows: HTMLElement[]) =>
                rows
                    .filter((row) => getComputedStyle(row).display === 'grid' && row.checkVisibility())
                    // A head-line cell is placed by its order; what goes under the head line is placed from a column.
                    .flatMap((row) =>
                        [...row.children].filter(
                            (cell): cell is HTMLElement =>
                                cell instanceof HTMLElement &&
                                cell.checkVisibility() &&
                                getComputedStyle(cell).gridColumnStart === 'auto',
                        ),
                    )
                    .filter((cell) => {
                        // A cell that clips its content keeps it in its box, whatever it holds.
                        if (getComputedStyle(cell).overflowX !== 'visible') {
                            return false
                        }
                        const right = cell.getBoundingClientRect().right
                        const past = [...cell.querySelectorAll('*')].some(
                            (inner) => inner.checkVisibility() && inner.getBoundingClientRect().right > right + 1,
                        )
                        return past || cell.scrollWidth > cell.clientWidth + 1
                    })
                    .map((cell) => cell.textContent.trim()),
            )
            expect(spilled).toEqual([])
            await page.unrouteAll({ behavior: 'ignoreErrors' })
        })
    }
}
