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
    // The PR's own title, as its worker reported it, rather than its ticket's.
    await expect(ours).toContainText('ABC-099: debounce the search box by 250 ms')
    await expect(ours.getByTestId('pull-request-review')).toContainText('review:4')
    // A PR canopy only reviews has no ticket, whoever asked for the review.
    await expect(rows.filter({ hasText: 'acme/api#12' })).toContainText('none: canopy only reviews it')
    await expect(rows.filter({ hasText: 'acme/api#12' })).toContainText('Bump the retry budget for flaky upstreams')
    // One the operator asked canopy to review is listed before its first review.
    await expect(rows.filter({ hasText: 'acme/web#95' })).toContainText('requested')

    await ours.getByRole('link', { name: 'acme/web#88', exact: true }).click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
    // Its title leads with its own, after the PR's name, and its description is its state.
    const heading = page.getByRole('heading', { level: 1 })
    await expect(heading).toHaveText('acme/web#88 ABC-099: debounce the search box by 250 ms')
    await expect(page.locator('main header p')).toHaveText('review:4 3 findings, 1 major · at its review limit')
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
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
        'acme/web#88 ABC-099: debounce the search box by 250 ms',
    )
})

test("a PR's page leads with where it stands, high on the page", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.goto(`pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/88')}`)
    await settled(page)
    const description = page.locator('main header p')
    await expect(description).toHaveText('review:4 3 findings, 1 major · at its review limit')
    const box = await description.boundingBox()
    expect(box).not.toBeNull()
    // The verdict starts above y=150, under the title rather than a panel down the page.
    expect(box?.y ?? Infinity).toBeLessThan(150)
    // Its repository is its title's, not a field too.
    const terms = page.getByTestId('pull-request-fields').getByRole('term')
    await expect(terms.first()).toHaveText('ticket')
    await expect(terms.filter({ hasText: /^repository$/u })).toHaveCount(0)
})

test('a PR canopy only reviews says so once, has no runs, and its empty lists collapse to their headers', async ({
    page,
}) => {
    for (const [pr, state] of [
        ['https://github.com/acme/web/pull/95', 'not reviewed · canopy only reviews it'],
        ['https://github.com/acme/api/pull/12', 'review:2 clean · canopy only reviews it'],
    ] as const) {
        await page.goto(`pull-requests/pr?url=${encodeURIComponent(pr)}`)
        await settled(page)
        await expect(page.locator('main header p')).toHaveText(state)
        await expect(page.locator('main').getByText('canopy only reviews it')).toHaveCount(1)
        await expect(page.getByTestId('pull-request-fields').getByRole('definition').first()).toHaveText('none')
        // Runs are a ticket's: a PR with none can never have one, so it has no Runs panel, and nothing names a ticket.
        await expect(page.getByTestId('pull-request-reviews')).toBeVisible()
        await expect(page.getByTestId('pull-request-runs')).toHaveCount(0)
        await expect(page.locator('main')).not.toContainText("its ticket's")
    }

    // acme/web#95 has no reviews and no decisions: each is its header and its count, nothing under it.
    const reviews = page.getByTestId('pull-request-reviews')
    const decisions = page.getByTestId('pull-request-decisions')
    await page.goto(`pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/95')}`)
    await settled(page)
    await expect(reviews).toHaveText('Reviews0')
    await expect(decisions).toHaveText('Decisions0')
    await expect(reviews.getByTestId('list-count')).toHaveAttribute(
        'title',
        'no reviews yet: canopy has not reviewed it',
    )
    // The panels under the identity panel, from the first one's top to the last one's foot, the gap between included.
    const first = await reviews.boundingBox()
    const last = await decisions.boundingBox()
    expect(first).not.toBeNull()
    expect(last).not.toBeNull()
    const below = (last?.y ?? Infinity) + (last?.height ?? 0) - (first?.y ?? 0)
    expect(below).toBeLessThan(120)
})

test('a PR the journal does not know says so, and a decision about a PR opens its page', async ({ page }) => {
    await page.goto(`pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/404')}`)
    await expect(page.getByText('canopy has no record of https://github.com/acme/web/pull/404')).toBeVisible()

    await page.goto('ticks/2')
    await settled(page)
    await page.getByTestId('decisions').getByRole('link', { name: 'acme/api#12', exact: true }).first().click()
    await expect(page).toHaveURL(/\/pull-requests\/pr\?url=/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
        'acme/api#12 Bump the retry budget for flaky upstreams',
    )
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
