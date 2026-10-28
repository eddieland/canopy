import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockHost } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { HostResources } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { HostReadout } from './host-readout'

const GIB = 1024 ** 3

afterEach(cleanup)

function renderReadout(host: HostResources | undefined) {
    const client = new QueryClient()
    // Nothing is fetched: the read is what the test seeds.
    client.setQueryDefaults(keys.host, { enabled: false })
    if (host !== undefined) {
        client.setQueryData(keys.host, host)
    }
    return renderRouted(<HostReadout />, { client })
}

describe('HostReadout', () => {
    it('shows nothing until the first read lands', async () => {
        await renderReadout(undefined)
        expect(screen.queryByTestId('host-readout')).toBeNull()
    })

    it('says the host is ok, and opens the system resources page', async () => {
        const { router } = await renderReadout(mockHost())
        const link = screen.getByRole('link', { name: 'host ok: system resources of build-box' })
        expect(link.textContent).toBe('host ok')
        await act(async () => {
            link.click()
            await router.invalidate()
        })
        expect(router.state.location.pathname).toBe('/system')
    })

    it('names a disk under the tick floor, as past what canopy works with', async () => {
        const full = mockHost({
            disks: [{ holds: ['workspace'], path: '/w', total: 100 * GIB, free: GIB, floor: 2 * GIB }],
        })
        await renderReadout(full)
        const link = screen.getByTestId('host-readout')
        expect(link.textContent).toBe('disk low')
        expect(link.dataset['pressure']).toBe('critical')
    })

    it('shows the machine at a glance in a card when it has the focus', async () => {
        await renderReadout(mockHost())
        act(() => {
            screen.getByTestId('host-readout').focus()
        })
        const card = await waitFor(() => screen.getByTestId('host-card'))
        expect(card.textContent).toContain('build-box')
        expect(card.textContent).toContain('2.41 1.87 1.52 on 12 cores')
        expect(card.textContent).toContain('412 GiB free of 931 GiB, the workspace and the journal')
        expect(card.textContent).toContain('27 GiB free of 32 GiB, the temporary directory')
    })
})
