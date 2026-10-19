import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { E2E_SECRET } from './secret.ts'
import { settled, signIn } from './helpers.ts'

// A write that fails says so in canopy's words, keeps what the operator wrote, and moves nothing on the page. Every
// write here is answered by the route, so the root server's journal never changes.

const REPLIES = '**/api/tickets/ABC-102/replies'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

async function reply(page: Page, text: string): Promise<void> {
    const form = page.getByRole('form', { name: 'Reply' })
    await form.getByRole('textbox').fill(text)
    await form.getByRole('button', { name: 'Reply' }).click()
}

test('a reply signed out by a 401 is still in its box after signing in again', async ({ page }) => {
    await page.route(REPLIES, (route) =>
        route.fulfill({ status: 401, json: { detail: 'sign in with the listener secret' } }),
    )
    await page.goto('tickets/ABC-102')
    await settled(page)
    await reply(page, 'Use the v2 API')

    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Sign in')
    await expect(page.getByText('Your last action was not sent: sign in and send it again.')).toBeVisible()
    await page.getByLabel('Listener secret').fill(E2E_SECRET)
    await page.getByRole('button', { name: 'Sign in' }).click()

    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-102 Export reports as CSV')
    await expect(page.getByRole('form', { name: 'Reply' }).getByRole('textbox')).toHaveValue('Use the v2 API')
})

test('a reply that reaches no server, or a failed one, says so in words', async ({ page }) => {
    let answer: 'abort' | 'bad gateway' = 'abort'
    await page.route(REPLIES, async (route) => {
        await (answer === 'abort' ? route.abort() : route.fulfill({ status: 502, body: 'Bad Gateway' }))
    })
    await page.goto('tickets/ABC-102')
    await settled(page)
    const said = page.getByRole('form', { name: 'Reply' }).getByRole('alert')

    await reply(page, 'Use the v2 API')
    await expect(said).toHaveText('canopy did not answer: is canopy loop running?')

    answer = 'bad gateway'
    await page.getByRole('form', { name: 'Reply' }).getByRole('button', { name: 'Reply' }).click()
    await expect(said).toHaveText('canopy failed (502): it may not have been done')
})

// The page's top in one frame for each test id, so a scroll as a button is clicked moves them all alike.
function tops(ids: readonly string[]): number[] {
    return ids.map((id) => document.querySelector(`[data-testid=${id}]`)?.getBoundingClientRect().top ?? 0)
}

test('a refused Stop says why and moves nothing below its actions', async ({ page }) => {
    // Panels rise into place as a page opens; with motion reduced they rest where they end, and nothing moves alone.
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.route('**/api/tickets/ABC-102/stop', (route) =>
        route.fulfill({ status: 409, json: { detail: { guard: 'not_started', reason: 'ABC-102 was not started' } } }),
    )
    await page.goto('tickets/ABC-102')
    await settled(page)
    const ids = ['ticket-actions', 'ticket-runs'] as const
    const below = async () => {
        const [actions = 0, runs = 0] = await page.evaluate(tops, ids)
        return runs - actions
    }
    const before = await below()

    await page.getByTestId('ticket-actions').getByRole('button', { name: 'Stop', exact: true }).click()
    await expect(page.getByTestId('ticket-actions').getByRole('alert')).toHaveText(
        'refused (not_started): ABC-102 was not started',
    )
    // Within a pixel: layout rounds the same place to a hair either side of it.
    expect(await below()).toBeCloseTo(before, 0)
})
