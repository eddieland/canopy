import type { AnyRouter, RouterHistory } from '@tanstack/react-router'
import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SEARCH_DEBOUNCE_MS } from '@/lib/search'
import { renderRouted } from '@/test-utils'

import { SearchBox } from './search-box'

beforeEach(() => {
    // Only the box's wait is faked: the router's own promises run as they would.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

function box(): HTMLInputElement {
    return screen.getByRole<HTMLInputElement>('searchbox', { name: 'Search the journal' })
}

// Types `text` into the box as one change, as a paste or the last keystroke leaves it.
function type(text: string) {
    fireEvent.change(box(), { target: { value: text } })
}

// Lets `ms` of the box's wait pass, and the navigation it starts settle.
async function wait(ms: number) {
    await act(async () => {
        vi.advanceTimersByTime(ms)
        await Promise.resolve()
    })
}

// Where the router is: its path and its search, as the address bar shows them.
function at(router: AnyRouter): string {
    return router.state.location.href
}

describe('SearchBox', () => {
    it('opens the search page once typing pauses, and Back leaves the search rather than each keystroke', async () => {
        const { router } = await renderRouted(<SearchBox onJump={vi.fn<() => void>()} />, { at: '/tickets' })

        type('export')
        await wait(SEARCH_DEBOUNCE_MS - 1)
        expect(at(router)).toBe('/tickets')
        await wait(1)
        expect(at(router)).toBe('/search?q=export')

        type('export   csv')
        await wait(SEARCH_DEBOUNCE_MS)
        expect(at(router)).toBe('/search?q=export+csv')

        // The test router is typed loosely: its history is the memory history renderRouted made.
        const history = router.history as RouterHistory
        await act(async () => {
            history.back()
            await Promise.resolve()
        })
        expect(at(router)).toBe('/tickets')
    })

    it('opens the search at once on Enter', async () => {
        const { router } = await renderRouted(<SearchBox onJump={vi.fn<() => void>()} />, { at: '/workspace/runs' })

        type('csv')
        await act(async () => {
            fireEvent.submit(box())
            await Promise.resolve()
        })
        expect(at(router)).toBe('/search?q=csv')
    })

    it("opens a task's page on Enter when the box holds its reference alone", async () => {
        const { router } = await renderRouted(<SearchBox onJump={vi.fn<() => void>()} />, { at: '/workspace/runs' })

        type(' task:4 ')
        await act(async () => {
            fireEvent.submit(box())
            await Promise.resolve()
        })
        expect(at(router)).toBe('/tasks/4')
        // The wait typing started is dropped, so the search does not open over the task.
        await wait(SEARCH_DEBOUNCE_MS)
        expect(at(router)).toBe('/tasks/4')

        type('task:4 report')
        await act(async () => {
            fireEvent.submit(box())
            await Promise.resolve()
        })
        expect(at(router)).toBe('/search?q=task%3A4+report')
    })

    it('sends nothing the server would refuse, and leaves the page as it is', async () => {
        const { router } = await renderRouted(<SearchBox onJump={vi.fn<() => void>()} />, { at: '/search?q=export' })

        type('e')
        await wait(SEARCH_DEBOUNCE_MS)
        expect(at(router)).toBe('/search?q=export')
    })

    it('empties the search page when the box is cleared, and keeps the focus in the box', async () => {
        const { router } = await renderRouted(<SearchBox onJump={vi.fn<() => void>()} />, { at: '/search?q=export' })
        expect(box().value).toBe('export')

        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Clear search' }))
            await Promise.resolve()
        })
        expect(box().value).toBe('')
        expect(document.activeElement).toBe(box())
        expect(at(router)).toBe('/search')
    })

    it('leaves any other page as it is when the box is emptied', async () => {
        const { router } = await renderRouted(<SearchBox onJump={vi.fn<() => void>()} />, { at: '/tickets' })

        type('export')
        type('')
        await wait(SEARCH_DEBOUNCE_MS)
        expect(at(router)).toBe('/tickets')
    })

    it("shows the page's query in the box when Back or a link changes it", async () => {
        const { router } = await renderRouted(<SearchBox onJump={vi.fn<() => void>()} />, { at: '/search?q=export' })

        await act(() => router.navigate({ to: '/search', search: { q: 'csv' } }))
        expect(box().value).toBe('csv')
    })

    it('takes the focus on `/` from the page, not from a text field, and gives it back on Escape', async () => {
        await renderRouted(
            <>
                <SearchBox onJump={vi.fn<() => void>()} />
                <textarea aria-label="Reply" />
            </>,
        )
        const reply = screen.getByRole('textbox', { name: 'Reply' })

        reply.focus()
        fireEvent.keyDown(reply, { key: '/' })
        expect(document.activeElement).toBe(reply)

        reply.blur()
        fireEvent.keyDown(document.body, { key: '/' })
        expect(document.activeElement).toBe(box())

        fireEvent.keyDown(box(), { key: 'Escape' })
        expect(document.activeElement).not.toBe(box())
    })
})
