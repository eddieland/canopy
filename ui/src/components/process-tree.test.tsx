import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { HostProcess, ProcessWork } from '@/api/types'
import { STORAGE_KEY } from '@/lib/process-settings'
import { renderRouted } from '@/test-utils'

import { ProcessTree } from './process-tree'

const LOOP = 50
const NONE: Omit<ProcessWork, 'kind' | 'id'> = {
    ticket_key: null,
    pr_url: null,
    chore: null,
    task_id: null,
    epic_id: null,
}

function process(pid: number, parent: number, name: string, cpu = 0, fields: Partial<HostProcess> = {}): HostProcess {
    return {
        pid,
        parent,
        name,
        command: name,
        user: 'operator',
        state: 'sleeping',
        cpu,
        rss: 64 * 1024 ** 2,
        threads: 1,
        started_at: null,
        work: null,
        ...fields,
    }
}

// A login down to a shell, the loop under it with run 41 compiling and review 4 idle, an editor's server beside it, and
// a database busy in a container.
const PROCESSES = [
    process(1, 0, 'systemd'),
    process(2, 1, 'sshd'),
    process(3, 2, 'bash'),
    process(LOOP, 3, 'canopy', 0.03),
    process(60, LOOP, 'python3', 0, { work: { ...NONE, kind: 'run', id: 41, ticket_key: 'ABC-101' } }),
    process(61, 60, 'rustc', 0.98, { state: 'running', rss: 1024 ** 3 }),
    process(70, LOOP, 'python3', 0, {
        work: { ...NONE, kind: 'review', id: 4, pr_url: 'https://github.com/acme/web/pull/88', ticket_key: null },
    }),
    process(80, 3, 'node', 0.02, { rss: 512 * 1024 ** 2 }),
    process(90, 1, 'dockerd'),
    process(91, 90, 'shim'),
    process(92, 91, 'postgres', 0.05),
]

beforeEach(() => {
    localStorage.removeItem(STORAGE_KEY)
})

afterEach(cleanup)

function renderTree() {
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.hostProcesses, {
        read_at: '2026-10-08T12:30:00Z',
        over_seconds: 10,
        processes: PROCESSES,
    })
    return renderRouted(<ProcessTree loop={LOOP} cores={12} memory={16 * 1024 ** 3} />, { client })
}

describe('ProcessTree', () => {
    it("roots the tree at the loop, with each run's process carrying its run and what it works on", async () => {
        const { router } = await renderTree()

        expect(screen.getByTestId('process-above').textContent).toBe('under systemd › sshd › bash')
        const run = screen.getByRole('link', { name: 'run:41 ABC-101' })
        expect(screen.getByRole('link', { name: 'review:4 acme/web#88' })).toBeTruthy()
        // A run's figures are what it costs: its process and the compiler under it.
        const row = run.closest('tr')
        expect(row?.textContent).toContain('98%')
        expect(row?.textContent).toContain('1.1 GiB')
        await act(async () => {
            run.click()
            await router.invalidate()
        })
        expect(router.state.location.pathname).toBe('/workspace/runs/41')
    })

    it("puts what else is busy under elsewhere, the loop's parents left to the line over it", async () => {
        await renderTree()

        const elsewhere = screen.getByTestId('process-elsewhere')
        expect(within(elsewhere).getByRole('columnheader', { name: 'elsewhere' })).toBeTruthy()
        // The container's idle parents are one line, on the way to the database.
        expect(within(elsewhere).getByTestId('process-chain').textContent).toBe('dockerd › shim')
        expect(
            within(elsewhere)
                .getAllByTestId('process-row')
                .map((r) => r.textContent),
        ).toEqual([expect.stringContaining('postgres'), expect.stringContaining('node')])
    })

    it('orders by memory from its head, says which column orders it, and keeps that on coming back', async () => {
        await renderTree()
        const memory = screen.getByRole('button', { name: /^memory/u })
        expect(screen.getByRole('columnheader', { name: /cpu/u }).getAttribute('aria-sort')).toBe('descending')

        act(() => {
            memory.click()
        })

        expect(memory.closest('th')?.getAttribute('aria-sort')).toBe('descending')
        cleanup()
        await renderTree()
        expect(
            screen
                .getByRole('button', { name: /^memory/u })
                .closest('th')
                ?.getAttribute('aria-sort'),
        ).toBe('descending')
    })

    it('keeps a fold and every process shown across leaving the page and coming back', async () => {
        await renderTree()
        act(() => {
            screen.getByRole('button', { name: 'Fold python3 60' }).click()
            screen.getByRole('button', { name: 'All' }).click()
        })
        cleanup()

        await renderTree()

        expect(screen.getByRole('button', { name: 'All' }).getAttribute('aria-pressed')).toBe('true')
        expect(screen.getByRole('button', { name: 'Unfold python3 60' }).getAttribute('aria-expanded')).toBe('false')
        expect(screen.queryByTestId('process-elsewhere')).toBeNull()
        expect(screen.getAllByTestId('process-row')[0]?.textContent).toMatch(/^systemd1operator/u)
    })
})
