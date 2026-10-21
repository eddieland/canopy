import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { NOW, openRepoPicker, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await page.clock.setFixedTime(NOW)
    await signIn(page)
})

/** The names of the PRs the pull requests list shows, sorted: the order is the list's own, by activity. */
async function prs(page: Page): Promise<string[]> {
    const names = await page
        .getByTestId('pull-requests')
        .getByTestId('pull-request')
        .evaluateAll((rows) => rows.map((r) => /acme\/\w+#\d+/u.exec(r.textContent)?.[0] ?? ''))
    return names.toSorted()
}

/** The test ids of the rows the reviews list shows, sorted. */
async function reviews(page: Page): Promise<string[]> {
    const ids = await page
        .getByTestId('reviews')
        .locator('[data-testid^="review-"], [data-testid^="requested-"]')
        .evaluateAll((rows) => rows.map((r) => (r as HTMLElement).dataset.testid ?? ''))
    return ids.toSorted()
}

test('the pull requests list filters by repositories and by words, in the URL', async ({ page }) => {
    await page.goto('pull-requests')
    await settled(page)
    const picker = page.getByRole('button', { name: /^Filter by repository: /u })
    await expect(picker).toHaveAccessibleName('Filter by repository: every repository')
    const repos = await openRepoPicker(picker)
    await expect(repos.getByRole('option', { name: 'every repository' })).toHaveAttribute('aria-checked', 'true')

    await repos.getByRole('option', { name: 'api', exact: true }).click()
    await expect(page).toHaveURL(/\/pull-requests\?repo=api$/u)
    await expect.poll(() => prs(page)).toEqual(['acme/api#12'])
    await expect(page.getByTestId('pull-requests-count')).toHaveText(/^1 of \d+$/u)

    // A second repository adds to the first while the list stays open; taking the first away leaves the second.
    await repos.getByRole('option', { name: 'web', exact: true }).click()
    await expect(page).toHaveURL(/[?&]repo=api%2Cweb/u)
    await expect(picker).toHaveAccessibleName('Filter by repository: api, web')
    await expect.poll(() => prs(page)).toEqual(['acme/api#12', 'acme/web#88', 'acme/web#91'])
    await repos.getByRole('option', { name: 'api', exact: true }).click()
    await expect(page).toHaveURL(/[?&]repo=web(?:&|$)/u)
    await page.keyboard.press('Escape')
    await expect(repos).toHaveCount(0)

    const field = page.getByRole('searchbox', { name: 'Filter pull requests by PR, ticket, or title' })
    await field.fill('DEBOUNCE')
    await expect(page).toHaveURL(/[?&]q=DEBOUNCE/u)
    await expect(page).toHaveURL(/[?&]repo=web/u)
    await expect.poll(() => prs(page)).toEqual(['acme/web#88'])

    await field.fill('nothing like it')
    await expect(page.getByText('no PRs in web with “nothing like it”')).toBeVisible()

    await (await openRepoPicker(picker)).getByRole('option', { name: 'every repository' }).click()
    await expect(page).toHaveURL(/\/pull-requests\?q=nothing/u)
})

test('a link to the pull requests list names its repositories in the URL, one or several', async ({ page }) => {
    await page.goto('pull-requests?repo=web,api')
    await settled(page)
    await expect(page.getByRole('button', { name: 'Filter by repository: api, web' })).toBeVisible()
    await expect.poll(() => prs(page)).toEqual(['acme/api#12', 'acme/web#88', 'acme/web#91'])
    await page.goto('pull-requests?repo=api,Not-A-Repo')
    await settled(page)
    await expect.poll(() => prs(page)).toEqual(['acme/api#12'])
})

test('the reviews list filters by repository and by words, and a request waits out a repository', async ({ page }) => {
    await page.goto('reviews?q=web%2388')
    await settled(page)
    const field = page.getByRole('searchbox', { name: 'Filter reviews by PR, ticket, or commit' })
    await expect(field).toHaveValue('web#88')
    await expect.poll(() => reviews(page)).toEqual(['review-1', 'review-4'])

    await field.fill('acme')
    // The PR waiting on its review is listed while no repository is chosen.
    await expect(page.getByTestId('requested-https://github.com/acme/web/pull/95')).toBeVisible()
    const repos = await openRepoPicker(page.getByRole('button', { name: 'Filter by repository: every repository' }))
    await repos.getByRole('option', { name: 'api', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(page).toHaveURL(/[?&]repo=api/u)
    await expect.poll(() => reviews(page)).toEqual(['review-2'])
    await expect(page.getByTestId('reviews-count')).toHaveText(/^1 of \d+$/u)

    await field.fill('abc-099')
    await expect(page.getByText('no reviews in api with “abc-099”')).toBeVisible()
})
