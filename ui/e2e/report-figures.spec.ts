import { expect, test } from '@playwright/test'

import { growFigures, NOW, settled, signIn } from './helpers.ts'

// A report's figures sit in columns sized by the table to its widest, never by a width guessed from the mock's: grown
// to a long-lived journal's (growFigures), no figure breaks over two lines (ui/DESIGN.md, "A bar in a cell").
const PAGES = [
    'reports',
    'reports/spend',
    'reports/checklist',
    'reports/health',
    'reports/ci',
    'reports/reviews',
    'reports/plans',
    'chores/deps',
] as const

// What a figure reads as: digits and what goes with them, `$1,234.56`, `12 of 15`, `40%`, `3.0h`, `1.2M`, `–`.
const FIGURE = /^[\s\d$.,%–+−-]*\d[\s\d$.,%–+−-]*(?:of[\s\d,]+)?[kKMmhd%]?$|^–$/u

for (const width of [1280, 1720]) {
    for (const path of PAGES) {
        test(`${path} keeps each figure on one line at ${width}px`, async ({ page }) => {
            await page.clock.setFixedTime(NOW)
            await signIn(page)
            await growFigures(page, /\/api\/(?:reports|spend|chores)/u)
            await page.setViewportSize({ width, height: 900 })
            await page.goto(path)
            await settled(page)
            await expect(page.locator('main table').first()).toBeVisible()
            const broken = await page.locator('main table tbody td').evaluateAll(
                (cells: HTMLElement[], pattern: string) =>
                    cells
                        .filter(
                            (cell) => cell.checkVisibility() && new RegExp(pattern, 'u').test(cell.textContent.trim()),
                        )
                        .filter((cell) => {
                            const range = document.createRange()
                            range.selectNodeContents(cell)
                            const tops = new Set(
                                [...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top)),
                            )
                            return tops.size > 1
                        })
                        .map((cell) => cell.textContent.trim()),
                FIGURE.source,
            )
            expect(broken).toEqual([])
            await page.unrouteAll({ behavior: 'ignoreErrors' })
        })
    }
}
