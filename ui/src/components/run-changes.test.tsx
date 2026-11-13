import { QueryClient, queryOptions } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import type { ChangedFile, ChecklistStretch, ReviewDiff, RunChange, RunRange } from '@/api/types'
import { renderRouted, tipOf } from '@/test-utils'

import { RunChangesPanel } from './run-changes'

afterEach(() => {
    cleanup()
})

const START = '5b1e0c47aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const END = 'c9d24f83bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
const LEFT = 'd8e61b30cccccccccccccccccccccccccccccccc'
const PR = 'https://github.com/acme/web/pull/88'

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

function file(path: string, added: number | null = 1, removed: number | null = 1): ChangedFile {
    return { path, old_path: null, added, removed }
}

function range(repo: string, fields: Partial<RunRange> = {}): RunRange {
    return {
        repo,
        start_sha: START,
        start_on_base: false,
        end_sha: END,
        unpushed_sha: null,
        files_changed: 1,
        lines_added: 1,
        lines_removed: 1,
        commit_count: null,
        commits: [],
        kick: null,
        ...fields,
    }
}

function stretch(repo: string, diff: ReviewDiff | null, removed: number | null = null): ChecklistStretch {
    return { repo, shown_sha: START, pushed_sha: END, diff, diff_removed_after_days: removed }
}

function change(repo: string, fields: Partial<RunChange> = {}, ranged: Partial<RunRange> = {}): RunChange {
    return {
        range: range(repo, ranged),
        files: [file('own.txt')],
        diff_kept: true,
        missing: null,
        removed_after_days: null,
        pr_url: null,
        ...fields,
    }
}

interface Rendered {
    /** The repositories whose diff was read, in order. */
    read: string[]
    /** What the panel rendered into. */
    container: HTMLElement
    /** Takes it down again. */
    unmount: () => void
}

// Each repository's diff as the server keeps it; one it has none of is a 404, as the server sends.
async function render(
    changes: RunChange[],
    {
        records = true,
        at = '/',
        diffs = {},
        stretches = [],
        leftOut = 0,
    }: {
        records?: boolean
        at?: string
        diffs?: Record<string, ReviewDiff>
        stretches?: ChecklistStretch[]
        leftOut?: number
    } = {},
): Promise<Rendered> {
    const read: string[] = []
    const diff = (repo: string) =>
        queryOptions({
            queryKey: ['run-change', 1, repo] as const,
            queryFn: () => {
                read.push(repo)
                const found = diffs[repo]
                if (found === undefined) {
                    throw new ApiError(404, `run 1 kept no diff of its change to ${repo}`)
                }
                return found
            },
            retry: false,
        })
    const client = new QueryClient()
    const { container, unmount } = await renderRouted(
        <RunChangesPanel
            changes={changes}
            records={records}
            diff={diff}
            stretches={stretches}
            leftOut={leftOut}
            shownBy="run:38"
        />,
        { at, client },
    )
    return { read, container, unmount }
}

function rowsOf(region: HTMLElement): string[] {
    return within(within(region).getByTestId('run-change-files'))
        .getAllByRole('listitem')
        .map((r) => r.textContent)
}

function stretchLine(): string | null {
    return screen.getByTestId('run-change-stretch').textContent
}

function shownFiles(): string[] {
    return screen.getAllByTestId('diff-file').map((f) => within(f).getAllByTitle(/\.txt$/u)[0]?.title ?? '')
}

describe('RunChangesPanel', () => {
    it('summarizes a change, its repository, commits, and size, and reads no diff until it is shown', async () => {
        const changed = change(
            'web',
            { files: [file('src/own.txt', 20, 3), { ...file('logo.png', null, null), old_path: 'old.png' }] },
            { files_changed: 2, lines_added: 20, lines_removed: 3 },
        )
        const { read } = await render([changed], { diffs: { web: diffOf('own.txt') } })
        const shown = screen.getByRole('region', { name: "web's diff" })
        expect(within(shown).getByTestId('run-change-range').textContent).toBe('web · 5b1e0c4..c9d24f8')
        expect(within(shown).getByTestId('run-change-range').title).toBe(
            'From where origin’s branch was when the run started, to where the run left it on origin.',
        )
        expect(within(shown).getByTestId('run-change-size').textContent).toBe('2 files · +20 −3')
        const rows = within(screen.getByTestId('run-change-files')).getAllByRole('listitem')
        expect(rows.map((r) => r.textContent)).toEqual(['src/own.txt+20 −3', 'old.png → logo.pngbinary'])
        // No diff is drawn, nor read, until asked for.
        expect(screen.queryAllByTestId('diff-file')).toHaveLength(0)
        expect(read).toEqual([])
        expect(screen.queryByText('branch vs base')).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Show diff of web' }))
        expect(await screen.findAllByTestId('diff-file')).toHaveLength(1)
        expect(read).toEqual(['web'])
        // The branch's text stays text.
        expect(screen.getByText('own.txt <img src=x onerror=alert(1)>')).toBeDefined()
        expect(document.querySelector('img')).toBeNull()
        fireEvent.click(within(screen.getByTestId('run-change')).getByRole('button', { name: 'Hide diff of web' }))
        expect(screen.queryAllByTestId('diff-file')).toHaveLength(0)
    })

    it('lists the commits in its range under its files, an unpushed slot’s linked nowhere', async () => {
        const made = { canopy_trailer: true, prefixed: null, runtime_trailer: false, harness_pushed: false }
        const commits = [{ sha: END, subject: 'ABC-099: the fix', ...made }]
        await render([
            change('api', { pr_url: PR }, { commits, commit_count: 3 }),
            change('web', { pr_url: PR }, { commits, commit_count: 1, unpushed_sha: LEFT }),
        ])
        const [api, web] = screen.getAllByTestId('run-commits')
        expect(api?.textContent).toBe('and 2 older commitsc9d24f8ABC-099: the fix')
        expect(
            within(api as HTMLElement)
                .getByRole('link', { name: 'c9d24f8' })
                .getAttribute('href'),
        ).toBe(`${PR}/commits/${END}`)
        expect(within(web as HTMLElement).queryByRole('link')).toBeNull()
    })

    it('opens the diff a link names, `#diff-web`, and links to the PR’s page for the whole branch', async () => {
        await render([change('api'), change('web', { pr_url: PR })], {
            at: '/#diff-web',
            diffs: { api: diffOf('api.txt'), web: diffOf('web.txt') },
        })
        await screen.findAllByTestId('diff-file')
        expect(shownFiles()).toEqual(['web.txt'])
        const web = screen.getByRole('region', { name: "web's diff" })
        expect(web.id).toBe('diff-web')
        expect(within(web).getByRole('link', { name: 'branch vs base' }).getAttribute('href')).toBe(
            `/pull-requests/pr?url=${encodeURIComponent(PR)}`,
        )
    })

    it('marks an unpushed slot’s change not on origin, once, saying why in its tip', async () => {
        await render([change('web', {}, { end_sha: START, unpushed_sha: LEFT })])
        expect(screen.getByTestId('run-change-range').textContent).toBe('web · 5b1e0c4..d8e61b3')
        // Said once, in the chip, not again in a paragraph or a sentence under it.
        expect(screen.getAllByText(/unpushed|not on origin/u)).toHaveLength(1)
        expect(tipOf(screen.getByText('not on origin'))).toContain('left this commit unpushed in its slot')
    })

    it('names a range with nothing pushed so it does not look cut off', async () => {
        await render([change('web', {}, { end_sha: null })])
        expect(screen.getByTestId('run-change-range').textContent).toBe('web · 5b1e0c4 → nothing pushed')
    })

    it('says why a diff was not kept, or that retention removed it, rather than offering it', async () => {
        await render([
            change(
                'api',
                { files: [], diff_kept: false, missing: 'the run crashed, so canopy kept no diff' },
                { start_sha: null, end_sha: null, files_changed: null, lines_added: null, lines_removed: null },
            ),
            change('mobile', { diff_kept: false, removed_after_days: 30 }),
        ])
        const [crashed, removed] = screen.getAllByTestId('run-change')
        expect(within(crashed as HTMLElement).getByTestId('run-change-range').textContent).toBe('api · nothing read')
        expect(crashed?.textContent).toContain('no diff kept: the run crashed, so canopy kept no diff')
        // Its files were counted as it ended, so they outlive the diff.
        expect(removed?.textContent).toContain('own.txt')
        expect(removed?.textContent).toContain('removed after 30 days, as your [retention] keeps it')
        expect(screen.queryByRole('button', { name: /^Show diff/u })).toBeNull()
    })

    it('says a diff it opened and could not read was not there to read', async () => {
        await render([change('web')])
        fireEvent.click(screen.getByRole('button', { name: 'Show diff of web' }))
        expect(
            await screen.findByText('the diff could not be read: its file is gone, or not a regular file'),
        ).toBeDefined()
    })

    it('says a change that touched no file is no change, and one canopy did not count was not counted', async () => {
        await render([
            change('api', { files: [] }, { files_changed: 0, lines_added: 0, lines_removed: 0 }),
            change('web', { files: [] }, { files_changed: null, lines_added: null, lines_removed: null }),
        ])
        expect(screen.getByText('no change: the run left the branch where it started')).toBeDefined()
        expect(screen.getByText(/^canopy counted no files for this run/u)).toBeDefined()
        expect(screen.queryAllByTestId('run-change-size')).toHaveLength(0)
    })

    it('says a run that recorded nothing did so when a run like it records, and is nothing otherwise', async () => {
        const { container, unmount } = await render([], { records: false })
        expect(container.innerHTML).toBe('')
        unmount()
        await render([])
        expect(screen.getByTestId('run-change').textContent).toContain(
            'canopy recorded nothing of what this run changed',
        )
    })

    it('holds what the run pushed after its list as a scope of its Diff, open on it, its files marked', async () => {
        const changed = change('web', { files: [file('notes.txt'), file('own.txt')] }, { files_changed: 2 })
        const { read } = await render([changed], {
            stretches: [stretch('web', diffOf('notes.txt'))],
            diffs: { web: diffOf('own.txt', 'notes.txt') },
        })
        const web = screen.getByRole('region', { name: "web's diff" })
        // One panel, its stretch's files under it: a Diff, then each file a heading below its own, naming it.
        expect(
            within(web)
                .getAllByRole('heading')
                .map((h) => [h.tagName, h.textContent]),
        ).toEqual([
            ['H2', 'Diff'],
            ['H3', 'File notes.txt'],
        ])
        const scopes = within(web).getByRole('radiogroup', { name: "Which of web's diffs" })
        expect(within(scopes).getByRole('radio', { name: 'after the list' }).getAttribute('aria-checked')).toBe('true')
        expect(rowsOf(web)).toEqual(['changed after the list: notes.txt+1 −1', 'own.txt+1 −1'])
        expect(within(web).getByTestId('run-change-stretch').textContent).toBe(
            '1 file changed after the list · 5b1e0c4..c9d24f8',
        )
        // The stretch's diff came with the run: the run's own is read only when asked for.
        expect(read).toEqual([])
        expect(shownFiles()).toEqual(['notes.txt'])
        expect(screen.getByText('notes.txt <img src=x onerror=alert(1)>')).toBeDefined()
        expect(document.querySelector('img')).toBeNull()
        expect(within(web).getByRole('button', { name: 'Hide diff of notes.txt' })).toBeDefined()

        fireEvent.click(within(scopes).getByRole('radio', { name: 'whole run' }))
        await within(web).findByText('own.txt <img src=x onerror=alert(1)>')
        expect(read).toEqual(['web'])
        expect(shownFiles()).toEqual(['own.txt', 'notes.txt'])
        expect(rowsOf(web)).toEqual(['notes.txt+1 −1', 'own.txt+1 −1'])
        expect(within(web).queryByTestId('run-change-stretch')).toBeNull()
        // The whole run folds away as the stretch did.
        fireEvent.click(within(screen.getByTestId('run-change')).getByRole('button', { name: 'Hide diff of web' }))
        expect(screen.queryAllByTestId('diff-file')).toHaveLength(0)
    })

    it("puts a joint run's stretches each in its repository's Diff, listing the files of one alone", async () => {
        await render([change('web')], {
            stretches: [stretch('api', diffOf('api.txt')), stretch('web', diffOf('own.txt'))],
        })
        const regions = screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'))
        expect(regions).toEqual(["web's diff", "api's diff"])
        const api = screen.getByRole('region', { name: "api's diff" })
        expect(within(api).getByTestId('run-change-range').textContent).toBe('api')
        expect(rowsOf(api)).toEqual(['changed after the list: api.txt+1 −1'])
        expect(api.textContent).toContain('canopy recorded nothing of what this run changed')
        // With no run diff to read, its stretch is its only scope, so no choice is offered.
        expect(within(api).queryByRole('radiogroup')).toBeNull()
        expect(shownFiles()).toEqual(['own.txt', 'api.txt'])
    })

    it('says a stretch whose diff is missing, removed, or empty is so, and how many more it was not sent', async () => {
        await render([change('web', { diff_kept: false, removed_after_days: 30 })], {
            stretches: [
                stretch('web', null),
                stretch('web', null, 30),
                stretch('web', { truncated: false, files: [] }),
            ],
            leftOut: 2,
        })
        const scopes = screen.getByRole('radiogroup', { name: "Which of web's diffs" })
        // A run diff retention removed is no scope to offer.
        expect(
            within(scopes)
                .getAllByRole('radio')
                .map((r) => r.textContent),
        ).toEqual(['after list 1', 'after list 2', 'after list 3'])
        expect(stretchLine()).toContain('no diff kept for this stretch')
        fireEvent.click(within(scopes).getByRole('radio', { name: 'after list 2' }))
        expect(stretchLine()).toContain('removed after 30 days, as your [retention] keeps it')
        fireEvent.click(within(scopes).getByRole('radio', { name: 'after list 3' }))
        expect(stretchLine()).toBe('no change: the run pushed the commit it was shown the list at')
        expect(screen.queryAllByTestId('diff-file')).toHaveLength(0)
        expect(screen.queryByRole('button', { name: /^Show diff/u })).toBeNull()
        expect(screen.getByTestId('checklist-stretches-left-out').textContent).toBe(
            "2 more stretches pushed after the list, not shown: canopy show run:38 names each one's diff",
        )
    })

    it('keeps its disclosure in place on a scope with no diff, disabled, saying why', async () => {
        await render([change('web')], {
            stretches: [stretch('web', { truncated: false, files: [] })],
            diffs: { web: diffOf('own.txt') },
        })
        const web = screen.getByRole('region', { name: "web's diff" })
        const scopes = within(web).getByRole('radiogroup', { name: "Which of web's diffs" })
        const disclosure = (): HTMLButtonElement => within(web).getByRole('button', { name: /diff of web$/u })
        expect(disclosure().textContent).toBe('Show diff')
        expect(disclosure().disabled).toBe(true)
        expect(disclosure().parentElement?.title).toBe('no change: the run pushed the commit it was shown the list at')

        // The panel opened on the stretch, so the run's diff is open once chosen.
        fireEvent.click(within(scopes).getByRole('radio', { name: 'whole run' }))
        await within(web).findByText('own.txt <img src=x onerror=alert(1)>')
        expect(disclosure().disabled).toBe(false)
        expect(disclosure().textContent).toBe('Hide diff')
        expect(disclosure().parentElement?.title).toBe('')
        // Back on the stretch the diff folds, and the run's stays open for when it is chosen again.
        fireEvent.click(within(scopes).getByRole('radio', { name: 'after the list' }))
        expect(screen.queryAllByTestId('diff-file')).toHaveLength(0)
        expect(disclosure().disabled).toBe(true)
        fireEvent.click(within(scopes).getByRole('radio', { name: 'whole run' }))
        expect(shownFiles()).toEqual(['own.txt'])
        expect(disclosure().textContent).toBe('Hide diff')
    })

    it('opens the run’s own diff, not the stretch, when a link names it', async () => {
        await render([change('web')], {
            at: '/#diff-web',
            stretches: [stretch('web', diffOf('notes.txt'))],
            diffs: { web: diffOf('own.txt') },
        })
        await screen.findByText('own.txt <img src=x onerror=alert(1)>')
        expect(shownFiles()).toEqual(['own.txt'])
        expect(screen.getByRole('radio', { name: 'whole run' }).getAttribute('aria-checked')).toBe('true')
    })
})
