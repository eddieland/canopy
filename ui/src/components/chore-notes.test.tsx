import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockChores } from '@/api/mocks'
import type { ChoreDetail, ChoreSummary, Message } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { ChoreNotes } from './chore-notes'

afterEach(() => {
    cleanup()
    localStorage.clear()
})

// The chore's latest run started at 08:00.
const CHORE = mockChores[0] as ChoreSummary

function note(id: number, at: string, body: string): Message {
    return {
        id,
        at,
        body,
        source: 'operator',
        kind: 'reply',
        channel: 'web',
        answers: null,
        run_id: null,
        comment: null,
    }
}

const READ = note(6, '2026-10-08T07:00:00Z', 'Ignore dev dependencies.')
const UNREAD = note(8, '2026-10-08T09:00:00Z', 'The lodash advisory is known; skip it.')

function renderNotes(notes: Message[]) {
    const detail: ChoreDetail = { chore: CHORE, notes, runs: [] }
    // Nothing is fetched: a chore's notes say which its next run reads, not which a tick read.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    return renderRouted(<ChoreNotes detail={detail} />, { client })
}

// Each note's text, in the order shown.
function shown(): string[] {
    return within(screen.getByTestId('conversation'))
        .getAllByRole('listitem')
        .map((item) => item.textContent)
}

describe('ChoreNotes', () => {
    it('says its runs follow the prompt file alone without notes, and offers no order for fewer than two', async () => {
        const { unmount } = await renderNotes([])
        expect(screen.getByText('no notes yet: its runs follow its prompt file alone')).toBeDefined()
        expect(screen.queryByRole('button', { name: /first/u })).toBeNull()
        unmount()

        await renderNotes([READ])
        expect(screen.queryByRole('button', { name: /first/u })).toBeNull()
    })

    it('marks the notes no run has read yet, which the next run reads as an instruction', async () => {
        await renderNotes([READ, UNREAD])
        const why = 'No run of this chore has read it yet. Its next run does, as an instruction.'
        expect(within(screen.getByTestId('message-8')).getByTitle(why).textContent).toBe('waiting for the next run')
        expect(screen.getAllByText('waiting for the next run')).toHaveLength(1)
    })

    it('lists the notes oldest first, and newest first once flipped', async () => {
        await renderNotes([READ, UNREAD])
        expect(shown()).toEqual([expect.stringContaining(READ.body), expect.stringContaining(UNREAD.body)])
        fireEvent.click(screen.getByRole('button', { name: 'oldest first: show newest first' }))
        expect(shown()).toEqual([expect.stringContaining(UNREAD.body), expect.stringContaining(READ.body)])
    })
})
