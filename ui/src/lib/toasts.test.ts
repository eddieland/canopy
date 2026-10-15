import { describe, expect, it } from 'vitest'

import { addToast, closeToast, MAX_TOASTS } from './toasts'
import type { ToastItem } from './toasts'

const copied = { title: 'Copied branch', detail: 'agent/ABC-1', tone: 'done' } as const

describe('addToast', () => {
    it('adds a toast last, open, with an id past every other', () => {
        const one = addToast([], copied)
        expect(one).toEqual([{ ...copied, id: 1, open: true }])
        expect(addToast(one, copied).map((t) => t.id)).toEqual([1, 2])
    })

    it('drops the toasts already closed, but never reuses their ids', () => {
        const closed = closeToast(addToast(addToast([], copied), copied), 2)
        expect(addToast(closed, copied).map((t) => [t.id, t.open])).toEqual([
            [1, true],
            [3, true],
        ])
    })

    it('closes the oldest past the most shown at once', () => {
        let toasts: ToastItem[] = []
        for (let i = 0; i < MAX_TOASTS + 1; i += 1) {
            toasts = addToast(toasts, copied)
        }
        expect(toasts.filter((t) => t.open)).toHaveLength(MAX_TOASTS)
        expect(toasts[0]).toMatchObject({ id: 1, open: false })
        expect(toasts.at(-1)).toMatchObject({ id: MAX_TOASTS + 1, open: true })
    })
})

describe('closeToast', () => {
    it('closes that toast alone, keeping it for its exit', () => {
        const toasts = closeToast(addToast(addToast([], copied), copied), 1)
        expect(toasts.map((t) => [t.id, t.open])).toEqual([
            [1, false],
            [2, true],
        ])
    })
})
