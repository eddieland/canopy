import { afterEach, describe, expect, it } from 'vitest'

import { printLine, printsAPlan } from './plan-print'

const stops: (() => void)[] = []
const root = document.documentElement

afterEach(() => {
    for (const stop of stops.splice(0)) {
        stop()
    }
    root.classList.remove('dark')
    delete root.dataset['printing']
})

describe('a plan printed', () => {
    it('opens with a line naming its ticket, which plan it is, where it stands, and when it was written', () => {
        expect(printLine('ABC-105', 2, 'proposed', '2026-10-08T11:00:00Z')).toBe(
            'ABC-105 · plan 2 · waiting on you · written Oct 8, 2026',
        )
        expect(printLine('epic:2', 3, 'approved', '2026-10-08T11:00:00Z')).toBe(
            'epic:2 · plan 3 · approved · written Oct 8, 2026',
        )
    })

    it('takes the light theme for the print and gives the dark one back after', () => {
        root.classList.add('dark')
        stops.push(printsAPlan())
        globalThis.dispatchEvent(new Event('beforeprint'))
        expect(root.classList.contains('dark')).toBe(false)
        expect(root.dataset['printing']).toBe('plan')
        globalThis.dispatchEvent(new Event('afterprint'))
        expect(root.classList.contains('dark')).toBe(true)
        expect(root.dataset['printing']).toBeUndefined()
    })

    it('leaves a light page light, and stops when its plan leaves the page', () => {
        stops.push(printsAPlan())
        globalThis.dispatchEvent(new Event('beforeprint'))
        globalThis.dispatchEvent(new Event('afterprint'))
        expect(root.classList.contains('dark')).toBe(false)

        stops.pop()?.()
        root.classList.add('dark')
        globalThis.dispatchEvent(new Event('beforeprint'))
        expect(root.classList.contains('dark')).toBe(true)
        expect(root.dataset['printing']).toBeUndefined()
    })
})
