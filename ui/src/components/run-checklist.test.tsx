import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ChecklistAnswer } from '@/api/types'
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
})
