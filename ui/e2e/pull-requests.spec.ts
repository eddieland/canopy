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
    await expect(rows).toHaveCount(4)
    const ours = rows.filter({ hasText: 'acme/web#88' })
    await expect(ours).toContainText('Debounce search input')
    await expect(ours.getByTestId('pull-request-review')).toContainText('review:4')
    // A PR canopy only reviews has no ticket, whoever asked for the review.
    await expect(rows.filter({ hasText: 'acme/api#12' })).toContainText('none: canopy only reviews it')
    // One the operator asked canopy to review is listed before its first review.
    await expect(rows.filter({ hasText: 'acme/web#95' })).toContainText('requested')

    await ours.getByRole('link', { name: 'acme/web#88', exact: true }).click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
    // Its title leads with its ticket's, after the PR's name, and its description is its state.
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('acme/web#88 Debounce search input')
    await expect(page.locator('main header p')).toHaveText('ABC-099 · 2 reviews')
    await expect(nav.getByRole('link', { name: 'Pull requests' })).toHaveAttribute('data-status', 'active')
    // The run that opened it, its two reviews, and what the loop decided about it.
    await expect(page.getByTestId('pull-request-runs').getByRole('link', { name: 'run:39' })).toBeVisible()
    await expect(page.getByTestId('pull-request-reviews').getByRole('link', { name: /^review:/u })).toHaveCount(2)
    await expect(page.getByTestId('pull-request-decisions')).toContainText('needs reviewer')
    // Its title names it, and nothing else on its page does: not its runs, its decisions, or its review limit.
    await expect(page.locator('main').getByText('acme/web#88')).toHaveCount(1)

    // The link out under the title says where it goes, rather than naming the PR again.
    const out = page.locator('main header').getByRole('navigation', { name: 'Links out' }).getByRole('link')
    await expect(out).toHaveText('on GitHub')
    await expect(out).toHaveAttribute('href', 'https://github.com/acme/web/pull/88')

    // A review opens its findings on its diff, and leads back to its PR's page.
    await page.getByTestId('pull-request-review-4').getByRole('link', { name: 'review:4' }).click()
    await expect(page).toHaveURL(/\/reviews\/4$/u)
    // The URL changes before the new page replaces the old, which links to its PR too: wait for the review's title.
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('review:4 acme/web#88 Debounce search input')
    await page.getByRole('link', { name: 'acme/web#88', exact: true }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('acme/web#88 Debounce search input')
})

test('a PR the journal does not know says so, and a decision about a PR opens its page', async ({ page }) => {
    await page.goto(`pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/404')}`)
    await expect(page.getByText('canopy has no record of https://github.com/acme/web/pull/404')).toBeVisible()

    await page.goto('ticks/2')
    await settled(page)
    await page.getByTestId('decisions').getByRole('link', { name: 'acme/api#12', exact: true }).first().click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('acme/api#12')
})

test('a PR named on a run, a review, a decision, or a ticket opens its page in one click, and its icon GitHub', async ({
    page,
}) => {
    const where: [string, string, string][] = [
        ['runs/39', 'main', 'acme/web#88'],
        ['reviews', 'review-4', 'acme/web#88'],
        ['ticks/2', 'decisions', 'acme/api#12'],
        ['tickets/ABC-103', 'main', 'acme/web#91'],
    ]
    for (const [path, within, name] of where) {
        await page.goto(path)
        await settled(page)
        const scope = within === 'main' ? page.locator('main') : page.getByTestId(within)
        const out = scope.getByRole('link', { name: `${name} on GitHub`, exact: true }).first()
        await expect(out).toHaveAttribute('href', `https://github.com/${name.replace('#', '/pull/')}`)
        await expect(out).toHaveAttribute('target', '_blank')
        // The name links in: on a ticket's page, its header's button of the same name links out.
        const inward = page.locator('a[href*="pull-requests/pr"]')
        await scope.getByRole('link', { name, exact: true }).and(inward).first().click()
        await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
        // The PR's name leads its title, before its ticket's title when it has one.
        await expect(page.getByRole('heading', { level: 1 })).toHaveText(new RegExp(`^${name}( |$)`, 'u'))
    }
})
