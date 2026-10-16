import { expect, test } from '@playwright/test'

import { diffFile, serveReview, signIn } from './helpers.ts'
import type { DiffFinding } from './helpers.ts'

// A review at the server's bounds is the largest the page is ever sent: 500 files and 30,000 lines in its diff
// (canopy/core/review_diff.py) and 20 findings (canopy/core/review_result.py). Drawn whole, such a diff took seconds to
// show and seconds more for each click on the page; the page draws 2,000 of its lines at first and a fold shows 500
// more a click (DIFF_BUDGET in src/lib/review-folds.ts).
const MAX_FILES = 500
const MAX_LINES = 30_000
const MAX_FINDINGS = 20
const MAX_DETAIL = 1000
const PAGE_LINES = 2000
const STEP = 500

/** A minor finding titled `title`, on `line` of the diff's file `file`, with as long a detail as a finding may have. */
function finding(title: string, file: number | null, line: number | null): DiffFinding {
    const location = file === null ? 'docs/elsewhere.md:1' : `src/f${file}.ts${line === null ? '' : `:${line}`}`
    return { severity: 'minor', title, location, detail: 'd '.repeat(MAX_DETAIL / 2), file, line, dismissed: false }
}

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('a review of as many files as a diff holds draws its findings in place, and folds the rest', async ({ page }) => {
    const perFile = MAX_LINES / MAX_FILES
    const files = Array.from({ length: MAX_FILES }, (_, f) =>
        diffFile(`src/f${f}.ts`, perFile, (n) => `f${f} line ${n}`),
    )
    // Half the findings on one line, most of the rest on lines in a row, one on a file's header, one on no file.
    const findings = [
        ...Array.from({ length: 10 }, (_, i) => finding(`crowded ${i + 1}`, 499, 30)),
        ...Array.from({ length: 8 }, (_, i) => finding(`in a row ${i + 1}`, 250, i + 1)),
        finding('about a file', 100, null),
        finding('about no file in the diff', null, null),
    ]
    expect(findings).toHaveLength(MAX_FINDINGS)
    await serveReview(page, files, findings)
    await page.goto('reviews/4')

    await expect(page.getByTestId('finding')).toHaveCount(MAX_FINDINGS)
    await expect(page.getByTestId('diff-file')).toHaveCount(MAX_FILES)
    await expect(page.getByTestId('diff-folded')).toContainText('the page shows 2,000 of its 30,000 lines at first')
    await expect(page.locator('tr[data-kind]')).toHaveCount(PAGE_LINES)

    // The ten findings on one line sit together, right under it.
    const crowded = page.getByTestId('diff-file').nth(499).getByTestId('finding')
    await expect(crowded).toHaveCount(10)
    const above = crowded.first().locator('xpath=ancestor::tr/preceding-sibling::tr[1]')
    await expect(above).toContainText('f499 line 30')
    // The findings list still reaches a card far down the page.
    await page.getByRole('link', { name: 'crowded 7', exact: true }).click()
    await expect(page.locator('#finding-7')).toBeInViewport()

    // A file the page has no room for is its header and a fold, which shows the file's lines.
    const folded = page.getByTestId('diff-file').nth(400)
    await expect(folded.locator('tr[data-kind]')).toHaveCount(0)
    await folded.getByRole('button', { name: `Show ${perFile} hidden lines` }).click()
    await expect(folded.locator('tr[data-kind]')).toHaveCount(perFile)
    await expect(folded.getByTestId('diff-fold')).toHaveCount(0)
})

test("a file of as many lines as a diff holds shows them a fold's step at a time, its cards in reach", async ({
    page,
}) => {
    // A thousand-character line among the ones the findings sit on, which scrolls the file's table sideways.
    const files = [diffFile('src/f0.ts', MAX_LINES, (n) => (n === 15_005 ? 'w'.repeat(1000) : `line ${n}`))]
    const findings = Array.from({ length: MAX_FINDINGS }, (_, i) => finding(`line ${15_000 + i}`, 0, 15_000 + i))
    await serveReview(page, files, findings)
    await page.goto('reviews/4')

    await expect(page.getByTestId('finding')).toHaveCount(MAX_FINDINGS)
    await expect(page.locator('tr[data-kind]')).toHaveCount(PAGE_LINES)
    // The first lines, then the findings' lines and ten either side, with a fold before them and after.
    const folds = page.getByTestId('diff-fold')
    await expect(folds).toHaveText([`Show ${STEP} of 13,029 hidden lines`, `Show ${STEP} of 14,971 hidden lines`])
    await folds.first().getByRole('button').click()
    await expect(page.locator('tr[data-kind]')).toHaveCount(PAGE_LINES + STEP)
    await expect(folds.first()).toHaveText(`Show ${STEP} of 12,529 hidden lines`)

    // Scrolled to the long line's end, each card still sits inside the panel, its text in reach.
    const panel = page.getByTestId('diff-file')
    const scroller = panel.locator('.overflow-x-auto')
    await scroller.evaluate((el) => el.scrollTo({ left: el.scrollWidth }))
    const box = await panel.boundingBox()
    for (const card of await page.getByTestId('finding').all()) {
        const { x, width } = (await card.boundingBox()) ?? { x: -1, width: 0 }
        expect(x).toBeGreaterThanOrEqual(box?.x ?? Infinity)
        expect(x + width).toBeLessThanOrEqual((box?.x ?? 0) + (box?.width ?? 0))
    }
})
