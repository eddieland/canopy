import { expect, test } from '@playwright/test'
import type { Locator } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

/** Where an element is drawn, failing the test when it is not on the page. */
async function box(where: Locator) {
    const found = await where.boundingBox()
    if (found === null) {
        throw new Error('not on the page')
    }
    return found
}

test("the pull requests list has each PR once, and a PR's page its runs, reviews, and decisions", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    await nav.getByRole('link', { name: 'Pull requests' }).click()
    await expect(page).toHaveURL(/\/pull-requests$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Pull requests')
    const rows = page.getByTestId('pull-requests').getByTestId('pull-request')
    // Five, the seven mobile PRs whose pages show the feedback plan's states (canopy/serve/mock/feedback_plans.py), and
    // the nineteen its months before merged (history.py).
    await expect(rows).toHaveCount(31)
    const ours = rows.filter({ hasText: 'acme/web#88' })
    // The PR's own title, as its worker reported it, rather than its ticket's.
    await expect(ours).toContainText('ABC-099: debounce the search box by 250 ms')
    await expect(ours.getByTestId('pull-request-review')).toContainText('review:4')
    // A PR canopy only reviews has no ticket, whoever asked for the review: `none`, and why on hover.
    await expect(rows.filter({ hasText: 'acme/api#12' }).getByTitle('none: canopy only reviews it')).toHaveText('none')
    await expect(rows.filter({ hasText: 'acme/api#12' })).toContainText('Bump the retry budget for flaky upstreams')
    // One the operator asked canopy to review is listed before its first review.
    await expect(rows.filter({ hasText: 'acme/web#95' })).toContainText('requested')
    // Where the operator's review of each PR the loop does not own stands, after its verdict; the loop's own have none.
    const state = (pr: string) => rows.filter({ hasText: pr }).getByTestId('pull-request-review')
    await expect(state('acme/api#14')).toHaveText(/review:6.*draft$/u)
    await expect(state('acme/api#12')).toHaveText(/review:2.*published$/u)
    await expect(state('acme/web#88')).not.toContainText('draft')

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
    await expect(page).toHaveURL(/\/pull-requests\/reviews\/4$/u)
    // The URL changes before the new page replaces the old, which links to its PR too: wait for the review's title.
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
        'review:4 acme/web#88 ABC-099: debounce the search box by 250 ms',
    )
    await page.getByRole('link', { name: 'acme/web#88', exact: true }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(
        'acme/web#88 ABC-099: debounce the search box by 250 ms',
    )
})

test("a PR's page leads with where it stands, and a list it cannot fill takes only its header", async ({ page }) => {
    const open = async (pr: string) => {
        await page.goto(`pull-requests/pr?url=${encodeURIComponent(`https://github.com/${pr.replace('#', '/pull/')}`)}`)
        await expect(page.getByRole('heading', { level: 1 })).toHaveText(new RegExp(`^${pr}( |$)`, 'u'))
    }
    const description = page.locator('main header p')

    // The latest review's verdict is in the header, where the page starts, not first in the Reviews panel.
    await open('acme/web#88')
    await expect(description).toHaveText('review:4 3 findings, 1 major · at its review limit')
    // The loop's own PR is reviewed by `review.agent_prs`, so its page has no review to ask for.
    await expect(page.getByTestId('review-request')).toHaveCount(0)
    const said = await box(description)
    expect(said.y + said.height).toBeLessThan(150)
    // Its title names its repository, so its fields do not.
    await expect(page.locator('main').getByText('repository', { exact: true })).toHaveCount(0)

    // A PR canopy only reviews says so once, in its description; it has no ticket, so no runs, and no Runs panel.
    await open('acme/api#12')
    await expect(description).toContainText('canopy only reviews it')
    await expect(page.locator('main').getByText('canopy only reviews it')).toHaveCount(1)
    await expect(page.getByTestId('pull-request-runs')).toHaveCount(0)
    // Its Pull request panel says where the operator's review of it stands, and links to it. Not followed: opening
    // review 2 marks it seen, a write this journal never takes.
    const yours = page.getByRole('definition').filter({ has: page.getByRole('link', { name: 'review:2' }) })
    await expect(yours).toHaveText('publishedreview:2')
    await expect(yours.getByRole('link', { name: 'review:2' })).toHaveAttribute('href', /\/pull-requests\/reviews\/2$/u)
    // Its request ended with that review: its foot asks for another, as `canopy start URL --review` does.
    await expect(page.getByTestId('review-request').getByRole('button', { name: 'Review again' })).toHaveAttribute(
        'title',
        'canopy start https://github.com/acme/api/pull/12 --review',
    )

    // One canopy has yet to review: its empty lists are their headers alone, each counting 0.
    await open('acme/web#95')
    await expect(description).toHaveText('not reviewed · canopy only reviews it')
    await expect(page.getByTestId('pull-request-runs')).toHaveCount(0)
    const reviews = page.getByTestId('pull-request-reviews')
    const decisions = page.getByTestId('pull-request-decisions')
    await expect(reviews).toHaveText('Reviews0')
    await expect(decisions).toHaveText('Decisions0')
    const [first, last] = [await box(reviews), await box(decisions)]
    expect(last.y + last.height - first.y).toBeLessThan(120)
})

test("a feedback plan waiting on you leads the PR's drafts, its Approve in the first screen", async ({ page }) => {
    // The operator's window: half a 3440×1440 ultrawide, or a 16" MacBook Pro's whole screen (PRODUCT.md).
    await page.setViewportSize({ width: 1720, height: 1440 })
    for (const pr of ['https://github.com/acme/web/pull/88', 'https://github.com/acme/mobile/pull/67']) {
        await page.goto(`pull-requests/pr?url=${encodeURIComponent(pr)}`)
        await settled(page)
        const plan = page.getByTestId('feedback-plan')
        await expect(plan).toHaveAttribute('data-status', /^(?:waiting|stale)$/u)
        // The button, stale or not, whole in view before any scroll.
        await expect(plan.getByRole('button', { name: /^Approve/u })).toBeInViewport({ ratio: 1 })
        const [ahead, drafts] = [await box(plan), await box(page.getByTestId('review-replies'))]
        expect(ahead.y + ahead.height).toBeLessThanOrEqual(drafts.y)
    }
    // On bob's thread the plan proposes a change while run 45's draft waits: the proposal says which answers first.
    const bob = page.getByTestId('review-thread').filter({ hasText: 'Why 250?' })
    await page.goto(`pull-requests/pr?url=${encodeURIComponent('https://github.com/acme/web/pull/88')}`)
    await expect(bob.getByTestId('plan-proposal-ahead')).toHaveText(
        "The plan's resume writes a new reply here; sending this draft first answers ahead of it.",
    )
    await expect(bob.getByTestId('draft').getByRole('button', { name: 'Send', exact: true })).toBeVisible()
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
        ['pull-requests/reviews', 'review-4', 'acme/web#88'],
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
