import { expect, test } from '@playwright/test'

import { ROUTES, settled, signIn } from './helpers.ts'

/**
 * Every page's headings as a screen reader lists them, in document order: one h1, the page's title, and no level
 * skipped after it, so a panel's title is an h2 and what heads a part of a panel an h3 (DESIGN.md, "Headings").
 */
for (const route of ROUTES) {
    test(`${route} has one h1 and skips no heading level`, async ({ page }) => {
        await signIn(page)
        await page.goto(route)
        await settled(page)
        await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
        const levels = await page.evaluate(() =>
            [...document.querySelectorAll('h1, h2, h3, h4, h5, h6, [role=heading]')]
                .filter((el) => el.checkVisibility() && el.closest('[aria-hidden=true]') === null)
                .map((el) => ({
                    level: Number(el.getAttribute('aria-level') ?? el.tagName.slice(1)),
                    text: el.textContent.trim().slice(0, 40),
                })),
        )
        const skipped = levels.filter((h, i) => (i === 0 ? h.level !== 1 : h.level > (levels[i - 1]?.level ?? 0) + 1))
        expect(skipped, `headings: ${levels.map((h) => `h${h.level} ${h.text}`).join(' | ')}`).toEqual([])
    })
}
