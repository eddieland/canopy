import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ChecklistAnswer, ChecklistStretch, ReviewDiff } from '@/api/types'
import { tipOf } from '@/test-utils'

import { ChecklistPanel } from './run-checklist'

afterEach(() => {
    cleanup()
})

function answer(repo: string, item: string, said: ChecklistAnswer['answer'], reason: string | null = null) {
    return { repo, item, answer: said, reason }
}

// The worker's words: markup in them stays its characters.
const REASON = 'The CSV writer sits beside the export route. <img src=x onerror=alert(1)>'

// The branch's text, in a language canopy does not highlight: markup in it stays its characters too.
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
                    lines: [
                        { kind: 'del', old: 1, new: null, text: 'queryKey inline' },
                        { kind: 'add', old: null, new: 1, text: 'invoiceLinesQuery(id) <img src=x onerror=alert(1)>' },
                    ],
                },
            ],
        },
    ],
}

function stretch(repo: string, diff: ReviewDiff | null, removed: number | null = null): ChecklistStretch {
    return {
        repo,
        shown_sha: '5b1e0c47aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        pushed_sha: 'c9d24f83bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        diff,
        diff_removed_after_days: removed,
    }
}

describe('ChecklistPanel', () => {
    it("lists one list's items in its order, its repository in the readout, a held item's reason under it", () => {
        render(
            <ChecklistPanel
                answers={[
                    answer('api', 'general-types', 'pass'),
                    answer('api', 'newspaper-order', 'held', REASON),
                    answer('api', 'doc-comments', 'n/a'),
                ]}
            />,
        )
        expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Checklist')
        expect(screen.getByTestId('run-checklist-said').textContent).toBe('api · 1 pass · 1 held · 1 n/a')
        // One list needs no heading of its repository's.
        expect(screen.queryByRole('heading', { level: 3 })).toBeNull()
        const rows = screen.getAllByTestId('checklist-answer')
        expect(rows.map((r) => r.textContent)).toEqual([
            'passgeneral-types',
            `heldnewspaper-order${REASON}`,
            'n/adoc-comments',
        ])
        expect(document.querySelector('img')).toBeNull()
        expect(tipOf(within(rows[1] as HTMLElement).getByText('held'))).toBe(
            'held\nThe diff does not, and the run left it so, for the reason under it',
        )
    })

    it("puts a joint run's lists each under its repository's name", () => {
        render(
            <ChecklistPanel
                answers={[
                    answer('api', 'general-types', 'fixed'),
                    answer('web', 'no-any', 'pass'),
                    answer('web', 'query-keys', 'unanswered'),
                ]}
            />,
        )
        expect(screen.getByTestId('run-checklist-said').textContent).toBe(
            '2 repositories · 1 pass · 1 fixed · 1 unanswered',
        )
        expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['api', 'web'])
        const web = screen.getByRole('region', { name: "web's checklist" })
        expect(
            within(web)
                .getAllByTestId('checklist-answer')
                .map((r) => r.textContent),
        ).toEqual(['passno-any', 'unansweredquery-keys'])
    })

    it('shows nothing for a run given no list', () => {
        const { container } = render(<ChecklistPanel answers={[]} />)
        expect(container.innerHTML).toBe('')
    })

    it('shows each stretch the run pushed after its list under the answers, its diff in the diff panels', () => {
        render(
            <ChecklistPanel
                answers={[answer('web', 'query-keys', 'fixed')]}
                stretches={[stretch('web', DIFF)]}
                shownBy="run:38"
            />,
        )
        const shown = screen.getByRole('region', { name: 'Pushed after the list: web · 5b1e0c4..c9d24f8' })
        // Its panel, then a panel per file of the diff, as a review's diff has.
        expect(
            within(shown)
                .getAllByRole('heading', { level: 2 })
                .map((h) => h.textContent),
        ).toEqual(['Pushed after the list', 'File'])
        expect(within(shown).getByTestId('checklist-stretch-range').textContent).toBe('web · 5b1e0c4..c9d24f8')
        const [file] = within(shown).getAllByTestId('diff-file')
        expect(within(file as HTMLElement).getByTitle('notes.txt')).toBeDefined()
        expect(
            within(file as HTMLElement).getByText('invoiceLinesQuery(id) <img src=x onerror=alert(1)>'),
        ).toBeDefined()
        expect(document.querySelector('img')).toBeNull()
        // After the answers, which it is read against.
        const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
        expect(headings).toEqual(['Checklist', 'Pushed after the list', 'File'])
        expect(screen.queryByTestId('checklist-stretches-left-out')).toBeNull()
    })

    it("puts a joint run's stretches each under its repository, in the order the run was shown its lists", () => {
        render(
            <ChecklistPanel
                answers={[answer('api', 'general-types', 'fixed'), answer('web', 'no-any', 'fixed')]}
                stretches={[stretch('api', DIFF), stretch('web', DIFF)]}
                shownBy="run:38"
            />,
        )
        expect(screen.getAllByTestId('checklist-stretch-range').map((r) => r.textContent)).toEqual([
            'api · 5b1e0c4..c9d24f8',
            'web · 5b1e0c4..c9d24f8',
        ])
        expect(screen.getAllByTestId('diff-file')).toHaveLength(2)
    })

    it('says a stretch whose diff is missing, removed, or empty is so, rather than leaving it out', () => {
        render(
            <ChecklistPanel
                answers={[answer('web', 'no-any', 'fixed')]}
                stretches={[
                    stretch('web', null),
                    stretch('web', null, 30),
                    stretch('web', { truncated: false, files: [] }),
                ]}
                leftOut={2}
                shownBy="task:4"
            />,
        )
        const stretches = screen.getAllByTestId('checklist-stretch').map((s) => s.textContent)
        expect(stretches).toEqual([
            expect.stringContaining('no diff kept for this stretch'),
            expect.stringContaining('removed after 30 days, as your [retention] keeps it'),
            expect.stringContaining('no change: the run pushed the commit it was shown the list at'),
        ])
        expect(screen.queryAllByTestId('diff-file')).toHaveLength(0)
        expect(screen.getByTestId('checklist-stretches-left-out').textContent).toBe(
            "2 more stretches pushed after the list, not shown: canopy show task:4 names each one's diff",
        )
    })
})
