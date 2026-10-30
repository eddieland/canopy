import { expect, test } from '@playwright/test'
import type { Locator } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

/** Resolves once `highlight` sits exactly on `link`, as it does once its slide has ended. */
async function covers(highlight: Locator, link: Locator): Promise<void> {
    await expect(async () => {
        const [h, l] = await Promise.all([highlight.boundingBox(), link.boundingBox()])
        expect(h?.y).toBeCloseTo(l?.y ?? Number.NaN, 0)
        expect(h?.x).toBeCloseTo(l?.x ?? Number.NaN, 0)
        expect(h?.height).toBeCloseTo(l?.height ?? Number.NaN, 0)
    }).toPass()
}

test('the nav highlight slides to the item a navigation lands on', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const nav = page.getByRole('navigation', { name: 'Main' })
    const highlight = page.getByTestId('nav-highlight')
    await covers(highlight, nav.getByRole('link', { name: 'Attention' }))

    await expect(highlight).toHaveClass(/\bbg-section-attention\/24\b/u)

    await nav.getByRole('link', { name: 'Reports' }).click()
    await covers(highlight, nav.getByRole('link', { name: 'Reports' }))
    // It takes on the color of the section it lands on.
    await expect(highlight).toHaveClass(/\bbg-section-reports\/24\b/u)

    // On a page under Reports, it sits on that page's item, in Reports' color.
    await nav.getByRole('link', { name: 'Spend' }).click()
    await covers(highlight, nav.getByRole('link', { name: 'Spend' }))
    await expect(highlight).toHaveClass(/\bbg-section-reports\/24\b/u)

    await page.getByRole('link', { name: 'Tickets' }).click()
    await page.getByTestId('tickets').getByRole('link', { name: 'ABC-102', exact: true }).click()
    await covers(highlight, nav.getByRole('link', { name: 'Tickets' }))
})

/** The names of the animations running on `locator`'s element. */
function animations(locator: Locator): Promise<string[]> {
    return locator.evaluate((element) =>
        element.getAnimations().map((animation) => (animation as CSSAnimation).animationName),
    )
}

/** Plays `locator`'s element's animations to their end. */
async function finish(locator: Locator): Promise<void> {
    await locator.evaluate((element) => {
        for (const animation of element.getAnimations()) {
            animation.finish()
        }
    })
}

test('a dialog floats in and out again, and under reduced motion only appears and goes', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const palette = page.getByRole('dialog', { name: 'Jump to a ticket' })
    // Each float is held at its first frame, so the check sees an animation that would end before it looked.
    await page.evaluate(() => {
        document.addEventListener('animationstart', (event) => {
            if (event.animationName.startsWith('float-')) {
                for (const animation of (event.target as Element).getAnimations()) {
                    animation.pause()
                }
            }
        })
    })

    await page.keyboard.press('Control+k')
    await expect.poll(() => animations(palette)).toContain('float-in')
    await finish(palette)
    await page.keyboard.press('Escape')
    // A closing dialog stays in the page while it floats out.
    await expect.poll(() => animations(palette)).toContain('float-out')
    await finish(palette)
    await expect(palette).toBeHidden()

    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.keyboard.press('Control+k')
    await expect(palette).toBeVisible()
    expect(await animations(palette)).toEqual([])
    await page.keyboard.press('Escape')
    await expect(palette).toBeHidden()
})

test('under reduced motion, counters read their values and nothing waits on an animation', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('attention')
    await settled(page)
    await expect(page.getByTestId('counter-attention')).toContainText('10')
    const running = await page.evaluate(() => document.getAnimations().map((a) => a.constructor.name))
    expect(running).toEqual([])
})

test('the header ticker crawls one headline at a time, at the speed and gap set in Settings', async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    const ticker = page.getByTestId('ticker')
    const headline = page.getByTestId('ticker-headline')
    await expect(ticker).toHaveAttribute('data-speed', 'normal')
    await expect(headline).toHaveCount(1)

    // A flair's own loops (a flash, a wave) bubble their iterations up; they do not move the reel on.
    const first = await headline.textContent()
    await headline.evaluate((element) => {
        const event = new AnimationEvent('animationiteration', { bubbles: true, animationName: 'wave' })
        element.firstElementChild?.dispatchEvent(event)
    })
    await expect(headline).toHaveText(first ?? '')

    // At the end of its pass, the next headline takes the window.
    await headline.evaluate((element) => {
        const [crawl] = element.getAnimations()
        const duration = Number(crawl?.effect?.getComputedTiming().duration)
        if (crawl) {
            crawl.currentTime = duration - 20
        }
    })
    await expect(headline).not.toHaveText(first ?? '')
    await expect(headline).toHaveCount(1)

    await page.getByTestId('ticker-spicy').click()
    await expect(ticker).toHaveAttribute('data-speed', 'spicy')

    // The gap pads the line by the distance the crawl covers in that time: 5 seconds at 9rem a second.
    await page.getByTestId('ticker-gap').fill('5')
    await expect(headline).toHaveCSS('padding-right', `${5 * 9 * 16}px`)

    await page.getByTestId('fun-ticker').click()
    await expect(ticker).toHaveCount(0)
    await page.reload()
    await settled(page)
    await expect(ticker).toHaveCount(0)
    await expect(page.getByTestId('fun-ticker')).not.toBeChecked()
    await expect(page.getByTestId('ticker-gap')).toHaveValue('5')
    await expect(page.getByTestId('ticker-gap')).toBeDisabled()
    await expect(page.getByTestId('ticker-spicy')).toBeDisabled()

    // Back on, it keeps the speed and gap it had.
    await page.getByTestId('fun-ticker').click()
    await expect(ticker).toHaveAttribute('data-speed', 'spicy')
    await expect(page.getByTestId('ticker-gap')).toBeEnabled()
})

test('the ticker steps out of a header with no room to read a headline in, and back in when there is', async ({
    page,
}) => {
    await page.goto('attention')
    await settled(page)
    const ticker = page.getByTestId('ticker')
    await expect(ticker).toBeVisible()

    await page.setViewportSize({ width: 700, height: 800 })
    await expect(ticker).toHaveCount(0)
    // Its room stays, so the readouts keep their place at the header's end.
    const header = await page.getByTestId('app-header').boundingBox()
    const readouts = await page.getByTestId('live-readouts').boundingBox()
    // Measured by their end, not their start: how wide they are depends on what they show, memory's readout among them.
    const end = readouts === null ? 0 : readouts.x + readouts.width
    expect(end).toBeGreaterThan((header?.width ?? 0) * 0.85)

    await page.setViewportSize({ width: 1280, height: 800 })
    await expect(ticker).toBeVisible()
})

test('the ticker holds its headline in place when the readouts beside it change width', async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const frame = page.getByTestId('ticker')
    const headline = page.getByTestId('ticker-headline')
    // Held mid-pass, then the latest tick's readout widens, as it does when a tick starts: the window narrows.
    await headline.evaluate(async (element) => {
        const [crawl] = element.getAnimations()
        crawl?.pause()
        await crawl?.ready
    })
    const where = (): Promise<number | undefined> =>
        headline.evaluate((element) => element.firstElementChild?.getBoundingClientRect().left)
    const before = await where()
    const wide = (await frame.boundingBox())?.width ?? 0
    await page.getByTestId('last-tick').evaluate((element) => {
        element.append(' running · for 12s')
    })
    await expect.poll(async () => (await frame.boundingBox())?.width).toBeLessThan(wide)
    expect(await where()).toBeCloseTo(before ?? Number.NaN, 0)
})

test('the ticker leaves out the topics turned off in Settings', async ({ page }) => {
    await page.goto('settings')
    await settled(page)
    const ticker = page.getByTestId('ticker')
    const headline = page.getByTestId('ticker-headline')
    const programming = page.getByTestId('ticker-topic-programming')
    const vibes = page.getByTestId('ticker-topic-vibes')
    const tips = page.getByTestId('ticker-topic-tips')
    await expect(programming).toBeChecked()
    await expect(tips).toBeChecked()

    // With the jokes off, every headline is a tip.
    await programming.click()
    await page.getByText('Vibe coding', { exact: true }).click()
    await expect(vibes).not.toBeChecked()
    await expect(headline).toHaveText(/^Tip: /u)

    // With none picked, the window is gone, and it stays gone on a reload.
    await tips.click()
    await expect(ticker).toHaveCount(0)
    await page.reload()
    await settled(page)
    await expect(ticker).toHaveCount(0)
    await expect(tips).not.toBeChecked()

    await vibes.click()
    await expect(headline).not.toHaveText(/^Tip: /u)
})
