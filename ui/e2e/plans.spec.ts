import { expect, test } from '@playwright/test'

import { plan, select, settled, signIn } from './helpers.ts'

// A ticket's plan on its own page (docs/design/PLANNING.md §25), over the mock journal's ABC-105: its newest plan
// waits on the operator, with three comments on it, one resolved, and an earlier plan it superseded. The root server's
// journal never changes, so these only read; the writes are in prefixed.spec.ts.

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await page.goto('tickets/ABC-105/plan')
    await settled(page)
})

test('with comments open, the bar says Approve sends none of them', async ({ page }) => {
    await expect(page.getByTestId('plan-bar')).toContainText(
        '2 comments are still open: approving sends none of them, since the implement reads the plan alone. ' +
            'Ask for changes does.',
    )
})

test("a ticket's newest plan opens in the editor, its comments on their passages", async ({ page }) => {
    const section = page.getByTestId('ticket-plan')
    await expect(section.getByTestId('plan-status')).toContainText('Plan not needed, by policy.plan off.')
    await expect(section.getByTestId('plan-status')).toContainText('proposed')
    await expect(plan(page).getByRole('heading', { level: 1 })).toHaveText('Schedule report exports')
    await expect(page.getByRole('article')).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Show 1 resolved' })).toBeVisible()
    await expect(page.getByTestId('plan-actions').getByRole('button', { name: 'Approve' })).toBeVisible()
    await expect(page.getByTestId('plan-actions').getByRole('button', { name: 'Save' })).toBeDisabled()
    await expect(page.getByRole('form', { name: 'Ask for changes' })).toBeVisible()
    // It replaced plan 1, so it opens with what changed since marked, and counted.
    const bar = page.getByTestId('plan-bar')
    await expect(bar.getByRole('button', { name: 'Changes since plan 1' })).toHaveAttribute('aria-pressed', 'true')
    await expect(bar.getByText(/^\d+ changes$/u)).toBeVisible()
    await expect(plan(page).locator('ins').filter({ hasText: 'owner_timezone()' }).first()).toBeVisible()
})

test("the plan's page names its ticket and links back to it", async ({ page }) => {
    const title = page.getByRole('heading', { level: 1, name: 'Plan', exact: true })
    await expect(page.locator('header', { has: title })).toContainText('Schedule report exports')
    await page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'ABC-105' }).click()
    await expect(page).toHaveURL(/tickets\/ABC-105$/u)
})

test("a plan that waits on the operator leads its ticket's page as a card, which opens the plan", async ({ page }) => {
    await page.goto('tickets/ABC-105')
    const card = page.getByTestId('plan-card')
    await expect(card).toContainText('proposed')
    await expect(card).toContainText('plan:2')
    await expect(card).toContainText(/open comments\s*2/u)
    const box = await card.boundingBox()
    const work = await page.getByTestId('ticket-actions').boundingBox()
    expect(box?.y).toBeLessThan(work?.y ?? 0)
    // The card only reads: the editor and its actions are the plan's page's.
    await expect(page.getByTestId('ticket-plan')).toHaveCount(0)
    await card.getByRole('link', { name: 'Open plan' }).click()
    await expect(page).toHaveURL(/tickets\/ABC-105\/plan$/u)
    await expect(plan(page).getByRole('heading', { level: 1 })).toHaveText('Schedule report exports')
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

test("a plan review on the attention list opens the plan's page", async ({ page }) => {
    // The stream would send the list as the journal has it, which has no plan review: the list here is the test's.
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
                    repo: null,
                    finding: false,
                    subject: 'ABC-105',
                },
            ],
        }),
    )
    await page.goto('attention')
    await page.getByTestId('attention-detail').getByRole('link', { name: 'Open plan' }).click()
    await expect(page).toHaveURL(/tickets\/ABC-105\/plan$/u)
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
    const asked = new Promise<string>((resolve) => {
        page.once('dialog', async (dialog) => {
            resolve(dialog.type())
            await dialog.dismiss()
        })
    })
    await page.close({ runBeforeUnload: true })
    expect(await asked).toBe('beforeunload')
})
