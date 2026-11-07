import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ReviewDiff, RunChange, RunRange } from '@/api/types'

import { RunChangesPanel } from './run-changes'

afterEach(() => {
    cleanup()
})

const START = '5b1e0c47aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const END = 'c9d24f83bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
const LEFT = 'd8e61b30cccccccccccccccccccccccccccccccc'

// The branch's text, in a language canopy does not highlight: markup in it stays its characters.
function diffOf(...paths: string[]): ReviewDiff {
    return {
        truncated: false,
        files: paths.map((path) => ({
            path,
            old_path: null,
            binary: false,
            hunks: [
                {
                    header: '',
                    lines: [
                        { kind: 'del', old: 1, new: null, text: 'queryKey inline' },
                        { kind: 'add', old: null, new: 1, text: `${path} <img src=x onerror=alert(1)>` },
                    ],
                },
            ],
        })),
    }
}

function range(repo: string, fields: Partial<RunRange> = {}): RunRange {
    return { repo, start_sha: START, start_on_base: false, end_sha: END, unpushed_sha: null, ...fields }
}

function change(repo: string, fields: Partial<RunChange> = {}, ranged: Partial<RunRange> = {}): RunChange {
    return {
        range: range(repo, ranged),
        merge_base_sha: null,
        diff: diffOf('own.txt'),
        branch_diff: diffOf('earlier.txt', 'own.txt'),
        missing: null,
        removed_after_days: null,
        ...fields,
    }
}

function files(): string[] {
    return screen.getAllByTestId('diff-file').map((f) => within(f).getAllByTitle(/\.txt$/u)[0]?.title ?? '')
}

describe('RunChangesPanel', () => {
    it('shows the run’s own change, its repository and commits in the readout, and toggles to the branch', () => {
        render(<RunChangesPanel changes={[change('web')]} records />)
        const shown = screen.getByRole('region', { name: 'Diff: web · 5b1e0c4..c9d24f8' })
        expect(within(shown).getByTestId('run-change-range').textContent).toBe('web · 5b1e0c4..c9d24f8')
        expect(within(shown).getByText(/^What this run changed, from the commit origin's branch/u)).toBeDefined()
        expect(files()).toEqual(['own.txt'])
        // The branch's text stays text.
        expect(screen.getByText('own.txt <img src=x onerror=alert(1)>')).toBeDefined()
        expect(document.querySelector('img')).toBeNull()
        expect(screen.queryByTestId('run-change-unpushed')).toBeNull()

        fireEvent.click(screen.getByRole('radio', { name: 'Branch vs base' }))
        expect(files()).toEqual(['earlier.txt', 'own.txt'])
        expect(screen.getByText(/^The whole branch against its base/u)).toBeDefined()
        // Pressing the one shown keeps it.
        fireEvent.click(screen.getByRole('radio', { name: 'Branch vs base' }))
        expect(files()).toEqual(['earlier.txt', 'own.txt'])
        fireEvent.click(screen.getByRole('radio', { name: 'This run' }))
        expect(files()).toEqual(['own.txt'])
    })

    it('says an unpushed run’s diff is of work not on origin, its range running to the commit it left', () => {
        render(<RunChangesPanel changes={[change('web', {}, { end_sha: START, unpushed_sha: LEFT })]} records />)
        expect(screen.getByTestId('run-change-range').textContent).toBe('web · 5b1e0c4..d8e61b3')
        expect(screen.getByText('not on origin')).toBeDefined()
        expect(screen.getByTestId('run-change-unpushed').textContent).toMatch(/^Work not on origin/u)
        expect(screen.getByText(/to the last commit it made in its slot\.$/u)).toBeDefined()
        expect(files()).toEqual(['own.txt'])
    })

    it('puts a joint run’s changes each under its repository, only the unpushed one marked', () => {
        render(
            <RunChangesPanel
                changes={[change('api'), change('web', {}, { end_sha: START, unpushed_sha: LEFT })]}
                records
            />,
        )
        expect(screen.getAllByTestId('run-change-range').map((r) => r.textContent)).toEqual([
            'api · 5b1e0c4..c9d24f8',
            'web · 5b1e0c4..d8e61b3',
        ])
        const api = screen.getByRole('region', { name: 'Diff: api · 5b1e0c4..c9d24f8' })
        expect(within(api).queryByText('not on origin')).toBeNull()
        expect(screen.getAllByTestId('run-change-unpushed')).toHaveLength(1)
        // Each toggles alone.
        fireEvent.click(within(api).getByRole('radio', { name: 'Branch vs base' }))
        expect(files()).toEqual(['earlier.txt', 'own.txt', 'own.txt'])
    })

    it('says why a diff was not kept, or that retention removed it, rather than showing nothing', () => {
        render(
            <RunChangesPanel
                changes={[
                    change(
                        'api',
                        { diff: null, branch_diff: null, missing: 'the run crashed, so canopy kept no diff' },
                        { start_sha: null, end_sha: null },
                    ),
                    change('mobile', { diff: null, branch_diff: null, removed_after_days: 30 }),
                    change('web', { diff: null, missing: 'its own change: git diff exited 128: bad object' }),
                ]}
                records
            />,
        )
        const [crashed, removed, half] = screen.getAllByTestId('run-change')
        expect(within(crashed as HTMLElement).getByTestId('run-change-range').textContent).toBe('api · nothing read')
        expect(crashed?.textContent).toContain('no diff kept: the run crashed, so canopy kept no diff')
        // Nothing to toggle to.
        expect(within(crashed as HTMLElement).queryByRole('radio')).toBeNull()
        expect(removed?.textContent).toContain('removed after 30 days, as your [retention] keeps it')
        expect(half?.textContent).toContain('no diff kept: its own change: git diff exited 128: bad object')
        expect(screen.queryAllByTestId('diff-file')).toHaveLength(0)
        // The branch's diff was kept: a toggle away.
        fireEvent.click(within(half as HTMLElement).getByRole('radio', { name: 'Branch vs base' }))
        expect(files()).toEqual(['earlier.txt', 'own.txt'])
    })

    it('says a kept diff with no files is no change', () => {
        render(<RunChangesPanel changes={[change('web', { diff: { truncated: false, files: [] } })]} records />)
        expect(screen.getByText('no change: the run left the branch where it started')).toBeDefined()
        expect(screen.queryAllByTestId('diff-file')).toHaveLength(0)
    })

    it('says a run that recorded nothing did so when a run like it records, and is nothing otherwise', () => {
        const { container, unmount } = render(<RunChangesPanel changes={[]} records={false} />)
        expect(container.innerHTML).toBe('')
        unmount()
        render(<RunChangesPanel changes={[]} records />)
        expect(screen.getByTestId('run-change').textContent).toContain(
            'canopy recorded nothing of what this run changed',
        )
    })
})
