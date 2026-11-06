import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// An epic's page (ui/DESIGN.md, "An epic"), over the mock journal's epics: epic 1 approved, with members; epic 2
// proposed, after a reply; epic 3 just submitted, its plan run at work; epic 4 stopped before any plan run started.

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

/** The board's entries that are lit now, by id. */
function litEntries(page: Page): Promise<string[]> {
    return page
        .getByTestId(/^entry-B\d+$/u)
        .evaluateAll((rows) =>
            rows
                .filter((row) => row instanceof HTMLElement && row.dataset.lit !== undefined)
                .map((row) => (row as HTMLElement).dataset.testid ?? ''),
        )
}

/** The board's entries lit now, and whether each place `id` shows is lit, read at one instant. */
function lit(page: Page, id: string): Promise<{ entries: string[]; id: boolean[] }> {
    return page.evaluate((name) => {
        const entries = [...document.querySelectorAll<HTMLElement>('[data-testid^="entry-B"]')]
            .filter((row) => row.dataset.lit !== undefined)
            .map((row) => row.dataset.testid ?? '')
        const ids = [...document.querySelectorAll<HTMLElement>('main span')]
            .filter((span) => span.textContent === name && span.children.length === 0)
            .map((span) => span.dataset.lit !== undefined)
        return { entries, id: ids }
    }, id)
}

test("the list opens an epic's page, which leads with its breakdown beside its members", async ({ page }) => {
    await page.goto('epics')
    await settled(page)
    await page.getByTestId('epic-1').getByRole('link', { name: 'epic:1', exact: true }).click()
    await expect(page).toHaveURL(/\/epics\/1$/u)
    await settled(page)
    const b1 = page.getByTestId('entry-B1')
    await expect(b1.getByRole('link', { name: 'ABC-103', exact: true })).toHaveAttribute('href', /\/tickets\/ABC-103$/u)
    await expect(page.getByTestId('entry-B3')).toContainText('none yet')
    await expect(
        page.getByTestId('members-of-no-entry').getByRole('link', { name: 'ABC-100', exact: true }),
    ).toBeVisible()
})

test('pointing at a requirement lights the entries that cover it, and the id wherever it shows', async ({ page }) => {
    await page.goto('epics/1')
    await settled(page)
    // Each member's link out comes with the server's meta, after the page, and widens the board as it comes: hovered
    // before it, the board could move from under the mouse.
    await expect(page.getByRole('link', { name: 'ABC-103 in the tracker' })).toBeVisible()
    const outline = page.getByTestId('epic-outline')
    const r1 = outline.getByText('R1', { exact: true })
    await r1.hover()
    // The entries and the id are read at one instant, so they are told lit by the same pointing.
    await expect.poll(() => lit(page, 'R1')).toEqual({ entries: ['entry-B1', 'entry-B3'], id: [true, true, true] })
    // Lighting only adds: every entry still reads as it did, its members and none yet among them.
    await expect(page.getByTestId('entry-B2').getByRole('link', { name: 'ABC-104', exact: true })).toBeVisible()
    await expect(page.getByTestId('entry-B4')).toContainText('none yet')
    await page.getByRole('heading', { level: 1 }).hover()
    await expect.poll(() => litEntries(page)).toEqual([])
})

test('a contract lit from the keyboard lights who provides it and who uses it', async ({ page }) => {
    await page.goto('epics/1')
    await settled(page)
    await page.getByTestId('entry-B2').getByText('C1', { exact: true }).focus()
    await expect.poll(() => litEntries(page)).toEqual(['entry-B1', 'entry-B2', 'entry-B3'])
    await expect(page.getByTestId('epic-outline').getByText('C1', { exact: true })).toHaveAttribute('data-lit', '')
    // Its tip says its words, as the planner wrote them.
    await expect(page.getByRole('tooltip')).toContainText('BillingClient')
    await page.keyboard.press('Tab')
    await expect(page.getByTestId('epic-outline').getByText('C1', { exact: true })).not.toHaveAttribute('data-lit')
})

test("a proposed epic's board is marked proposed, and a planning one names its plan run", async ({ page }) => {
    await page.goto('epics/2')
    await settled(page)
    await expect(page.getByTestId('epic-board').getByText('proposed', { exact: true })).toBeVisible()
    await page.goto('epics/3')
    await settled(page)
    await expect(page.getByTestId('plan-run-working')).toContainText('epic:3#4 is writing its plan')
})

test("a proposed epic's mark opens its plan, read only, and Back returns to the board", async ({ page }) => {
    await page.goto('epics/2')
    await settled(page)
    await page.getByRole('link', { name: 'Open the proposed plan' }).click()
    await expect(page).toHaveURL(/\/epics\/2\/plan$/u)
    await settled(page)
    // Exactly: while the plan waits on you, its foot's note on the whole plan is a textbox too.
    const plan = page.getByRole('textbox', { name: 'Plan', exact: true })
    await expect(plan).toContainText('the copy goes when its customer does')
    await expect(plan).toHaveAttribute('contenteditable', 'false')
    await expect(page.getByRole('heading', { name: 'Comments' })).toHaveCount(0)
    // What changed since the plan the reply replaced is marked as the page opens; the earlier plan stays folded.
    await expect(page.getByRole('button', { name: 'Changes since plan 2' })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('earlier-plans').getByRole('textbox')).toHaveCount(0)
    await page.getByRole('button', { name: 'Show plan 2' }).click()
    await expect(page.getByTestId('earlier-plans').getByRole('textbox', { name: 'Plan' })).toContainText(
        'Sync on launch and on pull to refresh only.',
    )
    await page.goBack()
    await expect(page).toHaveURL(/\/epics\/2$/u)
    await expect(page.getByTestId('epic-board')).toBeVisible()
})

test("a proposed epic's plan is approved from its page, and the board then shows the approved breakdown", async ({
    page,
}) => {
    // The root server's journal never changes: the approval is answered here, as canopy plan epic:2 --approve would,
    // and the epic reads as approved once it is made.
    const approvals: unknown[] = []
    await page.route('**/api/epics/2/plan/approval', async (route) => {
        approvals.push(route.request().postDataJSON())
        await route.fulfill({ json: { plan: 3, run_id: 3, change: null } })
    })
    await page.route('**/api/epics/2', async (route) => {
        const detail = (await (await route.fetch()).json()) as {
            epic: { standing: string }
            plan: { status: string }
            outline: { source: string }
        }
        if (approvals.length > 0) {
            detail.epic.standing = 'approved'
            detail.plan.status = 'approved'
            detail.outline.source = 'approved'
        }
        await route.fulfill({ json: detail })
    })
    await page.route('**/api/epics/2/plans', async (route) => {
        const plans = (await (await route.fetch()).json()) as { plans: { sha256: string; plan: { status: string } }[] }
        const newest = plans.plans.at(-1)
        if (approvals.length > 0 && newest !== undefined) {
            newest.plan.status = 'approved'
        }
        await route.fulfill({ json: plans })
    })
    await page.goto('epics/2/plan')
    await settled(page)
    const bar = page.getByTestId('plan-bar')
    await expect(bar.getByRole('button', { name: 'Ask for changes' })).toBeVisible()
    await bar.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByTestId('plan-approved').getByRole('status')).toHaveText(
        "Approved epic:2's plan, written by run 3.",
    )
    expect(approvals).toEqual([{ read_sha256: expect.stringMatching(/^[0-9a-f]{64}$/u) as unknown }])
    await expect(bar.getByRole('button', { name: 'Approve' })).toHaveCount(0)
    await page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'epic:2' }).click()
    await expect(page).toHaveURL(/\/epics\/2$/u)
    await expect(page.getByRole('link', { name: 'Open the approved plan' })).toBeVisible()
    await expect(page.getByTestId('breakdown')).toContainText('Clear the local copy at sign-out')
})

test("asking for changes to an epic's plan is a reply, and says what it starts", async ({ page }) => {
    const replies: unknown[] = []
    await page.route('**/api/epics/2/replies', async (route) => {
        replies.push(route.request().postDataJSON())
        await route.fulfill({
            json: { message_id: 21, new: true, running_run: null, plan_runs: 2, max_plan_attempts: 3 },
        })
    })
    await page.goto('epics/2/plan')
    await settled(page)
    const bar = page.getByTestId('plan-bar')
    await bar.getByRole('textbox', { name: 'On the whole plan' }).fill('Say how the copy clears offline.')
    await expect(bar.getByRole('button', { name: 'Approve' })).toBeDisabled()
    await bar.getByRole('button', { name: 'Ask for changes' }).click()
    await expect(bar).toContainText(
        'Recorded message 21 on epic:2. The next tick starts its next plan run, which reads your reply.',
    )
    expect(replies).toEqual([{ body: 'Say how the copy clears offline.', submission: expect.any(String) as unknown }])
})

test("a ticket registered on an entry's none yet fills it, and a member is removed once asked", async ({ page }) => {
    // The root server's journal never changes: each write is answered here, as canopy epic add and remove would, and
    // the epic reads as they left it once they are made.
    const writes: unknown[] = []
    await page.route('**/api/epics/1/members', async (route) => {
        writes.push(route.request().postDataJSON())
        await route.fulfill({ json: { key: 'ABC-105', added: true, entries: ['B3'] } })
    })
    await page.route('**/api/epics/1/members/ABC-104', async (route) => {
        writes.push(route.request().method())
        await route.fulfill({ json: { key: 'ABC-104' } })
    })
    await page.route('**/api/epics/1', async (route) => {
        const detail = (await (await route.fetch()).json()) as {
            members: { key: string }[]
            outline: { entries: { id: string; members: string[] }[] }
        }
        for (const entry of detail.outline.entries) {
            if (entry.id === 'B3' && writes.length > 0) {
                entry.members = ['ABC-105']
            }
            if (entry.id === 'B2' && writes.includes('DELETE')) {
                entry.members = []
            }
        }
        await route.fulfill({ json: detail })
    })
    await page.goto('epics/1')
    await settled(page)
    const b3 = page.getByTestId('entry-B3')
    await b3.getByRole('button', { name: 'Register a ticket' }).click()
    const form = page.getByRole('form', { name: 'Register a ticket against B3' })
    await expect(form.getByRole('textbox', { name: 'Ticket key' })).toBeFocused()
    await form.getByRole('textbox', { name: 'Ticket key' }).fill('ABC-105')
    await form.getByRole('button', { name: 'Add and register' }).click()
    const foot = page.getByTestId('members-foot')
    await expect(foot).toContainText('Added ABC-105 to epic:1. Registered ABC-105 against B3.')
    await expect(b3).not.toContainText('none yet')
    expect(writes).toEqual([{ key: 'ABC-105', entries: ['B3'] }])

    const b2 = page.getByTestId('entry-B2')
    await b2.hover()
    await b2.getByRole('button', { name: 'Remove ABC-104' }).click()
    await page.getByRole('button', { name: 'Remove ABC-104 from epic:1' }).click()
    await expect(foot).toContainText('Removed ABC-104 from epic:1.')
    await expect(b2).toContainText('none yet')
})

test("registering the last entry's ticket fills the breakdown, which lights and drops a leaf, once", async ({
    page,
}) => {
    // Epic 1 as it reads with B4 filed already, then with B3 too once ABC-105 is registered against it.
    let registered = false
    await page.route('**/api/epics/1/members', async (route) => {
        registered = true
        await route.fulfill({ json: { key: 'ABC-105', added: true, entries: ['B3'] } })
    })
    await page.route('**/api/epics/1', async (route) => {
        const detail = (await (await route.fetch()).json()) as {
            epic: { entries_with_members: number }
            outline: { entries: { id: string; members: string[] }[] }
        }
        for (const entry of detail.outline.entries) {
            if (entry.id === 'B4' || (entry.id === 'B3' && registered)) {
                entry.members = [entry.id === 'B4' ? 'ABC-106' : 'ABC-105']
            }
        }
        detail.epic.entries_with_members = registered ? 4 : 3
        await route.fulfill({ json: detail })
    })
    await page.goto('epics/1')
    await settled(page)
    const filed = page.getByTestId('entries-filed')
    await expect(filed).toHaveText('3 of 4 entries filed')
    await expect(filed.getByTestId('leaf')).toHaveCount(0)

    await page.getByTestId('entry-B3').getByRole('button', { name: 'Register a ticket' }).click()
    const form = page.getByRole('form', { name: 'Register a ticket against B3' })
    await form.getByRole('textbox', { name: 'Ticket key' }).fill('ABC-105')
    await form.getByRole('button', { name: 'Add and register' }).click()
    await expect(filed).toHaveText('4 of 4 entries filed')
    await expect(filed.getByTestId('leaf')).toHaveCount(1)

    // This browser has had the moment: the page opened again reads it full, and plays nothing.
    await page.reload()
    await settled(page)
    await expect(filed).toHaveText('4 of 4 entries filed')
    await expect(filed.getByTestId('leaf')).toHaveCount(0)
})

test('an epic submitted from its form opens its page, which says its plan run is to come', async ({ page }) => {
    // The root server's journal never changes: the submission is answered here, as canopy epic submit would, and the
    // list and the new epic's page read as it left them, epic 5 built from epic 3's page with no run yet.
    const sent: unknown[] = []
    const goal = 'Let customers export their invoices as CSV.'
    await page.route('**/api/epics', async (route) => {
        if (route.request().method() === 'POST') {
            sent.push(route.request().postDataJSON())
            await route.fulfill({ json: { id: 5, repos: ['api', 'web'] } })
            return
        }
        const list = (await (await route.fetch()).json()) as Record<string, unknown>[]
        const [newest] = list
        await route.fulfill({
            json:
                sent.length === 0
                    ? list
                    : [{ ...newest, id: 5, text: goal, standing: 'queued', stopped_at: null }, ...list],
        })
    })
    await page.route('**/api/epics/5', async (route) => {
        const detail = (await (await route.fetch({ url: route.request().url().replace(/5$/u, '3') })).json()) as {
            epic: Record<string, unknown>
        }
        const epic = { ...detail.epic, id: 5, text: goal, repos: ['api', 'web'], standing: 'queued' }
        await route.fulfill({ json: { ...detail, epic, runs: [], members: [], plan: null, outline: null } })
    })
    await page.goto('epics')
    await settled(page)
    const form = page.getByRole('form', { name: 'Submit an epic' })
    await form.getByRole('textbox', { name: 'Goal' }).fill(goal)
    // A workspace of several repositories: nothing is sent until the operator names those its plan reads.
    await expect(form.getByRole('button', { name: /^Submit/u })).toBeDisabled()
    await form.getByRole('button', { name: 'Its plan reads: repositories it reads' }).click()
    const list = page.getByRole('listbox')
    await list.getByRole('option', { name: 'api' }).click()
    await list.getByRole('option', { name: 'web' }).click()
    await page.keyboard.press('Escape')
    await form.getByRole('textbox', { name: 'Tracker project' }).fill('ABC')
    await form.getByRole('button', { name: /^Submit/u }).click()

    await expect(page).toHaveURL(/\/epics\/5$/u)
    await settled(page)
    await expect(page.getByText('no plan yet: the next tick starts its plan run')).toBeVisible()
    expect(sent).toEqual([
        {
            text: goal,
            repos: ['api', 'web'],
            project: 'ABC',
            tracker_epic: null,
            submission: expect.any(String) as unknown,
        },
    ])
    await page.goBack()
    await expect(page.getByTestId('epics').getByRole('listitem').first()).toContainText('epic:5')
})

test('an epic is stopped from its header once asked, and then says so, and when, there and in its row', async ({
    page,
}) => {
    // The root server's journal never changes: the stop is answered here, as canopy stop epic:3 would, and the epic and
    // the list read as it left them: stopped, its plan run still working.
    const stops: unknown[] = []
    const stoppedAt = '2026-10-08T12:20:00Z'
    await page.route('**/api/epics/3/stop', async (route) => {
        stops.push(route.request().postDataJSON())
        await route.fulfill({ json: { already: false, running_run: 4, ended: false } })
    })
    await page.route('**/api/epics/3', async (route) => {
        const detail = (await (await route.fetch()).json()) as { epic: Record<string, unknown> }
        const epic = stops.length === 0 ? detail.epic : { ...detail.epic, stopped_at: stoppedAt }
        await route.fulfill({ json: { ...detail, epic } })
    })
    await page.route('**/api/epics', async (route) => {
        const list = (await (await route.fetch()).json()) as Record<string, unknown>[]
        for (const epic of list) {
            if (epic.id === 3 && stops.length > 0) {
                epic.stopped_at = stoppedAt
            }
        }
        await route.fulfill({ json: list })
    })
    await page.goto('epics/3')
    await settled(page)
    const actions = page.getByTestId('epic-actions')
    await actions.getByRole('button', { name: 'Stop', exact: true }).click()
    await expect(actions).toContainText('Its members and their work are left as they are.')
    expect(stops).toEqual([])
    await actions.getByRole('button', { name: 'Stop epic:3' }).click()
    await expect(actions).toContainText(
        'epic:3 is stopped; no plan run of it starts again. Its members are left as they are. Its plan run 4 is ' +
            'still working and will finish; Stop now ends it.',
    )
    expect(stops).toEqual([{ now: false }])
    // Its plan run still works: it plans, stopped since, and keeps Stop now alone.
    await expect(page.getByRole('main').locator('header p').first()).toContainText(/ · stopped \d+\w+ ago$/u)
    await expect(actions.getByRole('button')).toHaveText(['Stop now'])

    await page.goto('epics')
    await settled(page)
    await expect(page.getByTestId('epic-3').getByTestId('epic-stopped')).toHaveText(/^stopped \d+\w+ ago$/u)
    await expect(page.getByTestId('epic-4')).toContainText('stopped')
    await expect(page.getByTestId('epic-4').getByTestId('epic-stopped')).toHaveText(/^stopped \d+\w+ ago$/u)
})

test("an approved epic's header opens its plan", async ({ page }) => {
    await page.goto('epics/1')
    await settled(page)
    await page.getByRole('link', { name: 'Open plan' }).click()
    await expect(page).toHaveURL(/\/epics\/1\/plan$/u)
    await settled(page)
    await expect(page.getByRole('textbox', { name: 'Plan' })).toContainText('Every billing call goes to v2')
    await expect(
        page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'epic:1' }),
    ).toBeVisible()
})

test('an epic canopy has no record of is missing', async ({ page }) => {
    await page.goto('epics/999')
    await settled(page)
    await expect(page.getByText('canopy has no epic:999')).toBeVisible()
})

test("a member's ticket page names its epic, one click from it, and its plan the epic plan it follows", async ({
    page,
}) => {
    await page.goto('tickets/ABC-103')
    await settled(page)
    await expect(page.getByTestId('ticket-membership')).toHaveText('epic:1 · B1')
    await page.getByTestId('ticket-membership').getByRole('link', { name: 'epic:1' }).click()
    await expect(page).toHaveURL(/\/epics\/1$/u)

    await page.goto('tickets/ABC-103/plan')
    await settled(page)
    const followed = page.getByTestId('plan-epic')
    await expect(followed).toContainText('follows')
    await expect(followed).toContainText('epic:1’s plan')
    await expect(followed).toContainText(/approved \S+ ago/u)
    // The mock's epic has approved no plan since.
    await expect(page.getByTestId('plan-epic-newer')).toHaveCount(0)

    // A member of no entry says so; a ticket of no epic names none.
    await page.goto('tickets/ABC-100')
    await settled(page)
    await expect(page.getByTestId('ticket-membership')).toHaveText('epic:1 · of no entry')
    await page.goto('tickets/ABC-105')
    await settled(page)
    await expect(page.getByTestId('ticket-membership')).toHaveCount(0)
    await page.goto('tickets/ABC-105/plan')
    await settled(page)
    await expect(page.getByTestId('plan-epic')).toHaveCount(0)
})
