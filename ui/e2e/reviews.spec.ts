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
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('review:4')
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
