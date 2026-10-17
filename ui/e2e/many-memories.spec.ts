import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// A workspace far past the mock's handful of memories: hundreds of tickets with notes in force, and hundreds of lessons
// promoted. The memory page must keep each tier in reach, send counts rather than every note, and say which lessons
// the digest's cap leaves out.

const TICKETS = 300
const LESSONS = 200
// The lessons the digest serves; the cap leaves out the rest.
const SERVED = 4

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the memory page lists a row a ticket, scrolls each list in its panel, and opens notes one ticket at a time', async ({
    page,
}) => {
    await manyMemories(page)
    const opened: string[] = []
    page.on('request', (request) => {
        const found = /\/api\/tickets\/([^/]+)\/memory$/u.exec(new URL(request.url()).pathname)
        if (found?.[1] !== undefined) {
            opened.push(decodeURIComponent(found[1]))
        }
    })
    await page.goto('memory')
    await settled(page)

    const notes = page.getByTestId('memory-notes')
    await expect(notes.getByTestId(/^memory-ticket-/u)).toHaveCount(TICKETS)
    await expect(notes.getByTestId('memory-notes-count')).toHaveText(String(TICKETS * 3))
    // Each list scrolls in its own region, so the lessons stand within a window or two of the page's top.
    const lessons = page.getByTestId('memory-lessons')
    const top = await lessons.evaluate((el) => el.getBoundingClientRect().top)
    expect(top).toBeLessThan(2000)
    expect(opened).toEqual([])

    // A ticket's notes are read when its row opens, and only that ticket's.
    const row = notes.getByTestId('memory-ticket-ABC-100')
    await row.getByRole('button', { name: /^Show \d+ notes$/u }).click()
    await expect(row.getByTestId('memory-2')).toBeVisible()
    expect(opened).toEqual(['ABC-100'])

    // Every lesson listed, and each the digest's cap leaves out says so; recording, it would be left out at use.
    const promoted = lessons.getByRole('region', { name: 'Lessons you promoted' })
    await expect(promoted.getByTestId(/^memory-\d+$/u)).toHaveCount(LESSONS)
    await expect(promoted.getByText('would be left out at use, past its cap')).toHaveCount(LESSONS - SERVED)
})

/** Serves the mock's memory, grown: its tickets' counts copied over hundreds of tickets, and its lesson hundreds of times. */
async function manyMemories(page: Page): Promise<void> {
    await page.route('**/api/memory', async (route) => {
        const response = await route.fetch()
        const mock = (await response.json()) as {
            tickets: { ticket_key: string; count: number; used: number; latest_at: string }[]
            lessons: { id: number; key: string }[]
            lessons_digest: { ids: number[]; left_out: number } | null
        }
        const [ticket] = mock.tickets
        const [lesson] = mock.lessons
        if (ticket === undefined || lesson === undefined || mock.lessons_digest === null) {
            throw new Error('the mock has no ticket with notes, or no lesson')
        }
        // ABC-100 stays, so its row opens to its real notes.
        const tickets = Array.from({ length: TICKETS }, (_, t) => ({
            ...ticket,
            ticket_key: t === 0 ? 'ABC-100' : `DEN-${t}`,
            count: 3,
        }))
        const lessons = Array.from({ length: LESSONS }, (_, l) => ({ ...lesson, id: 1000 + l, key: `lesson-${l}` }))
        const ids = lessons.slice(0, SERVED).map((l) => l.id)
        await route.fulfill({
            response,
            json: {
                ...mock,
                tickets,
                lessons,
                lessons_digest: { ...mock.lessons_digest, ids, left_out: LESSONS - SERVED },
            },
        })
    })
}
