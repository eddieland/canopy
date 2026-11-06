import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { mockEpics } from '@/api/mocks'
import type { EpicSummary } from '@/api/types'
import { parseFilled, STORAGE_KEY } from '@/lib/filled-epics'
import { breakStorage } from '@/test-utils'

import { EntriesFiled } from './epic-filed'

// Epic 1, approved, with 2 of its 4 entries filed.
const EPIC = mockEpics.find((epic) => epic.id === 1) as EpicSummary

/** Epic 1 with `filed` of its 4 entries filed. */
function filed(filled: number, epic: EpicSummary = EPIC): EpicSummary {
    return { ...epic, entries_with_members: filled }
}

beforeEach(() => localStorage.clear())
afterEach(cleanup)

describe('EntriesFiled', () => {
    it('reads how much is filed, and plays nothing while an entry has no member', () => {
        render(<EntriesFiled epic={filed(3)} />)
        expect(screen.getByTestId('entries-filed').textContent).toBe('3 of 4 entries filed')
        expect(screen.queryByTestId('leaf')).toBeNull()
        expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    })

    it('plays once the last entry is filed while the page shows it, lit, dropping a leaf hidden from a reader', () => {
        const { rerender } = render(<EntriesFiled epic={filed(3)} />)
        rerender(<EntriesFiled epic={filed(4)} />)
        const readout = screen.getByTestId('entries-filed')
        expect(readout.textContent).toBe('4 of 4 entries filed')
        expect(screen.getByTestId('leaf').getAttribute('aria-hidden')).toBe('true')
        expect(parseFilled(localStorage.getItem(STORAGE_KEY))).toEqual([1])
    })

    it('plays on the first visit after it filled, and never again, on this page or a later one', () => {
        const { rerender } = render(<EntriesFiled epic={filed(4)} />)
        expect(screen.getAllByTestId('leaf')).toHaveLength(1)
        // A member removed and filed again while the page is open plays it to its end once, never anew.
        rerender(<EntriesFiled epic={filed(3)} />)
        rerender(<EntriesFiled epic={filed(4)} />)
        expect(screen.getAllByTestId('leaf')).toHaveLength(1)
        cleanup()

        render(<EntriesFiled epic={filed(4)} />)
        expect(screen.getByTestId('entries-filed').textContent).toBe('4 of 4 entries filed')
        expect(screen.queryByTestId('leaf')).toBeNull()
    })

    it('keeps each epic its own: another full one still plays', () => {
        render(<EntriesFiled epic={filed(4)} />)
        cleanup()
        render(<EntriesFiled epic={{ ...filed(3), id: 7, entries: 3 }} />)
        expect(screen.getByTestId('leaf')).toBeTruthy()
        expect(parseFilled(localStorage.getItem(STORAGE_KEY))).toEqual([7, 1])
    })

    it('never reads a proposed breakdown, or none, as full', () => {
        for (const epic of mockEpics) {
            render(<EntriesFiled epic={epic} />)
        }
        expect(screen.queryByTestId('leaf')).toBeNull()
    })

    it('plays once on this page where storage is unavailable, and breaks nothing', () => {
        breakStorage()
        const { rerender } = render(<EntriesFiled epic={filed(4)} />)
        rerender(<EntriesFiled epic={filed(4)} />)
        expect(screen.getAllByTestId('leaf')).toHaveLength(1)
    })
})

describe('parseFilled', () => {
    it('reads the epics stored, dropping what is not an id, and nothing from what is not a list', () => {
        expect(parseFilled('[3, 1]')).toEqual([3, 1])
        expect(parseFilled('[3, "1", 0, -2, 1.5, null]')).toEqual([3])
        expect(parseFilled(null)).toEqual([])
        expect(parseFilled('not json')).toEqual([])
        expect(parseFilled('{"1": true}')).toEqual([])
    })

    it('keeps every epic stored, so none that played long ago plays again', () => {
        const many = Array.from({ length: 1000 }, (_, i) => i + 1)
        expect(parseFilled(JSON.stringify(many))).toEqual(many)
    })
})
