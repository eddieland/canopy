import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { mockAttention } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { renderRouted } from '@/test-utils'
import { getSnapshot, setPreference } from '@/theme/store'

import { Favicon } from './favicon'

const WAITING = mockAttention[0] as AttentionItem
const FAILED: AttentionItem = { ...WAITING, id: 'a2', reason: 'worker_failed' }
const STATIC = './favicon.svg'

let link: HTMLLinkElement

beforeEach(() => {
    link = document.createElement('link')
    link.rel = 'icon'
    link.setAttribute('href', STATIC)
    document.head.append(link)
    // Names, not colors: the icon puts whatever the tokens hold where a color goes.
    const root = document.documentElement.style
    root.setProperty('--accent', 'ACCENT')
    root.setProperty('--status-failed', 'FAILED')
    root.setProperty('--status-blocked', 'BLOCKED')
    root.setProperty('--muted-foreground', 'MUTED')
})

afterEach(() => {
    cleanup()
    link.remove()
    setPreference('system')
})

// The SVG the tab's icon holds now.
function icon(): string {
    const href = link.getAttribute('href') ?? ''
    expect(href.startsWith('data:image/svg+xml,')).toBe(true)
    return decodeURIComponent(href.slice('data:image/svg+xml,'.length))
}

async function renderFavicon(items: AttentionItem[] | undefined) {
    const client = new QueryClient()
    // Nothing is fetched: the attention list is what the test seeds, as the stream would send.
    client.setQueryDefaults(keys.attention, { enabled: false })
    if (items !== undefined) {
        client.setQueryData(keys.attention, items)
    }
    return { client, ...(await renderRouted(<Favicon />, { client })) }
}

describe('Favicon', () => {
    it('draws the mark in the accent while nothing blocks', async () => {
        await renderFavicon([])
        expect(icon()).toContain('stroke="ACCENT"')
        expect(icon()).not.toMatch(/FAILED|BLOCKED|MUTED/u)
    })

    it("wears the most severe blocking item's color, and follows the list as it changes", async () => {
        const { client } = await renderFavicon([WAITING])
        expect(icon()).toContain('fill="BLOCKED"')
        act(() => {
            client.setQueryData(keys.attention, [WAITING, FAILED])
        })
        await waitFor(() => {
            expect(icon()).toContain('fill="FAILED"')
        })
        act(() => {
            client.setQueryData(keys.attention, [])
        })
        await waitFor(() => {
            expect(icon()).not.toMatch(/FAILED|BLOCKED/u)
        })
    })

    it("draws again in the new theme's tokens when the theme changes", async () => {
        await renderFavicon([FAILED])
        expect(icon()).toContain('fill="FAILED"')
        // The tokens a dark page resolves to, as tokens.css would give them under .dark.
        document.documentElement.style.setProperty('--status-failed', 'DARK_FAILED')
        act(() => {
            setPreference(getSnapshot().resolved === 'dark' ? 'light' : 'dark')
        })
        expect(icon()).toContain('fill="DARK_FAILED"')
    })

    it('puts back the icon it found when it goes, as on signing out', async () => {
        const { unmount } = await renderFavicon([FAILED])
        expect(icon()).toContain('fill="FAILED"')
        unmount()
        expect(link.getAttribute('href')).toBe(STATIC)
    })
})
