import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// A workspace far past the mock's handful of memories: hundreds of tickets with notes in force, hundreds of lessons
// promoted, and the most proposals that wait at once. The memory page must keep each tier in reach, send counts rather
// than every note, and say which lessons the digest's cap leaves out.

const TICKETS = 300
const LESSONS = 200
// MAX_PENDING: past it, a new proposal is refused.
const PROPOSALS = 20
// The lessons the digest serves; the cap leaves out the rest.
const SERVED = 4

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test('the memory page lists a row a ticket, scrolls each list, and opens notes one ticket at a time', async ({
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
    await expect(notes.getByTestId('memory-notes-count')).toHaveText(`${TICKETS} tickets · ${TICKETS * 3} notes`)
    // Each list scrolls in its own region, so the tickets stand within a window or two of the page's top.
    const proposals = page.getByTestId('memory-proposals').getByRole('region', { name: 'Proposals' })
    await expect(proposals.getByTestId(/^memory-\d+$/u)).toHaveCount(PROPOSALS)
    expect(await proposals.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
    const lessons = page.getByTestId('memory-lessons')
    const top = await notes.evaluate((el) => el.getBoundingClientRect().top)
    expect(top).toBeLessThan(2000)
    expect(opened).toEqual([])

    // A ticket's notes are read when its row opens, and only that ticket's.
    const row = notes.getByTestId('memory-ticket-ABC-100')
    await row.getByRole('button', { name: /^Show \d+ notes$/u }).click()
    await expect(row.getByTestId('memory-2')).toBeVisible()
    expect(opened).toEqual(['ABC-100'])

    // Every lesson listed, and each the digest's cap leaves out says so; recording, it would be left out at use.
    const promoted = lessons.getByRole('region', { name: 'Lessons' })
    await expect(promoted.getByTestId(/^memory-\d+$/u)).toHaveCount(LESSONS)
    await expect(promoted.getByText('would be left out at use, past its cap')).toHaveCount(LESSONS - SERVED)
})

/**
 * Serves the mock's memory, grown: its ticket's counts over hundreds of tickets, its lesson hundreds of times, and its
 * proposal as many times as may wait.
 */
async function manyMemories(page: Page): Promise<void> {
    await page.route('**/api/memory', async (route) => {
        const response = await route.fetch()
        const mock = (await response.json()) as {
            tickets: { ticket_key: string; count: number; used: number; latest_at: string }[]
            lessons: { id: number; key: string; pinned_at: string | null }[]
            proposals: { entry: { id: number; key: string } }[]
            lessons_digest: { ids: number[]; left_out: number } | null
        }
        const [ticket] = mock.tickets
        // One not pinned, so the hundreds made from it list as the rest, unheaded, as most lessons are.
        const lesson = mock.lessons.find((l) => l.pinned_at === null)
        const [proposal] = mock.proposals
        if (ticket === undefined || lesson === undefined || proposal === undefined || mock.lessons_digest === null) {
            throw new Error('the mock has no ticket with notes, no lesson, or no proposal')
        }
        // ABC-100 stays, so its row opens to its real notes.
        const tickets = Array.from({ length: TICKETS }, (_, t) => ({
            ...ticket,
            ticket_key: t === 0 ? 'ABC-100' : `DEN-${t}`,
            count: 3,
        }))
        const lessons = Array.from({ length: LESSONS }, (_, l) => ({ ...lesson, id: 1000 + l, key: `lesson-${l}` }))
        const proposals = Array.from({ length: PROPOSALS }, (_, p) => ({
            ...proposal,
            entry: { ...proposal.entry, id: 2000 + p, key: `proposal-${p}` },
        }))
        const ids = lessons.slice(0, SERVED).map((l) => l.id)
        await route.fulfill({
            response,
            json: {
                ...mock,
                tickets,
                lessons,
                proposals,
                lessons_digest: { ...mock.lessons_digest, ids, left_out: LESSONS - SERVED },
            },
        })
    })
}
