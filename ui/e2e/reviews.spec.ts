import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('a review opens from the nav and puts each finding on its line of the diff', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    await nav.getByRole('link', { name: 'Reviews' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Reviews')
    // The operator's own PR, matched by review.query, has no ticket: canopy only reviews it.
    await expect(page.getByTestId('review-2').getByTitle('none: canopy only reviews it')).toHaveText('none')

    await page.getByTestId('review-4').getByRole('link', { name: 'review:4' }).click()
    await expect(page).toHaveURL(/\/reviews\/4$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('review:4 acme/web#88 Debounce search input')
    await expect(nav.getByRole('link', { name: 'Reviews' })).toHaveAttribute('data-status', 'active')

    const files = page.getByTestId('diff-file')
    await expect(files).toHaveCount(2)
    // The major finding sits right under the line it names, in the file it names.
    const hook = files.filter({ hasText: 'src/search/useSearch.ts' })
    const card = hook.getByTestId('finding').filter({ hasText: 'A failed request leaves the spinner on' })
    await expect(card).toBeVisible()
    const above = card.locator('xpath=ancestor::tr/preceding-sibling::tr[1]')
    await expect(above).toContainText('setLoading(false)')
    // Its code is colored once TypeScript's grammar loads: the same characters, a keyword in its own color.
    await expect(above.locator('[data-highlighted]')).toHaveText(/setLoading\(false\)/u)
    await expect(hook.locator('[data-highlighted]').getByText('export', { exact: true }).first()).toHaveClass(
        'text-syntax-literal',
    )
    // A finding about a file the diff does not touch has a panel of its own.
    await expect(page.getByText('Not in the diff', { exact: true })).toBeVisible()

    // The findings list links to each card.
    await page.getByRole('link', { name: 'The debounce delay is a bare number' }).click()
    await expect(page).toHaveURL(/#finding-2$/u)
    await expect(page.locator('#finding-2')).toBeInViewport()
})

test('a review from before diffs were kept lists its findings without one', async ({ page }) => {
    await page.goto('reviews/1')
    await expect(page.getByText('no diff kept for this review')).toBeVisible()
    await expect(page.getByTestId('finding')).toHaveCount(1)
    // The PR's other review links to its newer one.
    await page.getByRole('link', { name: 'review:4' }).click()
    await expect(page).toHaveURL(/\/reviews\/4$/u)
})

test('a review that does not exist says so', async ({ page }) => {
    await page.goto('reviews/99')
    await expect(page.getByText('no review run 99')).toBeVisible()
})

test("a review's files fold away on their headers, and hide by type, until a finding's link wants one", async ({
    page,
}) => {
    await page.goto('reviews/4')
    const files = page.getByTestId('diff-file')
    const box = files.filter({ hasText: 'src/search/SearchBox.tsx' })
    const hook = files.filter({ hasText: 'src/search/useSearch.ts' })

    // A file folds to its header and a line counting what it hides; the rest stay open.
    await box.getByRole('button', { name: 'Hide diff' }).click()
    await expect(box.locator('tr[data-kind]')).toHaveCount(0)
    await expect(box).toContainText('9 lines and 1 finding folded away')
    await expect(hook.locator('tr[data-kind]')).not.toHaveCount(0)
    // The findings list's link to a card on it opens it again.
    await page.getByRole('link', { name: 'The debounce delay is a bare number' }).click()
    await expect(page.locator('#finding-2')).toBeInViewport()
    await expect(box.getByRole('button', { name: 'Hide diff' })).toBeVisible()

    // The menu of file types has every one ticked; unticking one hides its files.
    const types = page.getByTestId('diff-file-types')
    await expect(types).toHaveText('All file types')
    await types.click()
    const menu = page.getByRole('menu')
    const tsx = menu.getByRole('menuitemcheckbox', { name: '.tsx, 1 file', exact: true })
    await expect(menu.getByRole('menuitemcheckbox', { name: '.ts, 1 file', exact: true })).toBeVisible()
    await expect(menu.getByRole('menuitemcheckbox')).toHaveCount(2)
    await tsx.click()
    await expect(tsx).toHaveAttribute('aria-checked', 'false')
    await page.keyboard.press('Escape')
    await expect(types).toHaveText('.ts only')
    await expect(page.getByTestId('diff-hidden-files')).toHaveText('1 file hidden by type')
    await expect(files).toHaveCount(1)
    await expect(hook).toBeVisible()

    // A link to a finding on a hidden file ticks its type again: the same link as before, the hash unchanged.
    await page.getByRole('link', { name: 'The debounce delay is a bare number' }).click()
    await expect(files).toHaveCount(2)
    await expect(page.locator('#finding-2')).toBeInViewport()
    await expect(types).toHaveText('All file types')
})
