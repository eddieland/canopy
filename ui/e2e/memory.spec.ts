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
    await expect(notes.getByTestId('memory-notes-count')).toHaveText('3')
    const ticket = notes.getByTestId('memory-ticket-ABC-100')
    await expect(ticket).toContainText('read by no run')
    await expect(ticket.getByTestId('memory-3')).toHaveCount(0)
    await ticket.getByRole('button', { name: 'Show 2 notes' }).click()
    // Written to the journal by hand, past the bounds: its link is text, and its zero-width space is named.
    const cache = ticket.getByTestId('memory-3')
    await expect(cache).toContainText('[package-lock.json](https://evil.example/lock)<U+200B>, so a bumped')
    await expect(cache.getByRole('link', { name: /evil/u })).toHaveCount(0)
    await expect(cache).toContainText('read by no run')

    const lessons = page.getByTestId('memory-lessons')
    await expect(lessons.getByTestId('memory-band')).toHaveText(
        'lessons: recordingRecording only. Workers propose lessons and you may promote them; no run reads them.',
    )
    await expect(lessons.getByTestId('memory-6')).toContainText(
        'private: its text may hold what you kept off the tracker',
    )
    await expect(lessons.getByText('would be served at use')).toBeVisible()
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
    await expect(run).toContainText('ticket notes in use, lessons recording')
    await expect(run.getByTestId('memory-2')).toBeVisible()
    await expect(run.getByTestId('memory-1')).toContainText('this run relied on it')
    await expect(run.getByTestId('memory-1')).not.toContainText('used in')
    await expect(run.getByTestId('memory-refused')).toHaveText(
        'notes staging-login: its text looks like it holds a secret',
    )

    await page.goto('runs/37')
    await settled(page)
    await expect(page.getByTestId('run-memory')).toContainText('none, recording only')

    // Rendered with memory off: no panel at all.
    await page.goto('runs/41')
    await settled(page)
    await expect(page.getByTestId('run-memory')).toHaveCount(0)
})
