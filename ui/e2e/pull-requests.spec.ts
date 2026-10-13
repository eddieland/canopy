import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the pull requests list has each PR once, and a PR's page its runs, reviews, and decisions", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    await nav.getByRole('link', { name: 'Pull requests' }).click()
    await expect(page).toHaveURL(/\/pull-requests$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Pull requests')
    const rows = page.getByTestId('pull-requests').getByTestId('pull-request')
    await expect(rows).toHaveCount(3)
    const ours = rows.filter({ hasText: 'acme/web#88' })
    await expect(ours).toContainText('Debounce search input')
    await expect(ours.getByTestId('pull-request-review')).toContainText('review 4')
    // A PR canopy only reviews has no ticket, whoever asked for the review.
    await expect(rows.filter({ hasText: 'acme/api#12' })).toContainText('no ticket')

    await ours.getByRole('link', { name: 'acme/web#88' }).click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('github.com/acme/web/pull/88')
    await expect(nav.getByRole('link', { name: 'Pull requests' })).toHaveAttribute('data-status', 'active')
    // The run that opened it, its two reviews, and what the loop decided about it.
    await expect(page.getByTestId('pull-request-runs').getByRole('link', { name: 'run:39' })).toBeVisible()
    await expect(page.getByTestId('pull-request-reviews').getByRole('link', { name: /^review /u })).toHaveCount(2)
    await expect(page.getByTestId('pull-request-decisions')).toContainText('needs reviewer')

    // A review opens its findings on its diff, and leads back to its PR's page.
    await page.getByTestId('pull-request-review-4').getByRole('link', { name: 'review 4' }).click()
    await expect(page).toHaveURL(/\/reviews\/4$/u)
    await page.getByRole('link', { name: 'its page in canopy' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('github.com/acme/web/pull/88')
})

test('a PR the journal does not know says so, and a decision about a PR opens its page', async ({ page }) => {
    await page.goto(`pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/404')}`)
    await expect(page.getByText('canopy has no record of https://github.com/acme/web/pull/404')).toBeVisible()

    await page.goto('ticks/2')
    await settled(page)
    await page.getByTestId('decisions').getByRole('link', { name: 'pr', exact: true }).first().click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
})
