import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the nav opens Reviews under Reports, the week's first review timed on GitHub's clock", async ({ page }) => {
    await page.goto('reports')
    await settled(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Reviews', exact: true }).click()
    await expect(page).toHaveURL(/\/reports\/reviews$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Reviews')
    // The mock's week: PR 88 asked alice for a review at 10:45, and hers came at 11:12 (canopy/serve/mock/).
    await expect(page.locator('main header p')).toHaveText('2 reviews on 1 PR · median first review 27m over 7 days')
    await expect(page.getByTestId('reviews-window-7')).toHaveAttribute('data-state', 'on')
    await expect(page.getByTestId('reviews-chart').getByTestId('reviews-peak')).toHaveText('1')
    const reviewers = page.getByTestId('reviews-reviewer-table').getByTestId('reviews-reviewer')
    await expect(reviewers).toHaveCount(3)
    await expect(page.getByTestId('reviews-pull-request-table').getByTestId('reviews-pull-request')).toHaveCount(1)
    await expect(page.getByTestId('reviews-canopy-trust')).toContainText('canopy:review is in trust.trusted_reviewers')
})

test("the month counts the PRs read before GitHub's times apart, and the planner's estimates", async ({ page }) => {
    await page.goto('reports/reviews')
    await settled(page)
    await page.getByTestId('reviews-window-30').click()
    await expect(page).toHaveURL(/\/reports\/reviews\?days=30$/u)
    await expect(page.locator('main header p')).toHaveText(
        '10 reviews on 7 PRs · median first review 18.3h over 30 days',
    )
    // What the median leaves out is in its tile's tip, so the chart's panel holds the chart alone.
    await page.getByTestId('reviews-tiles').getByText('median first review').hover()
    await expect(page.getByRole('tooltip')).toContainText(
        '2 reviewed PRs had no ready time from GitHub and are left out.',
    )
    // alice approved one PR of the month's, web#78, approved before any feedback round read it.
    const alice = page.getByTestId('reviews-reviewer').filter({ hasText: 'alice' })
    await expect(alice.getByRole('cell').nth(2)).toHaveText('1')
    const approved = page.getByTestId('reviews-pull-request').filter({ hasText: 'web#78' })
    await expect(approved.getByRole('cell').nth(4)).toHaveText('1')
    await expect(approved.getByRole('cell').nth(7)).toHaveText('0')
    // PR 61's round is the month's one answered: dana's review, the plan, its approval, the resume, and its push's
    // checks, 1.65 hours end to end, each part in the tile's tip.
    await expect(page.getByTestId('reviews-turnaround')).toHaveText('1.6h')
    await page.getByTestId('reviews-tiles').getByText('median turnaround').hover()
    await expect(page.getByRole('tooltip')).toContainText(
        "over 1 answered round. Each part's own median: review to plan 56m, plan to approval 12m, " +
            'approval to resume 5m, resume to push 26m',
    )
    await expect(page.getByTestId('reviews-round-5').getByTestId('reviews-round-turnaround')).toHaveText('1.6h')
    await expect(page.getByTestId('reviews-efforts').getByTestId('reviews-effort')).toHaveCount(3)
    await expect(page.getByTestId('reviews-round-4')).toContainText('the planner')
    await page.getByTestId('reviews-round-4').getByRole('link', { name: 'run:52' }).click()
    await expect(page).toHaveURL(/\/runs\/52$/u)
})
