import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'

import type { MemoryEntry, MemoryProposal } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { MemoryBand, MemoryDigestView, MemoryPurge, MemoryRows, ProposalFacts } from './memory'
import { MemoryText } from './memory-text'

afterEach(() => {
    cleanup()
})

// A note written to the journal by hand, past the bounds: a Markdown link, a bidi override, and a zero-width space.
const WRITTEN = 'See [the fix](https://evil.test) \u202Eeht and\u200Bthis.'

describe('MemoryText', () => {
    it('shows what a worker wrote as plain text, never a link, with each hidden character named', () => {
        const { container } = render(<MemoryText text={WRITTEN} />)
        expect(container.textContent).toBe('See [the fix](https://evil.test) <U+202E>eht and<U+200B>this.')
        expect(screen.queryByRole('link')).toBeNull()
        expect(container.textContent).not.toContain('\u202E')
        expect(screen.getAllByTitle('A character that hides text, which a model still reads')).toHaveLength(2)
    })
})

describe('MemoryBand', () => {
    it('says in words what reads a tier, so recording never reads as in use', () => {
        const { rerender } = render(
            <MemoryBand
                name="ticket notes"
                tier={{
                    mode: 'record',
                    words: 'recording',
                    band: 'Recording only. Workers write these notes; no run reads them.',
                }}
            />,
        )
        expect(screen.getByTestId('memory-band').textContent).toBe(
            'ticket notes: recordingRecording only. Workers write these notes; no run reads them.',
        )
        rerender(
            <MemoryBand
                name="ticket notes"
                tier={{ mode: 'use', words: 'in use', band: "In use. A ticket's later runs read its notes." }}
            />,
        )
        expect(screen.getByText('ticket notes: in use')).toBeTruthy()
        expect(screen.queryByText(/recording/u)).toBeNull()
    })
})

const NOTE: MemoryEntry = {
    id: 12,
    key: 'export-encoding',
    text: 'The CSV writer must emit a BOM for Excel.',
    scope: 'ticket',
    status: 'active',
    ticket_key: 'ABC-102',
    repo: 'web',
    run_id: 41,
    head: 'a1b2c3d',
    why: null,
    review_at: null,
    wrong_at: null,
    wrong_run_id: null,
    use_count: 2,
    used_by: [43],
    last_used_at: '2026-10-08T11:30:00Z',
    promoted_from: null,
    origin: null,
    version: 1,
    edited: false,
    private: false,
    created_at: '2026-10-08T10:00:00Z',
}

// Renders rows under a router, for their links, with no query that would fetch: a ticket's tracker link reads none.
function renderRows(rows: React.JSX.Element) {
    return renderRouted(rows, { client: new QueryClient({ defaultOptions: { queries: { enabled: false } } }) })
}

describe('MemoryRows', () => {
    it('says what a memory says, how runs used it, and which run wrote it at which commit', async () => {
        await renderRows(<MemoryRows entries={[NOTE]} />)
        const row = screen.getByRole('listitem')
        expect(within(row).getByText(NOTE.text ?? '')).toBeDefined()
        expect(within(row).getByText('used by 2 runs')).toBeDefined()
        expect(within(row).getByRole('link', { name: 'run:41' }).getAttribute('href')).toBe('/runs/41')
        expect(within(row).getByTitle('written at a1b2c3d')).toBeDefined()
        expect(within(row).queryByRole('link', { name: 'ABC-102' })).toBeNull()
    })

    it('names the runs that relied on a memory, and counts those it cannot name', async () => {
        await renderRows(<MemoryRows entries={[{ ...NOTE, use_count: 4, used_by: [43, 42] }]} />)
        expect(screen.getByText(/^used in/u).textContent).toBe('used in run:43, run:42 and 2 more')
        expect(screen.getByRole('link', { name: 'run:43' }).getAttribute('href')).toBe('/runs/43')

        cleanup()
        await renderRows(<MemoryRows entries={[{ ...NOTE, use_count: 0, last_used_at: null, used_by: [] }]} />)
        expect(screen.queryByText(/^used in/u)).toBeNull()
    })

    it('marks what the run whose page it is relied on and found wrong, apart from the runs that used it', async () => {
        const rows = [NOTE, { ...NOTE, id: 13, used_by: [] }, { ...NOTE, id: 14, used_by: [] }]
        await renderRows(<MemoryRows entries={rows} ownRun={43} cited={{ used: [12], wrong: [13] }} />)
        const [used, wrong, neither] = screen.getAllByRole('listitem')
        expect(used && within(used).getByText('this run relied on it')).toBeDefined()
        expect(used && within(used).queryByRole('link', { name: 'run:43' })).toBeNull()
        expect(wrong && within(wrong).getByText('this run found it wrong')).toBeDefined()
        expect(neither && within(neither).queryByText(/^this run/u)).toBeNull()
    })

    it('names each note’s ticket only in a list across tickets', async () => {
        await renderRows(<MemoryRows entries={[NOTE, { ...NOTE, id: 13, ticket_key: null }]} ticket />)
        expect(screen.getAllByRole('link', { name: 'ABC-102' }).map((link) => link.getAttribute('href'))).toEqual([
            '/tickets/ABC-102',
        ])
    })

    it('leaves out the run whose page it is, and says which run reported a memory wrong', async () => {
        await renderRows(<MemoryRows entries={[{ ...NOTE, status: 'invalid', wrong_run_id: 44 }]} ownRun={41} />)
        expect(screen.queryByRole('link', { name: 'run:41' })).toBeNull()
        expect(screen.getByText(/^reported wrong by/u).textContent).toBe('reported wrong by run:44')
        expect(screen.getByText('invalid')).toBeDefined()
    })

    it('names a lesson’s source, its ticket, and the run that wrote it, as the CLI does', async () => {
        const lesson = {
            ...NOTE,
            scope: 'lesson' as const,
            run_id: null,
            head: null,
            promoted_from: 7,
            origin: { id: 7, scope: 'proposal' as const, ticket_key: 'ABC-103', run_id: 38 },
        }
        await renderRows(<MemoryRows entries={[lesson]} />)
        expect(screen.getByText(/^from proposal/u).textContent).toBe('from proposal memory:7 of ABC-103, by run:38')
        expect(screen.getByRole('link', { name: 'run:38' }).getAttribute('href')).toBe('/runs/38')
    })

    it('says when a run reported a lesson wrong', async () => {
        await renderRows(
            <MemoryRows entries={[{ ...NOTE, wrong_run_id: 44, wrong_at: '2026-10-08T09:00:00Z' }]} ownRun={41} />,
        )
        expect(screen.getByText(/^reported wrong by/u).textContent).toMatch(/^reported wrong by run:44 \S+ ago$/u)
    })

    it('reads a memory in force under a recording tier as recorded, by its own tier', async () => {
        const lesson = { ...NOTE, id: 13, scope: 'lesson' as const }
        await renderRows(<MemoryRows entries={[NOTE, lesson]} modes={{ ticket_notes: 'use', lessons: 'record' }} />)
        expect(screen.getAllByTestId('memory-stand').map((s) => s.textContent)).toEqual(['active', 'recorded'])
    })

    it('says a deleted text was deleted, and nothing of use for a memory no run relied on', async () => {
        await renderRows(<MemoryRows entries={[{ ...NOTE, text: null, use_count: 0, last_used_at: null }]} />)
        expect(screen.getByText('text deleted')).toBeDefined()
        expect(screen.queryByText(/used by|read by/u)).toBeNull()
    })

    it('says why a memory stands as it does, on hover and in its line', async () => {
        const pending = { ...NOTE, status: 'pending' as const, why: 'proposed from 3 notes' }
        await renderRows(<MemoryRows entries={[pending]} />)
        expect(screen.getByTitle('proposed from 3 notes').textContent).toBe('pending')
        expect(screen.getByText('proposed from 3 notes')).toBeDefined()
    })

    it('leads a lesson past its review date with due, and one a run reported wrong with wrong', async () => {
        const due = { ...NOTE, scope: 'lesson' as const, review_at: '2026-10-01T12:00:00Z' }
        await renderRows(<MemoryRows entries={[due, { ...due, id: 13, wrong_run_id: 44 }]} />)
        const [first, second] = screen.getAllByTestId('memory-stand')
        expect(first?.textContent).toBe('due')
        expect(second?.textContent).toBe('wrong')
        expect(screen.getAllByText(/^review overdue \S+$/u)).toHaveLength(2)
    })

    it('says which memories in force the digest’s cap leaves out, telling served from recording', async () => {
        const digest = { ids: [12], left_out: 1, served: true, text: '' }
        const rows = [NOTE, { ...NOTE, id: 13 }, { ...NOTE, id: 14, status: 'superseded' as const }]
        await renderRows(<MemoryRows entries={rows} digest={digest} />)
        const [kept, left, replaced] = screen.getAllByRole('listitem')
        expect(kept && within(kept).queryByText(/past its cap/u)).toBeNull()
        expect(left && within(left).getByText('left out of the prompt, past its cap')).toBeDefined()
        // Not in force, so no digest could serve it: nothing to say.
        expect(replaced && within(replaced).queryByText(/past its cap/u)).toBeNull()

        cleanup()
        await renderRows(<MemoryRows entries={rows} digest={{ ...digest, served: false }} />)
        expect(screen.getByText('would be left out at use, past its cap')).toBeDefined()
        expect(screen.queryByText('left out of the prompt, past its cap')).toBeNull()
    })

    it('adds what goes under a row by its id, and under no other', async () => {
        const below = new Map([[13, <p key="13">from notes 4 and 5</p>]])
        await renderRows(<MemoryRows entries={[NOTE, { ...NOTE, id: 13 }]} below={below} />)
        const [first, second] = screen.getAllByRole('listitem')
        expect(first && within(first).queryByText('from notes 4 and 5')).toBeNull()
        expect(second && within(second).getByText('from notes 4 and 5')).toBeDefined()
    })
})

describe('MemoryDigestView', () => {
    it('labels a digest served at use as served, and one while recording as what would be', () => {
        const digest = { ids: [12], left_out: 0, served: true, text: '- export-encoding: emit a BOM' }
        const { rerender } = render(<MemoryDigestView digest={digest} served="served to the next run" />)
        const region = screen.getByRole('region', { name: 'served to the next run' })
        expect(within(region).getByText('- export-encoding: emit a BOM')).toBeDefined()

        rerender(<MemoryDigestView digest={{ ...digest, served: false }} served="served to the next run" />)
        expect(screen.getByRole('region', { name: 'would be served at use' })).toBeDefined()
        expect(screen.queryByText('served to the next run')).toBeNull()
    })
})

const HOUR = 60 * 60 * 1000

// A proposal of NOTE's that lapses `left` milliseconds from now.
function proposal(left: number): MemoryProposal {
    return {
        entry: { ...NOTE, scope: 'proposal', status: 'pending' },
        run_kind: 'implement',
        run_status: 'done',
        private: false,
        ticket_done: false,
        expires_at: new Date(Date.now() + left).toISOString(),
    }
}

describe('ProposalFacts', () => {
    it('says how a proposal’s run ended and whether its ticket is done, with private as a chip', async () => {
        await renderRows(<ProposalFacts proposal={{ ...proposal(5 * 24 * HOUR), private: true }} />)
        expect(screen.getByText(/ended/u).textContent).toBe('implement, ended done')
        expect(screen.getByText('ticket not done yet')).toBeDefined()
        expect(screen.getByText('private')).toBeDefined()
    })
})

describe('MemoryRows lapses', () => {
    it('leads a proposal with the time it has left in place of pending, in amber in its last days', async () => {
        const later = proposal(5 * 24 * HOUR + HOUR)
        const soon = { ...proposal(30 * HOUR), entry: { ...later.entry, id: 13 } }
        const lapses = new Map([
            [12, later.expires_at],
            [13, soon.expires_at],
        ])
        await renderRows(<MemoryRows entries={[later.entry, soon.entry]} ticket lapses={lapses} />)
        const [first, second] = screen.getAllByTestId('memory-stand')
        expect(first?.textContent).toBe('5d left')
        expect(first?.className).not.toContain('text-status-blocked')
        expect(second?.textContent).toBe('1d left')
        expect(second?.className).toContain('text-status-blocked')
    })

    it('puts the commit on the run’s hover, and shows it only where the run is left out', async () => {
        await renderRows(<MemoryRows entries={[NOTE]} />)
        expect(screen.getByTitle('written at a1b2c3d').textContent).toBe('by run:41')
        cleanup()
        await renderRows(<MemoryRows entries={[NOTE]} ownRun={41} />)
        expect(screen.getByText('at a1b2c3d')).toBeDefined()
    })
})

describe('MemoryRows, versions', () => {
    const first: MemoryEntry = {
        ...NOTE,
        id: 8,
        scope: 'lesson',
        ticket_key: null,
        run_id: null,
        head: null,
        text: 'Run the tests once.',
        status: 'superseded',
        why: 'edited into lesson 10',
        promoted_from: 7,
        review_at: '2027-01-06T12:00:00Z',
    }
    const second: MemoryEntry = {
        ...first,
        id: 10,
        text: 'Run the tests once, with --run.',
        status: 'active',
        why: null,
        promoted_from: 8,
        version: 2,
        edited: true,
    }
    // Every path the rows read; the versions are read only once opened.
    let read: string[] = []
    const server: Middleware = {
        onRequest({ request }) {
            read.push(new URL(request.url).pathname)
            return Response.json({ versions: [second, first] })
        },
    }

    function renderLive(rows: React.JSX.Element) {
        read = []
        api.use(server)
        return renderRouted(rows, { client: new QueryClient() })
    }

    afterEach(() => {
        api.eject(server)
    })

    it('says which version a lesson is, and lists every version, newest first, only once opened', async () => {
        await renderLive(<MemoryRows entries={[second]} onVersionSaid={vi.fn<(said: string) => void>()} />)
        const row = screen.getByTestId('memory-10')
        expect(within(row).getByText('version 2')).toBeDefined()
        expect(within(row).getByText('edited from memory:8')).toBeDefined()
        expect(read).toEqual([])
        fireEvent.click(within(row).getByRole('button', { name: 'Show versions' }))
        const versions = await screen.findByRole('list', { name: 'Versions, newest first' })
        expect(read).toEqual(['/api/memory/10/history'])
        const [newest, oldest] = within(versions).getAllByRole('listitem')
        expect(newest?.textContent).toMatch(/^v2memory:10activewebedited.+this rowRun the tests once, with --run\.$/u)
        expect(oldest?.textContent).toMatch(/^v1memory:8supersededwebpromoted.+Run the tests once\.Forget$/u)
        // Forget under the version out of force alone: the one in force has its own verbs on its row.
        expect(within(versions).getAllByRole('button', { name: 'Forget' })).toHaveLength(1)
        expect(newest && within(newest).queryByRole('button', { name: 'Forget' })).toBeNull()
    })

    it("has no Forget under a version where the list has no verbs, as on a run's page", async () => {
        await renderLive(<MemoryRows entries={[first]} />)
        expect(screen.queryByText(/^version /u)).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Show versions' }))
        const versions = await screen.findByRole('list', { name: 'Versions, newest first' })
        expect(within(versions).queryByRole('button', { name: 'Forget' })).toBeNull()
    })

    it('opens no versions on a memory that has none, nor on a proposal a promote used up', async () => {
        await renderLive(
            <MemoryRows
                entries={[
                    NOTE,
                    { ...NOTE, id: 5, scope: 'proposal', status: 'superseded', why: 'promoted to lesson 8' },
                ]}
            />,
        )
        expect(screen.queryByRole('button', { name: 'Show versions' })).toBeNull()
    })
})

describe('MemoryPurge', () => {
    it("copies purge's verb alone, and names the options that say what it deletes", async () => {
        vi.stubGlobal('isSecureContext', true)
        const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
        render(<MemoryPurge />)
        const purge = screen.getByTestId('memory-purge')
        expect(purge.textContent).toContain('from your shell alone')
        for (const option of ['--ticket KEY', '--run ID', '--all']) {
            expect(within(purge).getByText(option)).toBeDefined()
        }
        fireEvent.click(screen.getByRole('button', { name: 'Copy purge command' }))
        await act(async () => {
            await Promise.resolve()
        })
        expect(write).toHaveBeenCalledWith('canopy memory purge')
        expect(screen.getByRole('button', { name: 'Copied purge command' })).toBeDefined()
    })

    it('keeps the command as text to select where the page cannot reach the clipboard', () => {
        vi.stubGlobal('isSecureContext', false)
        render(<MemoryPurge />)
        expect(screen.getByText('canopy memory purge')).toBeDefined()
        expect(screen.queryByRole('button')).toBeNull()
    })
})
