import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { DiffLine, ReviewDiff, ReviewFinding } from '@/api/types'
import { DIFF_BUDGET } from '@/lib/review-folds'
import { placeFindings } from '@/lib/reviews'

import { ReviewDiffPanels } from './review-diff'

afterEach(() => {
    cleanup()
})

// One file of 100 lines more than the page draws at first, every line added, in a language canopy does not highlight.
const LINES = DIFF_BUDGET.page + 100
const DIFF: ReviewDiff = {
    truncated: false,
    files: [
        {
            path: 'notes.txt',
            old_path: null,
            binary: false,
            hunks: [
                {
                    header: '',
                    lines: Array.from({ length: LINES }, (_, i): DiffLine => ({
                        kind: 'add',
                        old: null,
                        new: i + 1,
                        text: `line ${i + 1}`,
                    })),
                },
            ],
        },
    ],
}

function finding(title: string, line: number): ReviewFinding {
    return { severity: 'minor', title, location: `notes.txt:${line}`, detail: '', file: 0, line, dismissed: false }
}

function diff(findings: ReviewFinding[]) {
    return (
        <QueryClientProvider client={new QueryClient()}>
            <ReviewDiffPanels run={4} diff={DIFF} placed={placeFindings(findings, true)} />
        </QueryClientProvider>
    )
}

describe('ReviewDiffPanels', () => {
    // Each render draws as many lines as the page does at first: seconds in happy-dom, close to the default's five.
    it(
        'draws a finding that arrives after the diff, on a line it had folded, and keeps the folds opened',
        {
            timeout: 30_000,
        },
        () => {
            // A running review: its diff, and no findings yet.
            const { rerender } = render(diff([]))
            expect(screen.queryByRole('article')).toBeNull()
            expect(screen.getByRole('button', { name: 'Show 100 hidden lines' })).toBeDefined()

            // It ends with a finding on a line past those drawn: the card shows, its line among ten either side,
            // and the first lines drawn give up the room they take.
            rerender(diff([finding('A late finding', LINES - 50)]))
            expect(screen.getByRole('article').textContent).toContain('A late finding')
            expect(screen.getByText(`line ${LINES - 50}`)).toBeDefined()
            fireEvent.click(screen.getByRole('button', { name: 'Show 60 hidden lines' }))
            expect(screen.getByText(`line ${DIFF_BUDGET.page + 1}`)).toBeDefined()

            // The next tick reads the review again: what the operator opened stays open.
            rerender(diff([finding('A late finding', LINES - 50)]))
            expect(screen.queryByRole('button', { name: 'Show 60 hidden lines' })).toBeNull()
            expect(screen.getByRole('button', { name: 'Show 40 hidden lines' })).toBeDefined()
        },
    )
})
