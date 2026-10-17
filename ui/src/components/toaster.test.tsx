import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useToast } from '@/hooks/use-toast'
import type { NewToast } from '@/lib/toasts'

import { Toaster } from './toaster'

// A control that shows the toast it is given, as a copy button does.
function Shows({ toast }: { toast: NewToast }) {
    const show = useToast()
    return (
        <button type="button" onClick={() => show(toast)}>
            {toast.title}
        </button>
    )
}

function renderToaster(...toasts: NewToast[]) {
    return render(
        <Toaster>
            {toasts.map((toast) => (
                <Shows key={toast.title} toast={toast} />
            ))}
        </Toaster>,
    )
}

// The toasts shown, each by what it says, in the landmark F8 moves the focus to.
function shown(): string[] {
    const region = screen.getByRole('region', { name: 'Notifications (F8)' })
    return within(region)
        .queryAllByRole('listitem')
        .map((toast) => toast.textContent)
}

beforeEach(() => {
    vi.useFakeTimers()
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

describe('Toaster', () => {
    it('shows what a control asks for, its title over its detail, and nothing before', () => {
        renderToaster({ title: 'Copied branch', detail: 'agent/ABC-1', tone: 'done' })
        expect(shown()).toEqual([])
        fireEvent.click(screen.getByRole('button', { name: 'Copied branch' }))
        expect(shown()).toEqual(['Copied branchagent/ABC-1'])
    })

    it('closes a toast on its own after 3 seconds', () => {
        renderToaster({ title: 'Could not copy branch', tone: 'failed' })
        fireEvent.click(screen.getByRole('button', { name: 'Could not copy branch' }))
        act(() => {
            vi.advanceTimersByTime(2999)
        })
        expect(shown()).toEqual(['Could not copy branch'])
        act(() => {
            vi.advanceTimersByTime(1)
        })
        expect(shown()).toEqual([])
    })

    it('shows at most three at once, the newest last, closing the oldest for a fourth', () => {
        const toasts = ['One', 'Two', 'Three', 'Four'].map((title): NewToast => ({ title, tone: 'done' }))
        renderToaster(...toasts)
        for (const { title } of toasts) {
            fireEvent.click(screen.getByRole('button', { name: title }))
        }
        expect(shown()).toEqual(['Two', 'Three', 'Four'])
    })
})
