import { expect, test } from '@playwright/test'

import { NOW, padDecisions, settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the root redirects to the attention list', async ({ page }) => {
    await page.goto('')
    await expect(page).toHaveURL(/\/attention$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Attention')
})

test('the tab names the page, after what blocks on the operator', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    // The mock's six items less the PR that waits on a reviewer and the chore's finding, which block nothing.
    await expect(page.getByTestId(/^attention-item-/u)).toHaveCount(6)
    const count = 4
    await expect(page).toHaveTitle(`(${count}) Attention · canopy`)

    const nav = page.getByRole('navigation', { name: 'Main' })
    await nav.getByRole('link', { name: 'Tickets' }).click()
    await page.getByTestId('tickets').getByRole('link', { name: 'ABC-102', exact: true }).click()
    await expect(page).toHaveTitle(`(${count}) ABC-102 Export reports as CSV · canopy`)
})

test('the nav moves between pages without reloading the shell', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    await page.evaluate(() => {
        const header = document.querySelector<HTMLElement>('[data-testid=app-header]')
        if (header) {
            header.dataset.marker = 'kept'
        }
    })
    const nav = page.getByRole('navigation', { name: 'Main' })

    await nav.getByRole('link', { name: 'Runs' }).click()
    await expect(page).toHaveURL(/\/runs$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Runs')
    await expect(nav.getByRole('link', { name: 'Runs' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Worktrees' }).click()
    await expect(page).toHaveURL(/\/worktrees$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Worktrees')

    await nav.getByRole('link', { name: 'Tickets' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tickets')
    // A ticket the overseer named shows its title beside its key (DESIGN §7).
    await expect(page.getByTestId('ticket-ABC-102')).toContainText('Export reports as CSV')
    await page.getByTestId('tickets').getByRole('link', { name: 'ABC-102', exact: true }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-102$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-102 Export reports as CSV')
    await expect(nav.getByRole('link', { name: 'Tickets' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Chores' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Chores')
    await page.getByTestId('chores').getByRole('link', { name: 'chore:deps' }).click()
    await expect(page).toHaveURL(/\/chores\/deps$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('chore:deps')
    await expect(nav.getByRole('link', { name: 'Chores' })).toHaveAttribute('data-status', 'active')

    await nav.getByRole('link', { name: 'Memory' }).click()
    await expect(page).toHaveURL(/\/memory$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Memory')
    await expect(nav.getByRole('link', { name: 'Memory' })).toHaveAttribute('data-status', 'active')

    await page.getByTestId('rail-settings').click()
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
    await expect(page).toHaveURL(/\/runs$/u)

    // A chore run's trail passes through its chore, by its name as written.
    await page.goto('chores/deps/runs/2')
    await expect(trail.getByRole('link')).toHaveText(['Chores', 'chore:deps'])
    await trail.getByRole('link', { name: 'chore:deps' }).click()
    await expect(page).toHaveURL(/\/chores\/deps$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('chore:deps')
    await trail.getByRole('link', { name: 'Chores' }).click()
    await expect(page).toHaveURL(/\/chores$/u)

    // A page in no section names itself.
    await page.goto('search?q=csv')
    await expect(trail).toHaveText('Search')
})

test('each nav item says on hover what its page holds', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    await expect(nav.getByRole('link', { name: 'Runs' })).toHaveAttribute('title', /ended last/u)
    for (const link of await nav.getByRole('link').all()) {
        await expect(link).toHaveAttribute('title', /\w/u)
    }
})

test('the side rail runs the full height of the page and its nav stays in view when scrolled', async ({ page }) => {
    await page.goto('tickets/ABC-102')
    await settled(page)
    const rail = page.locator('aside')
    const scroller = page.locator('[data-scroll-restoration-id=page]')
    const height = await scroller.evaluate((el) => el.scrollHeight)
    expect(height).toBeGreaterThan(await scroller.evaluate((el) => el.clientHeight))
    // From under the header to the page's foot, not just one window.
    expect(await rail.evaluate((el) => el.getBoundingClientRect().height)).toBe(height)

    await scroller.evaluate((el) => el.scrollTo(0, el.scrollHeight))
    await expect(
        page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Attention' }),
    ).toBeInViewport()
})

test('the header spans the window and only what is under it scrolls', async ({ page }) => {
    await page.goto('tickets/ABC-102')
    await settled(page)
    const header = page.getByTestId('app-header')
    const scroller = page.locator('[data-scroll-restoration-id=page]')
    // The window never scrolls, so no gutter of its own cuts the header short.
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(page.viewportSize()?.height)
    expect(await header.evaluate((el) => el.getBoundingClientRect().right)).toBe(page.viewportSize()?.width)

    await scroller.evaluate((el) => el.scrollTo(0, el.scrollHeight))
    await expect(header).toBeInViewport({ ratio: 1 })
    // A new page starts at its top, and going back returns to where the last one was.
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Runs' }).click()
    await expect(page).toHaveURL(/\/runs$/u)
    await expect.poll(() => scroller.evaluate((el) => el.scrollTop)).toBe(0)
    await page.goBack()
    await expect(page).toHaveURL(/\/tickets\/ABC-102$/u)
    await expect.poll(() => scroller.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
})

test('the keys scroll the page from a fresh load', async ({ page }) => {
    await page.goto('tickets/ABC-102')
    await settled(page)
    await page.keyboard.press('PageDown')
    await expect
        .poll(() => page.locator('[data-scroll-restoration-id=page]').evaluate((el) => el.scrollTop))
        .toBeGreaterThan(0)
})

test('search params are typed: a known state filters, an unknown one is dropped', async ({ page }) => {
    await page.goto('runs?state=blocked')
    const filters = page.getByRole('navigation', { name: 'Filter by state' })
    await expect(filters.getByRole('link', { name: 'waiting on you' })).toHaveAttribute('data-selected', 'true')
    await expect(filters.getByRole('link', { name: 'all' })).toHaveAttribute('data-selected', 'false')
    await expect(page.getByTestId('runs').locator(':scope > li')).toHaveCount(1)
    // The panel is named for its noun and counts what it lists, as every Runs panel does.
    await expect(page.getByTestId('runs-count')).toHaveText('1')

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
    await ticket.getByRole('button', { name: 'Show 1 earlier run' }).click()
    const earlier = ticket.getByTestId('earlier-runs-ABC-100')
    await expect(earlier.getByTestId('run-37')).toContainText('done')
    // Radix's Collapsible ties the toggle to what it opened, for assistive technology.
    const hide = ticket.getByRole('button', { name: 'Hide 1 earlier run' })
    await expect(hide).toHaveAttribute('aria-expanded', 'true')
    await expect(hide).toHaveAttribute('aria-controls', (await earlier.getAttribute('id')) ?? 'no id')
    await hide.click()
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
    // One sentence on one line, its link beside its words rather than a row of its own.
    const sentence = await page.getByText('no page at this address:').boundingBox()
    const link = await page.getByRole('link', { name: 'go to the attention list' }).boundingBox()
    expect(sentence?.height).toBeLessThan(2 * (link?.height ?? 0))
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

test("a public ticket's actions say how to stop its worker where Stop would be", async ({ page }) => {
    await page.goto('tickets/ABC-101')
    await settled(page)
    const actions = page.getByTestId('ticket-actions')
    await expect(actions.getByRole('button', { name: 'Start privately' })).toBeVisible()
    await expect(actions.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
    await expect(actions.getByTestId('public-stop')).toHaveText(
        'Public: remove its queue label to stop it, or start it privately.',
    )
    // Whether it is public is its title's chip, and said nowhere else on the page.
    await expect(page.getByText('public', { exact: true })).toHaveCount(1)
    // Every button in the foot is one size.
    const buttons = actions.getByRole('button')
    const heights = await buttons.evaluateAll((all) => all.map((b) => b.getBoundingClientRect().height))
    expect(new Set(heights).size).toBe(1)
})

test("a ticket's page links to its PR and its branch under its title, beside the tracker", async ({ page }) => {
    await page.goto('tickets/ABC-103')
    const links = page.locator('main header').getByRole('navigation', { name: 'Links out' })
    const branch = 'github.com/acme/web/tree/agent/ABC-103-billing-v2'
    await expect(links.getByRole('link')).toHaveText(['jira.example/browse/ABC-103', 'acme/web#91', branch])
    await expect(links.getByRole('link', { name: 'acme/web#91' })).toHaveAttribute(
        'href',
        'https://github.com/acme/web/pull/91',
    )
    // From the web repository's branch_url in the map.
    await expect(links.getByRole('link', { name: branch })).toHaveAttribute('href', `https://${branch}`)
})

test("a ticket's page puts its reply before its runs and decisions in a narrow window", async ({ page }) => {
    await page.setViewportSize({ width: 820, height: 900 })
    await page.goto('tickets/ABC-102')
    await settled(page)
    const box = async (testId: string) => {
        const found = await page.getByTestId(testId).boundingBox()
        if (found === null) {
            throw new Error(`${testId} is not on the page`)
        }
        return found
    }
    const actions = await box('ticket-actions')
    const conversation = await box('ticket-conversation')
    const reply = await page
        .getByTestId('ticket-conversation')
        .getByRole('textbox', { name: /^Reply/u })
        .boundingBox()
    const runs = await box('ticket-runs')
    const decisions = await box('ticket-decisions')
    // What it is and its actions, then the conversation and the reply, then the lists that support them.
    expect(actions.y).toBeLessThan(conversation.y)
    expect(reply).not.toBeNull()
    expect((reply?.y ?? Infinity) + (reply?.height ?? 0)).toBeLessThan(runs.y)
    expect(runs.y).toBeLessThan(decisions.y)

    // Wide, the conversation sits beside the rest, its top level with the Work panel's, above the actions in its foot.
    await page.setViewportSize({ width: 1600, height: 900 })
    const wide = await box('ticket-conversation')
    expect(wide.x).toBeGreaterThan((await box('ticket-runs')).x)
    expect(wide.y).toBeLessThan((await box('ticket-actions')).y)
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
    await expect(deps.getByTestId('chore-spend')).toHaveText('$0.47 24h · $0.47 30d')
    await expect(page.getByTestId('chore-build-health').getByTestId('chore-spend')).toHaveText('$0.38 24h · $0.38 30d')

    await page.goto('chores/deps')
    await settled(page)
    // Whether it is healthy is its description: where it stands, as its line in the list says it, then its findings.
    await expect(page.locator('main header p')).toHaveText('last ok 4h ago, due in 1h · 1 open finding')
    // Its schedule names what its config sets, and leaves out a default.
    await expect(page.getByTestId('chore-schedule').getByRole('definition')).toHaveText([
        'every 360 minutes',
        'mon,tue,wed,thu,fri 08:00-18:00 UTC',
        'Skip it when nothing has merged to main since the last run.',
    ])
    await expect(page.getByTestId('chore-spend-24h').getByRole('cell')).toHaveText([
        '2',
        '$0.47',
        '$0.23',
        '$0.26',
        '$0.26',
    ])
    const finding = page.getByTestId('finding-lodash-advisory')
    await expect(finding).toContainText('lodash 4.17.20 has a prototype pollution advisory')
    await expect(finding.getByRole('link')).toHaveAttribute('href', 'https://github.com/advisories/GHSA-35jh-r3h4-6jhm')
    await expect(page.getByTestId('chore-run-2')).toContainText('1 finding')
    await expect(page.getByTestId('chore-run-2')).toContainText('session ses_chore2')
    await expect(page.getByTestId('chore-notes').getByTestId('message-8')).toContainText("docs site's lockfile")
    // Nothing waits on a note, so its form waits to be asked for.
    await expect(page.getByRole('form', { name: 'Note' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Show a note for its next runs' }).click()
    await expect(page.getByRole('form', { name: 'Note' })).toBeVisible()

    // While a run works, the description still says how the last one ended; a chore with no window or condition
    // shows how often it may start alone.
    await page.goto('chores/build-health')
    await settled(page)
    await expect(page.locator('main header p')).toHaveText('running for 40m · last ok 2h ago')
    await expect(page.getByTestId('chore-schedule').getByRole('term')).toHaveText(['at most'])
    await expect(page.getByTestId('chore-notes').getByRole('textbox')).toHaveCount(0)
})

test("a chore's page puts its open findings and runs first, and wide, in the wide column", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.goto('chores/deps')
    await settled(page)
    const box = async (testId: string) => {
        const found = await page.getByTestId(testId).boundingBox()
        if (found === null) {
            throw new Error(`${testId} is not on the page`)
        }
        return found
    }
    // What it is, then where the operator acts, its open findings, and the runs that found them, then the rest.
    const findings = await box('chore-findings')
    expect(findings.y).toBeLessThan(480)
    expect((await box('chore-schedule')).y).toBeLessThan(findings.y)
    expect(findings.y).toBeLessThan((await box('chore-runs')).y)
    expect((await box('chore-runs')).y).toBeLessThan((await box('chore-notes')).y)
    expect((await box('chore-notes')).y).toBeLessThan((await box('chore-spend')).y)

    // Wide, findings and runs fill the wide column, beside the schedule, notes, and spend.
    await page.setViewportSize({ width: 1600, height: 900 })
    const schedule = await box('chore-schedule')
    expect((await box('chore-findings')).x).toBeGreaterThan(schedule.x + schedule.width)
    expect((await box('chore-runs')).x).toBeGreaterThan(schedule.x + schedule.width)
    expect((await box('chore-notes')).x).toBe(schedule.x)
    expect((await box('chore-spend')).x).toBe(schedule.x)
})

test('a chore not defined for this workspace says so', async ({ page }) => {
    await page.goto('chores/nope')
    await expect(page.getByText("no chore 'nope' is defined for this workspace")).toBeVisible()
})

test('the worktrees page shows each pool of the workspace and what holds each slot', async ({ page }) => {
    await page.goto('worktrees')
    await settled(page)
    // Its command set as code, as an attention item's detail sets it.
    await expect(page.getByTestId('pool-api')).toContainText('no clone; run canopy workspace sync')
    await expect(page.getByTestId('pool-api').getByRole('code')).toHaveText('canopy workspace sync')

    const web = page.getByTestId('pool-web')
    await expect(web.getByTestId('worktrees').locator('li')).toHaveCount(5)
    await expect(web.getByTestId('pool-size')).toHaveText('5 of size 4')
    await expect(web.getByTestId('pool-over')).toContainText('1 slot past the declared size')
    const working = web.getByTestId('worktree-1')
    await expect(working).toHaveAttribute('data-state', 'working')
    await expect(working).toContainText('agent/ABC-101-login')
    // The web repository has a branch_url in the map, so the branch links to its page there.
    await expect(working.getByRole('link', { name: 'agent/ABC-101-login' })).toHaveAttribute(
        'href',
        'https://github.com/acme/web/tree/agent/ABC-101-login',
    )
    // The slots' shared directory is said once, in the header; each slot's path is on its number.
    await expect(web.getByTestId('pool-root')).toHaveText('.treehouse/web-3f9c2a1b/')
    await expect(working.getByText('#1')).toHaveAttribute('title', '.treehouse/web-3f9c2a1b/1/web')
    await expect(working).not.toContainText('.treehouse/web-3f9c2a1b/1/web')
    await expect(working).toContainText('opencode 48211')
    await expect(web.getByTestId('worktree-3')).toHaveAttribute('data-state', 'held')
    await expect(web.getByTestId('worktree-3')).toContainText('detached')
    // An idle slot is its state and number alone.
    await expect(web.getByTestId('worktree-4')).toHaveText('idle#4')
    // A dirty slot says what it blocks and what clears it.
    const dirty = web.getByTestId('worktree-5')
    await expect(dirty).toHaveAttribute('data-state', 'dirty')
    await expect(dirty).toContainText('never reused while it has changes, and counts as busy')
    await expect(dirty).toContainText('discard them in the slot')

    // Run 43 holds a slot in two pools; each names it.
    const mobile = page.getByTestId('pool-mobile')
    await expect(mobile.getByTestId('pool-over')).toHaveCount(0)
    await expect(mobile.getByTestId('worktree-1')).toContainText('run:43')
    await expect(web.getByTestId('worktree-2')).toContainText('run:43')

    await working.getByRole('link', { name: 'ABC-101', exact: true }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-101$/u)
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
        if (slot === undefined) {
            throw new Error('the mock has no slot web#1')
        }
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
    await expect(processes).toHaveAttribute('title', /great_gasdbq_11 340939/u)
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
        if (r.url().endsWith('/api/worktrees')) {
            reads += 1
        }
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
    await expect(page.getByTestId('last-tick')).toHaveText(/^tick:2 · \d+[a-z]+ ago$/u)
    await expect(page.getByTestId('last-tick')).toHaveAttribute('title', 'mock tick')
})

test("the header's tick opens its decisions, each about its subject, the overseer's text shown as text", async ({
    page,
}) => {
    await page.goto('runs')
    await settled(page)
    await page.getByTestId('last-tick').getByRole('link', { name: 'tick:2' }).click()
    await expect(page).toHaveURL(/\/ticks\/2$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('tick:2')
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
    await expect(decisions.nth(4)).toContainText('acme/api#12')

    await decisions.nth(0).getByRole('link', { name: 'ABC-102', exact: true }).click()
    await expect(page).toHaveURL(/\/tickets\/ABC-102$/u)
})

test('the ticks page lists the latest ticks, and a ticket page why the loop did or did not work it', async ({
    page,
}) => {
    await page.goto('ticks')
    await settled(page)
    await expect(page.getByTestId('ticks').locator(':scope > li')).toHaveCount(2)
    await expect(page.getByTestId('tick-1').getByTestId('tick-decisions')).toHaveText('5 decisions')
    // Its overseer's tokens beside its cost, and the most one model call was sent.
    await expect(page.getByTestId('tick-1').getByTestId('tick-tokens')).toHaveText('12.9k tokens')
    await expect(page.getByTestId('tick-1').getByTestId('tick-peak')).toHaveText('16.8k peak')
    await expect(page.getByTestId('tick-1')).toContainText('dispatched 2, waiting on 1')

    await page.goto('tickets/ABC-102')
    await settled(page)
    const decisions = page.getByTestId('ticket-decisions').getByTestId('decisions').locator(':scope > li')
    await expect(decisions).toHaveCount(2)
    await expect(decisions.nth(0)).toContainText('tick:2')
    await expect(decisions.nth(1)).toContainText('dispatch: implement')
    await decisions.nth(1).getByRole('link', { name: 'tick:1' }).click()
    await expect(page).toHaveURL(/\/ticks\/1$/u)
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
    // ABC-099's page, since the runs page shows its latest run, 45.
    await page.goto('tickets/ABC-099')
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
    // The shell's slot has no lease: a process holds it.
    await expect(page.getByTestId('counter-held')).toContainText('1 in use')
    // The dirty slot and the unread pool both count, and the line names only what there is: its label, the value 2,
    // then the line.
    await expect(page.getByTestId('counter-needs')).toHaveText('Needs a look21 dirty · 1 pool unread')
    await expect(page.getByTestId('counter-free')).toContainText('of 7 slots')
    // The description is the pools' state: how many, and how fresh the read is.
    await expect(page.getByText(/^3 pools · 7 slots · read \d+[smhd] ago$/u)).toBeVisible()
    const strip = page.getByTestId('pool-web').getByTestId('slot-strip').locator('[data-state]')
    await expect(strip).toHaveCount(5)
    await expect(strip.nth(4)).toHaveAttribute('data-state', 'dirty')
})
