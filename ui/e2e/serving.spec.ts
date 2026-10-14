import { expect, test } from '@playwright/test'

import { signIn } from './helpers.ts'

// How FastAPI serves the build: these hold for every route the UI will ever have.

test('a deep link gets index.html, uncached, with a CSP and no external origins', async ({ request }) => {
    const response = await request.get('tickets/ABC-102')
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/html')
    expect(response.headers()['cache-control']).toBe('no-cache')
    const csp = response.headers()['content-security-policy'] ?? ''
    expect(csp).toContain("default-src 'self'")
    expect(csp).not.toMatch(/https?:/u)
})

test('hashed assets are immutable; a missing one is a 404, not the page', async ({ request, page }) => {
    await page.goto('runs')
    const script = await page.locator('script[type=module]').getAttribute('src')
    expect(script).toMatch(/^\.\/assets\//u)
    const asset = await request.get(script ?? '')
    expect(asset.headers()['cache-control']).toContain('immutable')

    const missing = await request.get('assets/missing-abc123.js')
    expect(missing.status()).toBe(404)
    expect(await missing.text()).not.toContain('<html')
})

test('the fallback never answers for the API', async ({ request }) => {
    const response = await request.get('api/nope')
    expect(response.status()).toBe(404)
    expect(await response.json()).toEqual({ detail: 'Not Found' })
})

test('a foreign Origin is refused on the API and the stream', async ({ request }) => {
    for (const path of ['api/meta', 'api/events']) {
        const response = await request.get(path, { headers: { origin: 'https://evil.example' } })
        expect(response.status()).toBe(403)
    }
})

test('the page makes no request to another origin', async ({ page, baseURL }) => {
    const origins = new Set<string>()
    page.on('request', (request) => origins.add(new URL(request.url()).origin))
    await signIn(page)
    await page.goto('tickets/ABC-101')
    await expect(page.getByTestId('conversation')).toBeVisible()
    await page.evaluate(async () => {
        await document.fonts.ready
    })
    expect([...origins]).toEqual([new URL(baseURL ?? '').origin])
})
