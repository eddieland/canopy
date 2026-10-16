import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ToastContext } from '@/hooks/use-toast'
import type { NewToast } from '@/lib/toasts'

import { CopyButton } from './copy-button'

let toasts: NewToast[] = []

function renderButton() {
    return render(
        <ToastContext
            value={(toast) => {
                toasts.push(toast)
            }}
        >
            <CopyButton text="canopy/ABC-1" label="branch" />
        </ToastContext>,
    )
}

// Lets the clipboard's promise settle, and React render what it did.
async function settle() {
    await act(async () => {
        await Promise.resolve()
    })
}

beforeEach(() => {
    toasts = []
    vi.stubGlobal('isSecureContext', true)
    vi.useFakeTimers()
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

describe('CopyButton', () => {
    it('renders nothing where the page cannot reach the clipboard', () => {
        vi.stubGlobal('isSecureContext', false)
        const { container } = renderButton()
        expect(container.childElementCount).toBe(0)
    })

    it('copies its text, says so on the button and in a toast, then reads Copy again', async () => {
        const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
        renderButton()

        fireEvent.click(screen.getByRole('button', { name: 'Copy branch' }))
        await settle()
        expect(write).toHaveBeenCalledWith('canopy/ABC-1')
        expect(screen.getByRole('button', { name: 'Copied branch' })).toBeDefined()
        expect(toasts).toEqual([{ title: 'Copied branch', detail: 'canopy/ABC-1', tone: 'done' }])

        act(() => {
            vi.advanceTimersByTime(1499)
        })
        expect(screen.getByRole('button', { name: 'Copied branch' })).toBeDefined()
        act(() => {
            vi.advanceTimersByTime(1)
        })
        expect(screen.getByRole('button', { name: 'Copy branch' })).toBeDefined()
    })

    it('says so when the browser refuses the clipboard', async () => {
        vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
        renderButton()

        fireEvent.click(screen.getByRole('button', { name: 'Copy branch' }))
        await settle()
        expect(screen.getByRole('button', { name: 'Could not copy branch' })).toBeDefined()
        expect(toasts).toEqual([
            { title: 'Could not copy branch', detail: 'The browser refused the clipboard.', tone: 'failed' },
        ])
    })
})
