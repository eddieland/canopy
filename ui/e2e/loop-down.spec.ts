import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// When the loop stops answering, the stream drops and does not come back (ui/DESIGN.md, the header). The page's own
// EventSource is kept where the test can reach it, so the test can drop it as a dead server would, and every new
// one is refused until the loop is "back".

test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
        const Native = globalThis.EventSource
        const streams: EventSource[] = []
        Object.assign(globalThis, { streams })
        globalThis.EventSource = class extends Native {
            constructor(url: string | URL, init?: EventSourceInit) {
                super(url, init)
                streams.push(this)
            }
        }
    })
    await signIn(page)
    await page.goto('runs')
    await settled(page)
    await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'open')
})

// Kills the stream as a loop that stopped would: every open one errors and closes, and no new one is answered.
async function stopLoop(page: Page): Promise<void> {
    await page.route('**/api/events', (route) => route.abort())
    await page.evaluate(() => {
        for (const stream of (globalThis as unknown as { streams: EventSource[] }).streams) {
            stream.close()
            stream.dispatchEvent(new Event('error'))
        }
    })
}

// Brings it back: new streams are answered, and the device saying it is online starts one at once.
async function startLoop(page: Page): Promise<void> {
    await page.unroute('**/api/events')
    await page.evaluate(() => globalThis.dispatchEvent(new Event('online')))
}

// Where each of the header's elements starts, left to right.
function header(page: Page): Promise<number[]> {
    const bar = page.getByTestId('app-header')
    const parts: Locator[] = [
        bar.getByRole('button', { name: /Pause|Resume/u }),
        bar.getByRole('button', { name: 'Tick now' }),
        page.getByTestId('last-tick'),
        page.getByTestId('memory-readout'),
        page.getByTestId('stream-status'),
    ]
    return Promise.all(parts.map(async (part) => (await part.boundingBox())?.x ?? Number.NaN))
}

test('when the loop stops answering the header moves nothing, says how long, and the band says what to do', async ({
    page,
}) => {
    const before = await header(page)
    await stopLoop(page)
    const status = page.getByTestId('stream-status')
    await expect(status).toHaveAttribute('data-status', 'reconnecting')
    expect(await header(page)).toEqual(before)

    // Past the first retry's wait it says how long, in the color of what waits on the operator.
    await expect(status).toHaveAttribute('data-status', 'down', { timeout: 8_000 })
    await expect(status).toHaveText(/down · \d+s$/u)
    expect(await header(page)).toEqual(before)

    // Then the band, with the commands that bring it back, and the loop's actions wait, saying why.
    const band = page.getByTestId('loop-down')
    await expect(band).toBeVisible({ timeout: 8_000 })
    await expect(band).toContainText("The loop isn't answering.")
    await expect(band).toContainText('canopy loop')
    await expect(band).toContainText('canopy daemon start')
    const tickNow = page.getByRole('button', { name: 'Tick now' })
    await expect(tickNow).toBeDisabled()
    await expect(tickNow).toHaveAttribute('title', /canopy daemon start/u)
    await expect(page.getByTestId('loop-pause').getByRole('button')).toBeDisabled()
    await expect(page.getByTestId('rail-working')).toHaveAttribute('data-stale', 'true')

    // Back, it is live again where it was, and the band goes, with no reload.
    await startLoop(page)
    await expect(status).toHaveAttribute('data-status', 'open')
    await expect(status).toHaveText(/live$/u)
    await expect(band).toHaveCount(0)
    await expect(tickNow).toBeEnabled()
    expect(await header(page)).toEqual(before)
})
