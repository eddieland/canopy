import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { keys } from '@/api/queries'

afterEach(() => {
    cleanup()
    document.head.querySelector('meta[name="canopy-build"]')?.remove()
})

// The page's build is read from its meta tag when the module loads, so each test loads a fresh copy under its own.
async function renderUnder(page: string | null, served: string | null | undefined) {
    if (page !== null) {
        const meta = document.createElement('meta')
        meta.name = 'canopy-build'
        meta.content = page
        document.head.append(meta)
    }
    vi.resetModules()
    const { NewerBuild } = await import('./newer-build')
    const client = new QueryClient()
    // Nothing is fetched: the meta is what the test seeds, or not read yet.
    client.setQueryDefaults(keys.meta, { enabled: false })
    if (served !== undefined) {
        client.setQueryData(keys.meta, { build: served })
    }
    return render(
        <QueryClientProvider client={client}>
            <NewerBuild />
        </QueryClientProvider>,
    )
}

describe('NewerBuild', () => {
    it('offers a reload once the server serves a build other than the page', async () => {
        const reload = vi.spyOn(globalThis.location, 'reload').mockImplementation(() => {})
        await renderUnder('abc123', 'def456')

        fireEvent.click(screen.getByRole('button', { name: 'Reload' }))
        expect(reload).toHaveBeenCalledOnce()
    })

    it.each([
        ['the page is the build served', 'abc123', 'abc123'],
        ['the server has no UI built', 'abc123', null],
        ['the page is from the dev server', null, 'def456'],
        ['the meta is not read yet', 'abc123', undefined],
    ] as const)('stays out of the way when %s', async (_, page, served) => {
        await renderUnder(page, served)
        expect(screen.queryByRole('button', { name: 'Reload' })).toBeNull()
    })
})
