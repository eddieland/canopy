import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { DiffFile, DiffLine, ReviewDiff, ReviewFinding } from '@/api/types'
import { DIFF_BUDGET } from '@/lib/review-folds'
import { placeFindings } from '@/lib/reviews'

import { FindingCard, ReviewDiffPanels } from './review-diff'
import type { Wanted } from './review-diff'

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
    return {
        severity: 'minor',
        title,
        location: `notes.txt:${line}`,
        detail: '',
        file: 0,
        line,
        dismissed: false,
        dismissed_reason: null,
        held: false,
        answer: null,
        answer_reason: null,
    }
}

function diff(
    findings: ReviewFinding[],
    { files = DIFF, wanted = null }: { files?: ReviewDiff; wanted?: Wanted | null } = {},
) {
    return (
        <QueryClientProvider client={new QueryClient()}>
            <ReviewDiffPanels run={4} diff={files} placed={placeFindings(findings, true)} wanted={wanted} />
        </QueryClientProvider>
    )
}

/** A file at `path` of one hunk of three added lines, `<path> 1` to `<path> 3`. */
function small(path: string): DiffFile {
    const lines = [1, 2, 3].map((n): DiffLine => ({ kind: 'add', old: null, new: n, text: `${path} ${n}` }))
    return { path, old_path: null, binary: false, hunks: [{ header: '', lines }] }
}

// Three files of two types, and one with none.
const SMALL: ReviewDiff = {
    truncated: false,
    files: [small('src/a.ts'), small('src/b.py'), small('src/c.ts'), small('Makefile')],
}

/** The paths of the files the page shows, in order. */
function shownPaths(): string[] {
    return screen
        .getAllByTestId('diff-file')
        .map((panel) => panel.querySelector('[title]')?.getAttribute('title') ?? '')
}

/** Folds the diff of the file at `i` on its header. */
function hideDiff(i: number) {
    fireEvent.click(
        within(screen.getAllByTestId('diff-file')[i] as HTMLElement).getByRole('button', { name: 'Hide diff' }),
    )
}

function openFilter() {
    fireEvent.pointerDown(screen.getByTestId('diff-file-types'), { button: 0, ctrlKey: false })
    return screen.getByRole('menu')
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

describe('ReviewDiffPanels folds', () => {
    it("folds a file's panel away on its header, and says what it folded", () => {
        const late = { ...finding('On b', 2), location: 'src/b.py:2', file: 1 }
        render(diff([late], { files: SMALL }))
        const b = screen.getAllByTestId('diff-file')[1]
        expect(b).toBeDefined()
        const panel = within(b as HTMLElement)
        expect(panel.getByText('src/b.py 2')).toBeDefined()

        fireEvent.click(panel.getByRole('button', { name: 'Hide diff' }))
        expect(panel.queryByText('src/b.py 2')).toBeNull()
        expect(panel.queryByRole('article')).toBeNull()
        expect(panel.getByText('3 lines and 1 finding folded away')).toBeDefined()
        // The others stay open.
        expect(screen.getByText('src/a.ts 1')).toBeDefined()

        fireEvent.click(panel.getByRole('button', { name: 'Show diff' }))
        expect(panel.getByText('src/b.py 2')).toBeDefined()
        expect(panel.getByRole('article').textContent).toContain('On b')
    })

    it('opens a folded file again whenever a link to a finding on it is followed, the same link again too', () => {
        const onB = { ...finding('On b', 2), location: 'src/b.py:2', file: 1 }
        const { rerender } = render(diff([onB], { files: SMALL }))
        hideDiff(1)
        expect(screen.queryByRole('article')).toBeNull()

        rerender(diff([onB], { files: SMALL, wanted: { file: 1 } }))
        expect(screen.getByRole('article').textContent).toContain('On b')

        // Folded again, and the same link followed again: a new object, so it opens again.
        hideDiff(1)
        expect(screen.queryByRole('article')).toBeNull()
        rerender(diff([onB], { files: SMALL, wanted: { file: 1 } }))
        expect(screen.getByRole('article').textContent).toContain('On b')
    })
})

describe('ReviewDiffPanels file types', () => {
    it("lists the diff's file types, every one ticked, and hides the files of one unticked", () => {
        render(diff([], { files: SMALL }))
        expect(screen.getByTestId('diff-file-types').textContent).toBe('All file types')
        const items = within(openFilter()).getAllByRole('menuitemcheckbox')
        expect(items.map((item) => item.getAttribute('aria-label'))).toStrictEqual([
            '.py, 1 file',
            '.ts, 2 files',
            'no extension, 1 file',
        ])
        expect(items.every((item) => item.getAttribute('aria-checked') === 'true')).toBe(true)

        fireEvent.click(items[1] as HTMLElement)
        // The menu stays open, so another flips in the same go.
        expect(within(screen.getByRole('menu')).getAllByRole('menuitemcheckbox')[1]?.getAttribute('aria-checked')).toBe(
            'false',
        )
        expect(shownPaths()).toStrictEqual(['src/b.py', 'Makefile'])
        expect(screen.getByTestId('diff-file-types').textContent).toBe('2 of 3 file types')
        expect(screen.getByTestId('diff-hidden-files').textContent).toBe('2 files hidden by type')

        fireEvent.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Show every type' }))
        expect(shownPaths()).toStrictEqual(['src/a.ts', 'src/b.py', 'src/c.ts', 'Makefile'])
        expect(screen.queryByTestId('diff-hidden-files')).toBeNull()
    })

    it("ticks a hidden file's type again when a link names a finding on it", () => {
        const onA = { ...finding('On a', 1), location: 'src/a.ts:1', file: 0 }
        const { rerender } = render(diff([onA], { files: SMALL }))
        const menu = openFilter()
        fireEvent.click(within(menu).getAllByRole('menuitemcheckbox')[1] as HTMLElement)
        fireEvent.keyDown(menu, { key: 'Escape' })
        expect(screen.queryByRole('menu')).toBeNull()
        expect(shownPaths()).toStrictEqual(['src/b.py', 'Makefile'])

        rerender(diff([onA], { files: SMALL, wanted: { file: 0 } }))
        expect(shownPaths()).toStrictEqual(['src/a.ts', 'src/b.py', 'src/c.ts', 'Makefile'])
        expect(screen.getByRole('article').textContent).toContain('On a')
    })
})

describe('ReviewDiffPanels file types and folds', () => {
    it(
        'keeps the lines opened in a file the filter hid, for when it comes back',
        {
            timeout: 30_000,
        },
        () => {
            render(diff([]))
            fireEvent.click(screen.getByRole('button', { name: 'Show 100 hidden lines' }))
            expect(screen.getByText(`line ${LINES}`)).toBeDefined()

            const menu = openFilter()
            fireEvent.click(within(menu).getByRole('menuitemcheckbox'))
            expect(screen.queryAllByTestId('diff-file')).toHaveLength(0)
            fireEvent.click(within(menu).getByRole('menuitemcheckbox'))
            fireEvent.keyDown(menu, { key: 'Escape' })

            expect(screen.getByText(`line ${LINES}`)).toBeDefined()
            expect(screen.queryByRole('button', { name: 'Show 100 hidden lines' })).toBeNull()
        },
    )
})

describe('FindingCard', () => {
    it('marks a finding canopy holds for the operator, and shows what the worker answered of one', () => {
        const held = { ...finding('log line is noisy', 2), held: true }
        const answered = {
            ...finding('retry never stops', 1),
            answer: 'declined' as const,
            answer_reason: 'By design.',
        }
        render(
            <QueryClientProvider client={new QueryClient()}>
                <FindingCard run={5} numbered={{ n: 1, finding: held }} />
                <FindingCard run={4} numbered={{ n: 2, finding: answered }} />
            </QueryClientProvider>,
        )
        const [first, second] = screen.getAllByTestId('finding')
        expect(within(first as HTMLElement).getByText('held for you')).toBeTruthy()
        expect(within(first as HTMLElement).queryByTestId('finding-answer')).toBeNull()
        expect(within(second as HTMLElement).queryByText('held for you')).toBeNull()
        expect(within(second as HTMLElement).getByTestId('finding-answer').textContent).toBe(
            'The worker answered: declinedBy design.',
        )
    })
})
