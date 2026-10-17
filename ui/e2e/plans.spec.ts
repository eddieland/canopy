import { expect, test } from '@playwright/test'

import { plan, settled, signIn } from './helpers.ts'

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

test('a waiting plan that replaced one opens with its changes marked, and counted', async ({ page }) => {
    const bar = page.getByTestId('plan-bar')
    await expect(bar.getByRole('button', { name: 'Changes since plan 1' })).toHaveAttribute('aria-pressed', 'true')
    await expect(bar.getByText(/^\d+ changes$/u)).toBeVisible()
    await expect(plan(page).locator('ins').filter({ hasText: 'owner_timezone()' }).first()).toBeVisible()
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
