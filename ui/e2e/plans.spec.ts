import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { plan, select, settled, signIn } from './helpers.ts'

// A ticket's plan on its own page (docs/design/PLANNING.md §25), over the mock journal's ABC-105: its newest plan
// waits on the operator, with three comments on it, one resolved, and an earlier plan it superseded. The root server's
// journal never changes, so these only read; the writes are in prefixed.spec.ts.

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await page.goto('tickets/ABC-105/plan')
    await settled(page)
})

test('with comments open, the foot says they go with Ask for changes, or with Approve to the implement', async ({
    page,
}) => {
    await expect(page.getByTestId('plan-bar')).toContainText(
        '2 open comments go with Ask for changes. Approve sends them to the implement instead, and resolves them.',
    )
    await expect(page.getByTestId('plan-actions').getByRole('button', { name: 'Approve with notes' })).toBeVisible()
})

test("a ticket's newest plan opens in the editor, its comments on their passages", async ({ page }) => {
    const section = page.getByTestId('ticket-plan')
    // In words, as everything that waits on you reads; nothing says a plan that waits is not needed.
    await expect(section.getByText('waiting on you', { exact: true })).toBeVisible()
    await expect(page.getByRole('main')).not.toContainText('needed')
    await expect(plan(page).getByRole('heading', { level: 3 })).toHaveText('Schedule report exports')
    await expect(page.getByRole('article')).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Show 1 resolved' })).toBeVisible()
    await expect(page.getByTestId('plan-actions').getByRole('button', { name: 'Approve' })).toBeVisible()
    await expect(page.getByTestId('plan-actions').getByRole('button', { name: 'Save' })).toBeDisabled()
    await expect(page.getByRole('form', { name: 'Ask for changes' })).toBeVisible()
    // It replaced plan 1, so it opens with what changed since marked, and counted: a mode of the Plan panel's header.
    await expect(page.getByRole('button', { name: 'Changes since plan 1' })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('plan-bar').getByRole('button', { name: 'Changes since plan 1' })).toHaveCount(0)
    await expect(page.getByText(/^\d+ changes$/u)).toBeVisible()
    await expect(plan(page).locator('.plan-cell-add').filter({ hasText: 'owner_timezone()' })).toBeVisible()
})

test("the plan's foot sits in its panel, with one primary, and at 820px takes two lines", async ({ page }) => {
    await page.setViewportSize({ width: 820, height: 800 })
    const bar = page.getByTestId('plan-bar')
    const approve = bar.getByRole('button', { name: 'Approve' })
    const ask = bar.getByRole('button', { name: 'Ask for changes' })
    // Its actions on one line, the note on the whole plan among them, and what they do on the line under it.
    const tops = await Promise.all(
        [
            approve,
            bar.getByRole('button', { name: 'Save' }),
            bar.getByRole('button', { name: 'Skip the plan' }),
            ask,
        ].map(async (button) => (await button.boundingBox())?.y ?? 0),
    )
    expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(1)
    const note = await bar.getByRole('textbox', { name: 'On the whole plan' }).boundingBox()
    expect(note?.y ?? 0).toBeLessThan((tops[0] ?? 0) + 8)
    expect((await bar.boundingBox())?.height ?? 0).toBeLessThan(120)
    // The foot of the panel the plan is in, not a box of its own under it.
    const panel = page.locator('section:has(> [data-testid="plan-bar"])')
    await expect(panel.getByRole('textbox', { name: 'Plan', exact: true })).toHaveCount(1)
    // A note being written takes a line of its own, the foot's whole width.
    await bar.getByRole('textbox', { name: 'On the whole plan' }).click()
    const written = await bar.getByRole('textbox', { name: 'On the whole plan' }).boundingBox()
    const actions = await approve.boundingBox()
    expect(written?.y ?? 0).toBeGreaterThan((actions?.y ?? 0) + (actions?.height ?? 0))
    expect(written?.width ?? 0).toBeGreaterThan((await ask.boundingBox())?.width ?? Infinity)
})

test('what Tab moves to stops above the stuck foot, never under it', async ({ page }) => {
    await page.setViewportSize({ width: 820, height: 800 })
    const bar = page.getByTestId('plan-bar')
    await page.getByRole('toolbar', { name: 'Format' }).getByRole('button', { name: 'Undo' }).focus()
    for (let step = 0; step < 30; step += 1) {
        await page.keyboard.press('Tab')
        const focused = page.locator(':focus')
        // The foot's own controls are in it, and the plan is the page's length: neither is covered.
        const inBar = await focused.evaluate(
            (element) => element.closest('[data-testid=plan-bar]') !== null || element.matches('.plan-doc'),
        )
        const box = await focused.boundingBox()
        const foot = await bar.boundingBox()
        if (!inBar && box !== null && foot !== null) {
            // Above the foot, or below it once the panel has ended and the foot rests at its end.
            const under = box.y + box.height > foot.y + 1 && box.y < foot.y + foot.height - 1
            expect(under).toBe(false)
        }
    }
})

test("the plan's page names its ticket and links back to it", async ({ page }) => {
    const title = page.getByRole('heading', { level: 1, name: 'plan:2 Schedule report exports' })
    await expect(title).toBeVisible()
    await page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'ABC-105' }).click()
    await expect(page).toHaveURL(/tickets\/ABC-105$/u)
})

test("a plan that waits on the operator leads its ticket's page as a card, which opens the plan", async ({ page }) => {
    await page.goto('tickets/ABC-105')
    const card = page.getByTestId('plan-card')
    await expect(card).toContainText('waiting on you')
    await expect(card.getByRole('button', { name: 'Approve' })).toBeVisible()
    await expect(card).toContainText('plan:2')
    await expect(card).toContainText(/open comments\s*2/u)
    const box = await card.boundingBox()
    const work = await page.getByTestId('ticket-actions').boundingBox()
    expect(box?.y).toBeLessThan(work?.y ?? 0)
    // The card approves, and nothing else: the editor and its other actions are the plan's page's.
    await expect(page.getByTestId('ticket-plan')).toHaveCount(0)
    await card.getByRole('link', { name: 'Open plan' }).click()
    await expect(page).toHaveURL(/tickets\/ABC-105\/plan$/u)
    await expect(plan(page).getByRole('heading', { level: 3 })).toHaveText('Schedule report exports')
})

test("the ticket's page waits for its plans to paint, so a card that leads it never pushes it down", async ({
    page,
}) => {
    let release: (() => void) | undefined
    const held = new Promise<void>((resolve) => {
        release = resolve
    })
    await page.route('**/api/tickets/ABC-105/plans', async (route) => {
        await held
        await route.continue()
    })
    await page.goto('tickets/ABC-105')
    await expect(page.getByRole('heading', { name: /ABC-105/u })).toBeVisible()
    await expect(page.getByTestId('ticket-actions')).toHaveCount(0)
    release?.()
    const card = await page.getByTestId('plan-card').boundingBox()
    const work = await page.getByTestId('ticket-actions').boundingBox()
    expect(card?.y).toBeLessThan(work?.y ?? 0)
})

test("a ticket's page loads no plan editor", async ({ page }) => {
    const scripts: string[] = []
    page.on('request', (request) => {
        if (request.resourceType() === 'script') {
            scripts.push(request.url())
        }
    })
    await page.goto('tickets/ABC-102')
    await settled(page)
    await page.goto('tickets/ABC-105')
    await expect(page.getByTestId('plan-card')).toBeVisible()
    expect(scripts.filter((url) => /plan-editor-/u.test(url))).toEqual([])
})

test("a plan review on the attention list shows the plan's card, which approves it and opens its page", async ({
    page,
}) => {
    await listPlanReview(page)
    // The root server's journal never changes: the approval is answered here, as canopy plan --approve would.
    const approvals: unknown[] = []
    await page.route('**/api/tickets/ABC-105/plan', async (route) => {
        approvals.push(route.request().postDataJSON())
        await route.fulfill({ json: { action: 'approve', already: false, plan: 2, superseded: null } })
    })
    await page.goto('attention')
    const card = page.getByTestId('attention-detail').getByTestId('plan-card')
    await expect(card).toContainText('waiting on you')
    await expect(card).toContainText('plan:2')
    await card.getByRole('button', { name: 'Approve' }).click()
    await expect(card.getByRole('status')).toHaveText(
        'Plan 2 of ABC-105 is approved as its file stands now. The next tick can implement it.',
    )
    expect(approvals).toEqual([{ action: 'approve' }])
    await card.getByRole('link', { name: 'Open plan' }).click()
    await expect(page).toHaveURL(/tickets\/ABC-105\/plan$/u)
})

test('a plan review you answered since its tick says so until the next one', async ({ page }) => {
    await listPlanReview(page)
    // The root server's journal never changes: the plan is answered here, as asking for changes would answer it.
    await page.route('**/api/tickets', async (route) => {
        const tickets = (await (await route.fetch()).json()) as { key: string; plan_waits: boolean }[]
        for (const ticket of tickets) {
            ticket.plan_waits &&= ticket.key !== 'ABC-105'
        }
        await route.fulfill({ json: tickets })
    })
    await page.goto('attention')
    await expect(page.getByTestId('attention-item-ABC-105:plan_review')).toContainText('answered')
    await expect(page.getByTestId('answered-note')).toHaveText(
        'You answered the plan. The item leaves at the next tick, when the loop reads your answer.',
    )
})

test('an earlier plan opens read only', async ({ page }) => {
    const earlier = page.getByTestId('earlier-plans')
    await expect(earlier).toContainText('superseded')
    await earlier.getByRole('button', { name: 'Show plan 1' }).click()
    await expect(earlier.getByRole('textbox', { name: 'Plan', exact: true })).toContainText('emails the CSV')
    await expect(earlier.getByRole('textbox', { name: 'Plan', exact: true })).toHaveAttribute(
        'contenteditable',
        'false',
    )
})

test('a plan shows the persona its planner wrote in, and opens to the instructions it read', async ({ page }) => {
    const persona = page.getByTestId('persona').first()
    await expect(persona).toContainText('canopy')
    await persona.getByRole('button', { name: 'Show instructions' }).click()
    await expect(persona.getByRole('region', { name: "the persona's instructions" })).toContainText(
        'When you plan, be as long as the work needs and no longer.',
    )
    // An earlier plan's planner read its own text, kept under its own digest.
    const earlier = page.getByTestId('earlier-plans')
    await earlier.getByRole('button', { name: 'Show plan 1' }).click()
    await expect(earlier.getByTestId('persona')).toContainText('canopy c4a0f1e2d3b4')
    await earlier.getByTestId('persona').getByRole('button', { name: 'Show instructions' }).click()
    await expect(earlier.getByRole('region', { name: "the persona's instructions" })).toContainText('When you plan')
})

test('leaving the page with an edit not yet saved asks first; Stay keeps the edit, Leave goes', async ({ page }) => {
    await plan(page).getByText('Exports to anything but CSV.').click()
    await page.keyboard.press('End')
    await page.keyboard.type(' Or PDF.')
    const tickets = page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'Tickets' })
    await tickets.click()
    const ask = page.getByRole('alertdialog', { name: 'Leave this page?' })
    await expect(ask).toContainText('Your edits to the plan are not saved.')
    await expect(ask.getByRole('button', { name: 'Stay' })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(ask).toBeHidden()
    await expect(page).toHaveURL(/tickets\/ABC-105\/plan$/u)
    await expect(plan(page)).toContainText('Or PDF.')
    await tickets.click()
    await ask.getByRole('button', { name: 'Leave' }).click()
    await expect(page).toHaveURL(/tickets$/u)
})

test('a comment half written asks before the page is left, by a link or by closing the tab', async ({ page }) => {
    await select(page, 'owner_timezone()')
    await page.keyboard.press('ControlOrMeta+Alt+m')
    await page.keyboard.type('Which timezone?')
    await page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'Tickets' }).click()
    const ask = page.getByRole('alertdialog', { name: 'Leave this page?' })
    await expect(ask).toContainText('What you wrote in a comment is not sent.')
    await ask.getByRole('button', { name: 'Stay' }).click()
    await expect(page.getByRole('form', { name: 'Comment' }).getByRole('textbox')).toHaveValue('Which timezone?')
    // Resolved once the dialog is dismissed, not when it opens: a test that ends while it is still up closes its
    // context under it, which fails the teardown.
    const asked = new Promise<string>((resolve) => {
        page.once('dialog', async (dialog) => {
            await dialog.dismiss()
            resolve(dialog.type())
        })
    })
    await page.close({ runBeforeUnload: true })
    expect(await asked).toBe('beforeunload')
    // Dismissed, the tab stays open. Closed here without asking again, the page leaves nothing half closed for the
    // context's teardown, which otherwise failed now and then closing a page whose close was refused under it.
    expect(page.isClosed()).toBe(false)
    await page.close()
})

test('writing a note on the whole plan never scrolls the page under it', async ({ page }) => {
    // Short enough that the plan runs past the window, so the foot is stuck to its bottom.
    await page.setViewportSize({ width: 1280, height: 600 })
    const scroller = page.locator('.page-scroll')
    const note = page.getByTestId('plan-bar').getByRole('textbox', { name: 'On the whole plan' })
    const top = await scroller.evaluate((element) => element.scrollTop)
    // By the pointer, where the field is: a locator's click scrolls it into view first, which a person's never does.
    const box = await note.boundingBox()
    await page.mouse.click((box?.x ?? 0) + 8, (box?.y ?? 0) + 8)
    await expect(note).toBeFocused()
    // Long enough to wrap: the field grows a line as the caret moves to the next.
    const words = 'Split the export into a module of its own, and keep the time zone handling as it is in the plan.'
    await note.pressSequentially(words)
    await expect(note).toHaveValue(words)
    expect(await scroller.evaluate((element) => element.scrollTop)).toBe(top)
})

// The stream would send the list as the journal has it, which has no review of a ticket's plan: the list here is the
// test's, ABC-105's.
async function listPlanReview(page: Page) {
    await page.route('**/api/events', (route) => route.abort())
    await page.route('**/api/attention', (route) =>
        route.fulfill({
            json: [
                {
                    id: 'ABC-105:plan_review',
                    ticket_key: 'ABC-105',
                    ticket_title: 'Schedule report exports',
                    reason: 'plan_review',
                    detail: 'plan 2 waits on your approval',
                    since: '2026-10-08T11:52:00Z',
                    chore: null,
                    pr: null,
                    task: null,
                    run: null,
                    review: null,
                    repo: null,
                    finding: false,
                    subject: 'ABC-105',
                },
            ],
        }),
    )
}
