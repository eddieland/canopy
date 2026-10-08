import { expect, test } from '@playwright/test'

import { E2E_SECRET } from './secret.ts'

// The root server needs the listener secret (DESIGN §22, D082).

test('signed out, every route shows the sign-in page and the API refuses', async ({ page, request }) => {
    await page.goto('tickets/ABC-102')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Sign in')
    await expect(page.getByText('ABC-102')).toHaveCount(0)
    for (const path of ['api/meta', 'api/tickets', 'api/tickets/ABC-102', 'api/events']) {
        expect((await request.get(path)).status(), path).toBe(401)
    }
})

test('a wrong secret is refused; the right one signs in and stays signed in', async ({ page }) => {
    await page.goto('tickets/ABC-102')
    const secret = page.getByLabel('Listener secret')
    await secret.fill('not-the-secret')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('alert')).toHaveText('That is not the listener secret.')

    await secret.fill(E2E_SECRET)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-102')
    const cookies = await page.context().cookies()
    const session = cookies.find((c) => c.name.startsWith('canopy_session_'))
    expect(session?.httpOnly).toBe(true)
    expect(session?.sameSite).toBe('Strict')
    expect(JSON.stringify(cookies)).not.toContain(E2E_SECRET)
    expect(await page.evaluate(() => JSON.stringify(window.localStorage))).not.toContain(E2E_SECRET)

    await page.reload()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('ABC-102')
})

test('signing out returns to the sign-in page', async ({ page }) => {
    await page.request.post('api/session', { data: { secret: E2E_SECRET } })
    await page.goto('settings')
    await page.getByRole('button', { name: 'Sign out' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Sign in')
    expect((await page.request.get('api/meta')).status()).toBe(401)
})

test('a write without the session token is refused even with the cookie', async ({ page }) => {
    await page.request.post('api/session', { data: { secret: E2E_SECRET } })
    const response = await page.request.post('api/tickets/ABC-102/start', {
        headers: { origin: 'http://127.0.0.1:8766' },
    })
    expect(response.status()).toBe(403)
})
