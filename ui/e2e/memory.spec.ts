import { expect, test } from '@playwright/test'

import { settled, signIn } from './helpers.ts'

// The mock journal has ticket notes in use and lessons recording (canopy/serve/mock.py, `_memory`).

test.beforeEach(async ({ page }) => {
    await signIn(page)
})

test("the header says memory is in use, each tier's mode in words, and opens the memory page", async ({ page }) => {
    await page.goto('attention')
    await settled(page)
    const readout = page.getByTestId('memory-readout')
    await expect(readout).toHaveText('memory: in use')
    await expect(readout).toHaveAttribute('title', 'ticket notes: in use, lessons: recording')
    await expect(readout).toHaveAccessibleName('memory: in use: ticket notes: in use, lessons: recording')
    await readout.click()
    await expect(page).toHaveURL(/\/memory$/u)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Memory')
})

test('the memory page heads each tier with what reads it, and shows what a worker wrote plainly', async ({ page }) => {
    await page.goto('memory')
    await settled(page)
    const notes = page.getByTestId('memory-notes')
    await expect(notes.getByTestId('memory-band')).toHaveText(
        "ticket notes: in useIn use. A ticket's later runs read its notes.",
    )
    // One row a ticket, the newest note's first, each opening to its notes in force.
    await expect(notes.getByTestId(/^memory-ticket-/u)).toHaveCount(2)
    await expect(notes.getByTestId('memory-notes-count')).toHaveText('2 tickets · 3 notes')
    const ticket = notes.getByTestId('memory-ticket-ABC-100')
    // Named by its title as every list names a ticket; no run has relied on its notes, so no use is shown.
    await expect(ticket.getByTitle('Fix the flaky checkout test')).toBeVisible()
    await expect(ticket).not.toContainText('used by')
    await expect(ticket.getByTestId('memory-3')).toHaveCount(0)
    await ticket.getByRole('button', { name: 'Show 2 notes' }).click()
    // Written to the journal by hand, past the bounds: its link is text, and its zero-width space is named.
    const cache = ticket.getByTestId('memory-3')
    await expect(cache).toContainText('[package-lock.json](https://evil.example/lock)<U+200B>, so a bumped')
    await expect(cache.getByRole('link', { name: /evil/u })).toHaveCount(0)
    await expect(cache.getByTestId('memory-stand')).toHaveText('active')

    // What waits on the operator heads the page, counted as the nav counts it.
    const proposals = page.getByTestId('memory-proposals')
    await expect(page.getByTestId(/^memory-(proposals|lessons|notes)$/u)).toHaveCount(3)
    await expect(page.getByTestId(/^memory-(proposals|lessons|notes)$/u).first()).toHaveAttribute(
        'data-testid',
        'memory-proposals',
    )
    await expect(proposals.getByTestId('memory-proposals-count')).toHaveText('2')
    // A private ticket's run's proposal says so in a word, and why on hover.
    await expect(
        proposals.getByTestId('memory-6').getByTitle('its run worked a private ticket', { exact: false }),
    ).toHaveText('private')
    // It is under lesson 8's key too, so it says what it would replace, and only the form promotes it.
    await expect(proposals.getByTestId('memory-6').getByTestId('proposal-replaces')).toHaveText('replaces memory:8')
    await expect(proposals.getByTestId('memory-6').getByRole('button', { name: 'Promote as written' })).toHaveCount(0)

    const lessons = page.getByTestId('memory-lessons')
    await expect(lessons.getByTestId('memory-band')).toHaveText(
        'lessons: recordingRecording only. Workers propose lessons and you may promote them; no run reads them.',
    )
    await expect(lessons.getByTestId('memory-lessons-count')).toHaveText('1')
    // Recording, so the lesson in force reads as recorded: no run reads it.
    await expect(lessons.getByTestId('memory-8').getByTestId('memory-stand')).toHaveText('recorded')
    // What every run would be served is folded until asked for.
    await expect(lessons.getByTestId('memory-digest')).toHaveCount(0)
    await lessons.getByRole('button', { name: 'Show what every run would be served at use' }).click()
    await expect(lessons.getByTestId('memory-digest')).toContainText('Lesson 8, `billing-client`, for `web`:')
})

test("a ticket's page lists its notes and what its next run gets", async ({ page }) => {
    await page.goto('tickets/ABC-100')
    await settled(page)
    const panel = page.getByTestId('ticket-memory')
    await expect(panel.getByTestId('memory-band')).toContainText('In use.')
    await expect(panel.getByTestId('memory-1')).toContainText('superseded')
    // A note names the runs that relied on it, each opening its page.
    await expect(panel.getByTestId('memory-1')).toContainText('used in run:40')
    await expect(panel.getByTestId('memory-1').getByRole('link', { name: 'run:40' })).toHaveAttribute(
        'href',
        /\/runs\/40$/u,
    )
    await expect(panel.getByText('served to its next run')).toBeVisible()
    await expect(panel.getByTestId('memory-digest')).toContainText('## Notes from earlier runs')
})

test('a run says what it wrote, what it read, and what was refused, and recording apart from empty', async ({
    page,
}) => {
    await page.goto('runs/40')
    await settled(page)
    const run = page.getByTestId('run-memory')
    // Folded on arrival: its header counts what it wrote and read, each tier's mode for the run on hover.
    const said = run.getByTestId('run-memory-said')
    await expect(said).toContainText('wrote 2 · read 1 · refused 1')
    await expect(said).toHaveAttribute('title', 'ticket notes: in use, lessons: recording')
    await expect(run.getByTestId('memory-2')).toHaveCount(0)
    await run.getByRole('button', { name: 'Show memory' }).click()
    await expect(run.getByTestId('memory-2')).toBeVisible()
    await expect(run.getByTestId('memory-1')).toContainText('this run relied on it')
    await expect(run.getByTestId('memory-1')).not.toContainText('used in')
    await expect(run.getByTestId('memory-refused')).toHaveText(
        'notes staging-login: its text looks like it holds a secret',
    )

    await page.goto('runs/37')
    await settled(page)
    await expect(page.getByTestId('run-memory-said')).toContainText('read none, recording only')

    // Rendered with memory off: no panel at all.
    await page.goto('runs/41')
    await settled(page)
    await expect(page.getByTestId('run-memory')).toHaveCount(0)
})

test('the memory page narrows every panel by words, a repository, and a lesson’s standing, kept in the URL', async ({
    page,
}) => {
    await page.goto('memory')
    await settled(page)
    const proposals = page.getByTestId('memory-proposals')
    const lessons = page.getByTestId('memory-lessons')
    const notes = page.getByTestId('memory-notes')

    await page.getByRole('searchbox', { name: 'Filter memory by key, text, ticket, or repository' }).fill('billing')
    await expect(page).toHaveURL(/[?&]q=billing/u)
    // Proposal 6 is under lesson 8's key, `billing-client`, so it holds the word too.
    await expect(proposals.getByTestId('memory-proposals-count')).toHaveText('1 of 2')
    await expect(proposals.getByTestId('memory-6')).toBeVisible()
    await expect(lessons.getByTestId('memory-8')).toBeVisible()
    await expect(
        notes.getByText('no note says “billing”, and no ticket with notes has it in its key or title'),
    ).toBeVisible()

    await page.getByRole('navigation', { name: 'Filter by repository' }).getByRole('link', { name: 'api' }).click()
    await expect(page).toHaveURL(/[?&]repo=api/u)
    await expect(notes.getByTestId('memory-notes-every-repo')).toBeVisible()
    await expect(lessons.getByText('no lessons with “billing” for api')).toBeVisible()

    // Back to everything: the chips and the field undo it.
    await page
        .getByRole('navigation', { name: 'Filter by repository' })
        .getByRole('link', { name: 'every repository' })
        .click()
    await page.getByRole('button', { name: 'Clear the filter' }).click()
    await expect(proposals.getByTestId('memory-proposals-count')).toHaveText('2')

    // The proposals flip, the newest first.
    await expect(proposals.getByTestId(/^memory-\d+$/u).first()).toHaveAttribute('data-testid', 'memory-5')
    await proposals.getByTestId('order-memory-proposals').click()
    await expect(proposals.getByTestId(/^memory-\d+$/u).first()).toHaveAttribute('data-testid', 'memory-6')
})

test('opened notes line up with the lessons, and the tickets with notes flip', async ({ page }) => {
    await page.goto('memory')
    await settled(page)
    const notes = page.getByTestId('memory-notes')
    await notes.getByTestId('memory-ticket-ABC-100').getByRole('button', { name: 'Show 2 notes' }).click()
    const noteKey = notes.getByTestId('memory-3').getByText('ci-cache', { exact: true })
    const lessonKey = page.getByTestId('memory-8').getByText('billing-client', { exact: true })
    const [a, b] = [await noteKey.boundingBox(), await lessonKey.boundingBox()]
    expect(Math.abs((a?.x ?? 0) - (b?.x ?? 1))).toBeLessThan(1)

    const rows = notes.getByTestId(/^memory-ticket-/u)
    await expect(rows.first()).toHaveAttribute('data-testid', 'memory-ticket-ABC-102')
    await notes.getByTestId('order-memory-tickets').click()
    await expect(rows.first()).toHaveAttribute('data-testid', 'memory-ticket-ABC-100')
})

test('the memory page shows its history on asking: the proposal promotion used up', async ({ page }) => {
    await page.goto('memory')
    await settled(page)
    const proposals = page.getByTestId('memory-proposals')
    await expect(proposals.getByTestId('memory-past-decided')).toHaveCount(0)
    await proposals.getByRole('link', { name: 'history' }).click()
    await expect(page).toHaveURL(/[?&]history=true/u)
    // The mock's lesson 8 was promoted from proposal 7, which promoting superseded.
    const decided = proposals.getByTestId('memory-past-decided')
    await expect(decided.getByTestId('memory-7').getByTestId('memory-stand')).toHaveText('superseded')
    await expect(page.getByTestId('memory-lessons').getByText('no lesson replaced or forgotten yet')).toBeVisible()
})

test('the memory page finds a note by what it says, as canopy memory search does', async ({ page }) => {
    await page.goto('memory')
    await settled(page)
    await page.getByRole('searchbox', { name: 'Filter memory by key, text, ticket, or repository' }).fill('lockfile')
    // Neither ticket's key nor title holds the word; ABC-100's note ci-cache does.
    const found = page.getByTestId('memory-notes-found')
    await expect(found.getByTestId('memory-3')).toContainText('ci-cache')
    await expect(found.getByTestId('memory-3').getByRole('link', { name: 'ABC-100', exact: true })).toBeVisible()
})
