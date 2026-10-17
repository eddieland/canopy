import { expect, test } from '@playwright/test'

import { plan, select, settled, signIn } from './helpers.ts'

// A ticket's plan on its page (docs/design/PLANNING.md §25), over the mock journal's ABC-105: its newest plan waits on
// the operator, with three comments on it, one resolved, and an earlier plan it superseded. The root server's journal
// never changes, so these only read; the writes are in prefixed.spec.ts.

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await page.goto('tickets/ABC-105')
    await settled(page)
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
})

test('a plan that waits on the operator leads the page, above its Work panel', async ({ page }) => {
    const section = await page.getByTestId('ticket-plan').boundingBox()
    const work = await page.getByTestId('ticket-actions').boundingBox()
    expect(section?.y).toBeLessThan(work?.y ?? 0)
    await expect(page.getByTestId('ticket-plan')).toBeInViewport()
})

test('the page waits for its plans to paint, so a plan that leads it never pushes it down', async ({ page }) => {
    let release: (() => void) | undefined
    const held = new Promise<void>((resolve) => {
        release = resolve
    })
    await page.route('**/api/tickets/ABC-105/plans', async (route) => {
        await held
        await route.continue()
    })
    await page.reload()
    await expect(page.getByRole('heading', { name: /ABC-105/u })).toBeVisible()
    await expect(page.getByTestId('ticket-actions')).toHaveCount(0)
    release?.()
    const section = await page.getByTestId('ticket-plan').boundingBox()
    const work = await page.getByTestId('ticket-actions').boundingBox()
    expect(section?.y).toBeLessThan(work?.y ?? 0)
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
    await expect(page).toHaveURL(/tickets\/ABC-105$/u)
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
