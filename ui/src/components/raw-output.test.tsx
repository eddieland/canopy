import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { RawOutput } from '@/api/types'
import { STORAGE_KEY } from '@/lib/pretty-output'

import { RunOutputPanel, TickOutputPanel } from './raw-output'

const PATH = '/home/op/.canopy/ticks/7.out'
const TEXT = '{"type":"result","ok":true}\n--- stderr ---\nrate limited once'

// The paths the panel read, and what the server stand-in answers each. A path's copy button reads the server's meta
// for the workspace root, which is not the file.
let read: string[] = []
const outputs = () => read.filter((path) => path.endsWith('/output'))
let answer: RawOutput = { status: 'read', text: TEXT, size: 2048, truncated: false }

const server: Middleware = {
    onRequest({ request }) {
        read.push(new URL(request.url).pathname)
        return Response.json(answer)
    },
}

beforeEach(() => {
    read = []
    answer = { status: 'read', text: TEXT, size: 2048, truncated: false }
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
    localStorage.clear()
})

function renderPanel(path: string | null) {
    return render(
        <QueryClientProvider client={new QueryClient()}>
            <TickOutputPanel id={7} path={path} />
        </QueryClientProvider>,
    )
}

// What the panel shows of the file.
function output() {
    return screen.getByRole('region', { name: "the overseer's output" }).textContent
}

// Opens the panel and waits for what it read.
async function show() {
    fireEvent.click(screen.getByRole('button', { name: 'Show output' }))
    await screen.findByRole('button', { name: 'Hide output' })
}

describe('TickOutputPanel', () => {
    it('is not there with no file: the transcript, read from the same file, says why', () => {
        const { container } = renderPanel(null)
        expect(container.textContent).toBe('')
        expect(read).toEqual([])
    })

    it('names its file while hidden, and reads it only once shown', async () => {
        renderPanel(PATH)
        expect(screen.getByText(/as written: stdout, then stderr/u).textContent).toBe(
            `${PATH} as written: stdout, then stderr`,
        )
        expect(outputs()).toEqual([])

        await show()
        expect((await screen.findByRole('region', { name: "the overseer's output" })).textContent).toBe(TEXT)
        expect(screen.getByText('2.0 KiB')).toBeDefined()
        expect(screen.queryByText(/as written: stdout, then stderr/u)).toBeNull()
        expect(outputs()).toEqual(['/api/ticks/7/output'])
    })

    it.each([
        ['a file it cannot read', { status: 'no_output', text: '', size: 0, truncated: false }, /^its output is gone/u],
        ['an empty file', { status: 'read', text: '', size: 0, truncated: false }, 'empty: the overseer wrote nothing'],
    ] as const)('says so for %s, with nothing to lay out', async (_, file, says) => {
        answer = file
        renderPanel(PATH)
        await show()
        expect(await screen.findByText(says)).toBeDefined()
        expect(screen.queryByRole('region')).toBeNull()
        expect(screen.queryByRole('button', { name: 'Pretty' })).toBeNull()
    })

    it('says when it shows only the end of a file that holds more', async () => {
        answer = { status: 'read', text: 'the last line', size: 900_000, truncated: true }
        renderPanel(PATH)
        await show()
        expect(
            await screen.findByText('cut: the file holds more, and this is its end, from a whole line'),
        ).toBeDefined()
        expect(output()).toBe('the last line')
    })

    it('lays its JSON out indented while Pretty is on, and keeps that choice for the tick', async () => {
        renderPanel(PATH)
        await show()
        await screen.findByRole('region', { name: "the overseer's output" })

        fireEvent.click(screen.getByRole('button', { name: 'Pretty', pressed: false }))
        expect(screen.getByRole('button', { name: 'Pretty', pressed: true })).toBeDefined()
        expect(output()).toBe('{\n  "type": "result",\n  "ok": true\n}\n--- stderr ---\nrate limited once')
        expect(localStorage.getItem(STORAGE_KEY)).toBe('[7]')

        fireEvent.click(screen.getByRole('button', { name: 'Pretty', pressed: true }))
        expect(output()).toBe(TEXT)
        expect(localStorage.getItem(STORAGE_KEY)).toBe('[]')
    })
})

// The run panel of run 40, whose log the server stand-in answers for.
function renderRun() {
    return render(
        <QueryClientProvider client={new QueryClient()}>
            <RunOutputPanel id={40} />
        </QueryClientProvider>,
    )
}

describe('RunOutputPanel', () => {
    const LOG = '--- setup web stdout ---\nDone in 6.2s\n--- worker stdout ---\n{"type":"text"}\n--- worker exit 1 ---'

    it('names its log while hidden, and reads the run’s output only once shown, setup lines and all', async () => {
        answer = { status: 'read', text: LOG, size: LOG.length, truncated: false }
        renderRun()
        expect(screen.getByText(/as written: its setup commands’ output/u).textContent).toBe(
            'the run’s log as written: its setup commands’ output, then the worker’s stdout and stderr',
        )
        expect(read).toEqual([])

        await show()
        expect((await screen.findByRole('region', { name: "the run's output" })).textContent).toBe(LOG)
        expect(read).toEqual(['/api/runs/40/output'])
    })

    it('keeps Pretty for the page alone, never in the ticks’ store', async () => {
        answer = { status: 'read', text: LOG, size: LOG.length, truncated: false }
        renderRun()
        await show()
        await screen.findByRole('region', { name: "the run's output" })
        fireEvent.click(screen.getByRole('button', { name: 'Pretty', pressed: false }))
        expect(screen.getByRole('button', { name: 'Pretty', pressed: true })).toBeDefined()
        expect(screen.getByRole('region', { name: "the run's output" }).textContent).toContain('{\n  "type": "text"\n}')
        expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    })

    it('says so when the run wrote nothing', async () => {
        answer = { status: 'read', text: '', size: 0, truncated: false }
        renderRun()
        await show()
        expect(await screen.findByText('empty: the run wrote nothing')).toBeDefined()
    })
})
