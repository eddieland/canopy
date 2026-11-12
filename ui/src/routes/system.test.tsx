import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockHost } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { HostHistory, HostResources } from '@/api/types'

import { Route } from './system'

afterEach(() => {
    cleanup()
})

const GIB = 1024 ** 3

async function renderPage(host: HostResources, history?: HostHistory) {
    // Nothing reads the server: the machine is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.host, host)
    if (history !== undefined) {
        client.setQueryData(keys.hostSamples, history)
    }
    const root = createRootRoute()
    const page = Route.update({ id: '/system', path: '/system', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: ['/system'] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
    return client
}

// An hour of readings, once a minute, of a machine using `used` of its memory.
function hour(used: number): HostHistory {
    return {
        every_seconds: 60,
        kept: 61,
        samples: Array.from({ length: 61 }, (_, i) => ({
            at: new Date(Date.parse('2026-10-08T11:30:00Z') + i * 60_000).toISOString(),
            load: 2,
            cpu_busy: 0.2,
            memory_used: used,
            swap_used: GIB,
            memory_stalled: 0,
            io_stalled: 0.01,
            rss: 268 * 1024 ** 2,
            disks: [],
        })),
    }
}

// Whether `first` comes before `second` on the page.
function before(first: HTMLElement, second: HTMLElement): boolean {
    return (first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
}

describe('the system resources page', () => {
    it('says nothing is under pressure, then the processes before the disks and the graphs', async () => {
        await renderPage(mockHost())
        expect(screen.queryByRole('region', { name: 'Under pressure' })).toBeNull()
        expect(screen.getByTestId('host-calm').textContent).toMatch(/^Nothing under pressure\. /u)
        expect(before(screen.getByTestId('host-processes'), screen.getByTestId('host-disks'))).toBe(true)
        expect(before(screen.getByTestId('host-disks'), screen.getByTestId('host-graphs'))).toBe(true)
    })

    it('leads with a disk under the floor, what it costs and the way out, and moves the disks up', async () => {
        const host = mockHost()
        for (const disk of host.disks) {
            if (disk.floor !== null) {
                disk.free = 412 * 1024 ** 2
            }
        }
        await renderPage(host)
        const band = screen.getByRole('region', { name: 'Under pressure' })
        expect(band.textContent).toContain(
            "412 MiB free where the workspace and the journal are, under the tick's floor of 2.0 GiB: " +
                'no tick runs the overseer',
        )
        expect(within(band).getByText('loop.min_free_disk_mib')).toBeTruthy()
        expect(screen.queryByTestId('host-calm')).toBeNull()
        expect(before(screen.getByTestId('host-disks'), screen.getByTestId('host-processes'))).toBe(true)
    })

    it('says the load once up top with its direction, and leaves the loop to the description', async () => {
        await renderPage(mockHost())
        expect(screen.getByTestId('counter-load').textContent).toContain('1.87 over 5 min, steady')
        expect(screen.queryByTestId('counter-loop')).toBeNull()
        expect(screen.getByText(/; the loop up/u)).toBeTruthy()
    })

    it('keeps the details folded until asked, holding only what nothing above shows', async () => {
        await renderPage(mockHost())
        const details = screen.getByTestId('host-details')
        expect(within(details).queryByText('Python')).toBeNull()
        act(() => {
            within(details).getByRole('button', { name: 'Show details' }).click()
        })
        expect(within(details).getByText(/^2\.41\s+1\.87\s+1\.52$/u)).toBeTruthy()
        expect(within(details).getByText('1.0 GiB used of 8.0 GiB')).toBeTruthy()
        expect(within(details).getByText('412 MiB')).toBeTruthy()
        expect(within(details).queryByText('Hostname')).toBeNull()
    })

    it('says once, off Linux, what only Linux reads, rather than a field at a time', async () => {
        await renderPage(
            mockHost({
                system: 'Darwin 24.1.0',
                memory: { total: 32 * GIB, available: null, swap_total: null, swap_free: null },
                stalled: { memory: null, io: null },
            }),
        )
        expect(screen.getByTestId('host-unread').textContent).toBe(
            'Memory, stalls, and processes are read on Linux only.',
        )
        expect(screen.queryByTestId('host-processes')).toBeNull()
        expect(screen.queryByText('not read on this system')).toBeNull()
        expect(screen.getByTestId('counter-memory').textContent).toContain('32 GiB in all')
    })

    it('ranks the graphs, the load, memory, and processors first, and says their hour and read once', async () => {
        await renderPage(mockHost(), hour(40 * GIB))

        const graphs = screen.getByTestId('host-graphs')
        const charts = within(graphs).getAllByRole('figure')
        expect(charts.map((chart) => chart.textContent.split(' ')[0])).toEqual([
            'Loadof',
            'Memory',
            'CPU',
            'Swap',
            'Memory',
            'Disk',
            "Loop's",
        ])
        expect(charts[1]?.textContent).toMatch(/^Memory used/u)
        expect(screen.getByTestId('host-graphs-read').textContent).toMatch(/^the last 60 min, read \d+[smhd] ago$/u)
        // The memory's graph draws where it turns amber, as a disk's draws the floor.
        expect(within(graphs).getByText('15% left')).toBeTruthy()
        expect(within(graphs).queryByText('60 min ago')).toBeNull()
    })

    it('says so in amber when a read again failed, so old figures do not pass for live ones', async () => {
        const client = await renderPage(mockHost(), hour(40 * GIB))

        // The next read fails, as one does while the loop's server is unreachable.
        await act(async () => {
            try {
                await client.query({
                    queryKey: keys.hostSamples,
                    queryFn: () => Promise.reject(new Error('down')),
                    retry: false,
                })
            } catch {
                // It fails, as it is meant to: the page is what is under test.
            }
        })

        await waitFor(() => {
            expect(screen.getByTestId('host-graphs-read').textContent).toContain('and the last read again failed')
        })
    })
})
