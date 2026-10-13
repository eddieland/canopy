import { expect, test } from '@playwright/test'

import { NOW, padDecisions, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the root redirects to the attention list', async ({ page }) => {
    await page.goto('')
    await expect(page).toHaveURL(/\/attention$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Attention')
})

test('the tab names the page, after what needs the operator', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const count = await page.getByTestId(/^attention-item-/).count()
    expect(count).toBeGreaterThan(0)
    await expect(page).toHaveTitle(`(${count}) Attention · canopy`)

    const nav = page.getByRole('navigation', { name: 'Main' })
    await nav.getByRole('link', { name: 'Tickets' }).click()
    await page.getByTestId('tickets').getByRole('link', { name: 'ABC-102' }).click()
    await expect(page).toHaveTitle(`(${count}) ABC-102 Export reports as CSV · canopy`)
})

test('the nav moves between pages without reloading the shell', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.evaluate(() => {
        document.querySelector('[data-testid=app-header]')?.setAttribute('data-marker', 'kept')
    })
    const nav = page.getByRole('navigation', { name: 'Main' })

    await nav.getByRole('link', { name: 'Runs' }).click()
    await expect(page).toHaveURL(/\/runs$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await expect(nav.getByRole('link', { name: 'Runs' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Worktrees' }).click()
    await expect(page).toHaveURL(/\/worktrees$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Worktrees')

    await nav.getByRole('link', { name: 'Tickets' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tickets')
    // A ticket the overseer named shows its title beside its key (DESIGN §7).
    await expect(page.getByTestId('ticket-ABC-102')).toContainText('Export reports as CSV')
    await page.getByTestId('tickets').getByRole('link', { name: 'ABC-102' }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-102$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-102 Export reports as CSV')
    await expect(nav.getByRole('link', { name: 'Tickets' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Chores' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Chores')
    await page.getByTestId('chores').getByRole('link', { name: 'chore:deps' }).click()
    await expect(page).toHaveURL(/\/chores\/deps$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('chore:deps')
    await expect(nav.getByRole('link', { name: 'Chores' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Settings' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Settings')
    await expect(page.getByTestId('app-header')).toHaveAttribute('data-marker', 'kept')
})

test('every page header opens with a trail back up to its section', async ({ page }) => {
    const trail = page.getByRole('navigation', { name: 'Breadcrumb' })

    // On a section's list the trail names the section and links nowhere.
    await page.goto('runs')
    await expect(trail).toHaveText('Runs')
    await expect(trail.getByRole('link')).toHaveCount(0)

    // On a run, the section links back to its list; the title is not repeated in the trail.
    await page.goto('runs/39')
    await expect(trail).toHaveText('Runs')
    await trail.getByRole('link', { name: 'Runs' }).click()
    await expect(page).toHaveURL(/\/runs$/)

    // A chore run's trail passes through its chore, by its name as written.
    await page.goto('chores/deps/runs/2')
    await expect(trail.getByRole('link')).toHaveText(['Chores', 'chore:deps'])
    await trail.getByRole('link', { name: 'chore:deps' }).click()
    await expect(page).toHaveURL(/\/chores\/deps$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('chore:deps')
    await trail.getByRole('link', { name: 'Chores' }).click()
    await expect(page).toHaveURL(/\/chores$/)

    // A page in no section names itself.
    await page.goto('search?q=csv')
    await expect(trail).toHaveText('Search')
})

test('each nav item says on hover what its page holds', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    await expect(nav.getByRole('link', { name: 'Runs' })).toHaveAttribute('title', /ended last/)
    for (const link of await nav.getByRole('link').all()) await expect(link).toHaveAttribute('title', /\w/)
})

test('the side rail runs the full height of the page and its nav stays in view when scrolled', async ({ page }) => {
    await page.goto('tickets/ABC-102')
    await settled(page)
    const rail = page.locator('aside')
    const height = await page.evaluate(() => document.documentElement.scrollHeight)
    expect(height).toBeGreaterThan(page.viewportSize()?.height ?? 0)
    // From under the header to the page's foot, not just one viewport.
    expect(await rail.evaluate((el) => el.getBoundingClientRect().bottom + window.scrollY)).toBe(height)

    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    await expect(
        page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Attention' }),
    ).toBeInViewport()
})

test('search params are typed: a known state filters, an unknown one is dropped', async ({ page }) => {
    await page.goto('runs?state=blocked')
    const filters = page.getByRole('navigation', { name: 'Filter by state' })
    await expect(filters.getByRole('link', { name: 'blocked' })).toHaveAttribute('data-selected', 'true')
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'false')
    await expect(page.getByTestId('runs').locator(':scope > li')).toHaveCount(1)

    // The router leaves the URL as typed; what matters is the page never sees the value.
    await page.goto('runs?state=bogus')
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'true')
    await expect(page.getByTestId('runs').locator(':scope > li')).not.toHaveCount(1)
})

test('the runs page lists a ticket once, by its latest run, and opens its earlier runs under it', async ({ page }) => {
    await page.goto('runs')
    await settled(page)
    const rows = page.getByTestId('runs').locator(':scope > li')
    await expect(rows.filter({ has: page.getByRole('link', { name: 'ABC-100', exact: true }) })).toHaveCount(1)
    const ticket = page.getByTestId('run-40')
    await expect(page.getByTestId('run-37')).toHaveCount(0)
    await ticket.getByRole('button', { name: '1 earlier run' }).click()
    await expect(ticket.getByTestId('earlier-runs-ABC-100').getByTestId('run-37')).toContainText('done')
    await ticket.getByRole('button', { name: 'hide earlier runs' }).click()
    await expect(page.getByTestId('run-37')).toHaveCount(0)

    // The filter goes by where each ticket stands: its latest run failed, so the run that finished before it is no
    // reason to list it as done.
    await page.goto('runs?state=done')
    await expect(page.getByTestId('run-40')).toHaveCount(0)
    await page.goto('runs?state=failed')
    await expect(page.getByTestId('run-40')).toBeVisible()
})

test('an unknown route renders the not-found page inside the shell', async ({ page }) => {
    await page.goto('nowhere')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Nothing here')
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
})

test('a ticket the journal does not know offers to start it', async ({ page }) => {
    await page.goto('tickets/ZZZ-9')
    await expect(page.getByText('canopy has no record of it')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start privately' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'jira.example/browse/ZZZ-9' })).toHaveAttribute(
        'href',
        'https://jira.example/browse/ZZZ-9',
    )
})

test("a ticket's page links to it in the tracker, from tracker.ticket_url, under its title", async ({ page }) => {
    await page.goto('tickets/ABC-102')
    // In the page's header, by its title, not down in a panel.
    const links = page.locator('main header').getByRole('navigation', { name: 'Links out' })
    const link = links.getByRole('link', { name: 'jira.example/browse/ABC-102' })
    await expect(link).toHaveAttribute('href', 'https://jira.example/browse/ABC-102')
    await expect(link).toHaveAttribute('target', '_blank')
    await expect(link).toHaveAttribute('rel', 'noreferrer noopener')
})

test("a ticket's page links to its PR under its title, beside the tracker", async ({ page }) => {
    await page.goto('tickets/ABC-103')
    const links = page.locator('main header').getByRole('navigation', { name: 'Links out' })
    await expect(links.getByRole('link')).toHaveText(['jira.example/browse/ABC-103', 'github.com/acme/web/pull/91'])
    await expect(links.getByRole('link', { name: 'github.com/acme/web/pull/91' })).toHaveAttribute(
        'href',
        'https://github.com/acme/web/pull/91',
    )
})

test('the chores page lists each chore as canopy status does, and a chore page what canopy show prints', async ({
    page,
}) => {
    // The fixtures' clock: deps last ran at 08:00 and is due again at 14:00.
    await page.clock.setFixedTime(NOW)
    await page.goto('chores')
    await settled(page)
    await expect(page.getByTestId('chore-build-health')).toContainText('running for 40m')
    const deps = page.getByTestId('chore-deps')
    await expect(deps).toContainText('last ok 4h ago, due in 1h')
    await expect(deps.getByTestId('chore-findings')).toHaveText('1 open finding')
    await expect(deps).toContainText('mon,tue,wed,thu,fri 08:00-18:00 UTC')

    await page.goto('chores/deps')
    await settled(page)
    const finding = page.getByTestId('finding-lodash-advisory')
    await expect(finding).toContainText('lodash 4.17.20 has a prototype pollution advisory')
    await expect(finding.getByRole('link')).toHaveAttribute('href', 'https://github.com/advisories/GHSA-35jh-r3h4-6jhm')
    await expect(page.getByTestId('chore-run-2')).toContainText('1 finding')
    await expect(page.getByTestId('chore-run-2')).toContainText('session ses_chore2')
    await expect(page.getByTestId('chore-notes').getByTestId('message-8')).toContainText("docs site's lockfile")
    await expect(page.getByRole('form', { name: 'Note' })).toBeVisible()
})

test('a chore not defined for this workspace says so', async ({ page }) => {
    await page.goto('chores/nope')
    await expect(page.getByText("no chore 'nope' is defined for this workspace")).toBeVisible()
})

test('the worktrees page shows each pool of the workspace and what holds each slot', async ({ page }) => {
    await page.goto('worktrees')
    await settled(page)
    await expect(page.getByTestId('pool-api')).toContainText('no clone; run `canopy workspace sync`')

    const web = page.getByTestId('pool-web')
    await expect(web.getByTestId('worktrees').locator('li')).toHaveCount(5)
    await expect(web.getByTestId('pool-size')).toHaveText('5 of size 4')
    await expect(web.getByTestId('pool-over')).toContainText('1 slot past the declared size')
    const working = web.getByTestId('worktree-1')
    await expect(working).toHaveAttribute('data-state', 'working')
    await expect(working).toContainText('agent/ABC-101-login')
    // The slots' shared directory is said once, in the header; each slot's path is on its number.
    await expect(web.getByTestId('pool-root')).toHaveText('.treehouse/web-3f9c2a1b/')
    await expect(working.getByText('#1')).toHaveAttribute('title', '.treehouse/web-3f9c2a1b/1/web')
    await expect(working).not.toContainText('.treehouse/web-3f9c2a1b/1/web')
    await expect(working).toContainText('opencode 48211')
    await expect(web.getByTestId('worktree-3')).toHaveAttribute('data-state', 'held')
    await expect(web.getByTestId('worktree-3')).toContainText('detached')
    // An idle slot is its state and number alone.
    await expect(web.getByTestId('worktree-4')).toHaveText('idle#4')
    await expect(web.getByTestId('worktree-5')).toHaveAttribute('data-state', 'dirty')

    // Run 43 holds a slot in two pools; each names it.
    const mobile = page.getByTestId('pool-mobile')
    await expect(mobile.getByTestId('pool-over')).toHaveCount(0)
    await expect(mobile.getByTestId('worktree-1')).toContainText('run:43')
    await expect(web.getByTestId('worktree-2')).toContainText('run:43')

    await working.getByRole('link', { name: 'ABC-101' }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-101$/)
    await page.goBack()

    const reads = page.waitForResponse((r) => r.url().endsWith('/api/worktrees'))
    await page.getByTestId('worktrees-refresh').click()
    expect((await reads).status()).toBe(200)
})

test('a slot with long text keeps it inside its row', async ({ page }) => {
    // Treehouse can find many processes in one slot, and a branch or a note can be any length: each is cut to fit
    // or wrapped, never past the panel's edge.
    await page.route('**/api/worktrees', async (route) => {
        const response = await route.fetch()
        const pools = (await response.json()) as {
            repo: string
            worktrees: { name: string; branch: string | null; note: string | null; processes: object[] }[]
        }[]
        const slot = pools.find((p) => p.repo === 'web')?.worktrees.find((w) => w.name === '1')
        if (slot === undefined) throw new Error('the mock has no slot web#1')
        slot.processes = Array.from({ length: 12 }, (_, i) => ({ pid: 340928 + i, name: `great_gasdbq_${i}` }))
        slot.branch = `agent/ABC-101-${'a-very-long-branch-name-'.repeat(6)}end`
        slot.note = `left ${'/a/path/with/no/spaces'.repeat(12)}`
        await route.fulfill({ response, json: pools })
    })
    await page.goto('worktrees')
    await settled(page)
    const slot = page.getByTestId('pool-web').getByTestId('worktree-1')
    await expect(slot).toContainText('great_gasdbq_0 340928')
    const processes = slot.getByTestId('worktree-processes')
    await expect(processes).toHaveAttribute('title', /great_gasdbq_11 340939/)
    const overflow = await slot.evaluate((li) => {
        const edge = li.getBoundingClientRect().right
        return [...li.querySelectorAll('*')].filter((el) => el.getBoundingClientRect().right > edge + 0.5).length
    })
    expect(overflow).toBe(0)
})

test('the worktrees page reads the pools again every 10 seconds, and only while it is open', async ({ page }) => {
    await page.clock.install()
    let reads = 0
    page.on('request', (r) => {
        if (r.url().endsWith('/api/worktrees')) reads += 1
    })
    await page.goto('worktrees')
    await settled(page)
    expect(reads).toBe(1)

    await page.clock.runFor(9_000)
    expect(reads).toBe(1)
    const next = page.waitForResponse((r) => r.url().endsWith('/api/worktrees'))
    await page.clock.runFor(1_000)
    expect((await next).status()).toBe(200)
    expect(reads).toBe(2)

    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Runs' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await page.clock.runFor(90_000)
    expect(reads).toBe(2)
})

test('the header names the latest tick and how long ago it ended', async ({ page }) => {
    await page.goto('runs')
    await settled(page)
    await expect(page.getByTestId('last-tick')).toHaveText(/^tick 2 · \d+[a-z]+ ago$/)
    await expect(page.getByTestId('last-tick')).toHaveAttribute('title', 'mock tick')
})

test("the header's tick opens its decisions, each about its subject, the overseer's text shown as text", async ({
    page,
}) => {
    await page.goto('runs')
    await settled(page)
    await page.getByTestId('last-tick').getByRole('link', { name: 'tick 2' }).click()
    await expect(page).toHaveURL(/\/ticks\/2$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('tick 2')
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Ticks' })).toHaveAttribute(
        'data-status',
        'active',
    )
    const decisions = page.getByTestId('decisions').locator(':scope > li')
    await expect(decisions).toHaveCount(5)
    await expect(decisions.nth(0)).toContainText('awaiting the operator')
    await expect(decisions.nth(1)).toContainText('refused: running')
    // The rationale's markup arrives as the characters, on one line, as `canopy decisions` prints it.
    await expect(decisions.nth(2)).toContainText('The ticket says <b>keep</b> the old route: left for the worker.')
    await expect(decisions.nth(2).locator('b')).toHaveCount(0)
    await expect(decisions.nth(3)).toContainText('ABC-099 (web)')
    await expect(decisions.nth(4)).toContainText('github.com/acme/api/pull/12')

    await decisions.nth(0).getByRole('link', { name: 'ABC-102' }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-102$/)
})

test('the ticks page lists the latest ticks, and a ticket page why the loop did or did not work it', async ({
    page,
}) => {
    await page.goto('ticks')
    await settled(page)
    await expect(page.getByTestId('ticks').locator(':scope > li')).toHaveCount(2)
    await expect(page.getByTestId('tick-1').getByTestId('tick-decisions')).toHaveText('5 decisions')
    await expect(page.getByTestId('tick-1')).toContainText('dispatched 2, waiting on 1')

    await page.goto('tickets/ABC-102')
    await settled(page)
    const decisions = page.getByTestId('ticket-decisions').getByTestId('decisions').locator(':scope > li')
    await expect(decisions).toHaveCount(2)
    await expect(decisions.nth(0)).toContainText('tick 2')
    await expect(decisions.nth(1)).toContainText('dispatch: implement')
    await decisions.nth(1).getByRole('link', { name: 'tick 1' }).click()
    await expect(page).toHaveURL(/\/ticks\/1$/)
    await expect(page.getByTestId('decisions')).toContainText('chore:deps')
})

test('a long list scrolls inside its panel, so the panels under it stay in reach', async ({ page }) => {
    await padDecisions(page, 'ABC-102', 40)
    await page.goto('tickets/ABC-102')
    await settled(page)
    const region = page.getByRole('region', { name: 'Decisions' })
    await expect(region.locator('li')).toHaveCount(40)
    const { client, scroll } = await region.evaluate((el) => ({ client: el.clientHeight, scroll: el.scrollHeight }))
    expect(scroll).toBeGreaterThan(client)
    // The keyboard scrolls it: it takes focus, and End goes to the last row.
    await region.focus()
    await page.keyboard.press('End')
    await expect.poll(() => region.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
})

test("a run's summary keeps its lines and lists, its first four shown until the toggle opens the rest", async ({
    page,
}) => {
    await page.goto('runs')
    await settled(page)
    const run = page.getByTestId('run-39')
    await expect(run.getByRole('listitem')).toHaveCount(3)
    await expect(run.locator('code').first()).toHaveText('useSearch')
    await expect(run).not.toContainText('ABC-112 owns it')
    await run.getByRole('button', { name: 'show 2 more lines' }).click()
    await expect(run.getByRole('listitem')).toHaveCount(4)
    await expect(run).toContainText('Left the result cache as it was: ABC-112 owns it.')
    await run.getByRole('button', { name: 'show less' }).click()
    await expect(run).not.toContainText('ABC-112 owns it')
})

test('a tick that does not exist, or a path that names none, says so', async ({ page }) => {
    await page.goto('ticks/99')
    await expect(page.getByText('no tick 99')).toBeVisible()
    await page.goto('ticks/two')
    await expect(page.getByText("not a tick: a tick's id is a positive number")).toBeVisible()
})

test('the worktrees page counts every pool, and each pool shows its slots at a glance', async ({ page }) => {
    await page.goto('worktrees')
    await settled(page)
    // The mock: web's two runs, a shell, an idle and a dirty slot; mobile's run 43 slot and an idle one; api has
    // no clone.
    await expect(page.getByTestId('counter-working')).toContainText('3')
    await expect(page.getByTestId('counter-held')).toContainText('1')
    await expect(page.getByTestId('counter-needs')).toContainText('1 dirty · 0 broken · 1 pool unread')
    await expect(page.getByTestId('counter-free')).toContainText('of 7 slots')
    const strip = page.getByTestId('pool-web').getByTestId('slot-strip').locator('[data-state]')
    await expect(strip).toHaveCount(5)
    await expect(strip.nth(4)).toHaveAttribute('data-state', 'dirty')
})
