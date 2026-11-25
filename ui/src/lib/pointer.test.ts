import { describe, expect, it } from 'vitest'

import { isOver, pointerAt } from './pointer'

describe('pointerAt', () => {
    it('is where the pointer last moved to, and unknown once it leaves the window', () => {
        document.dispatchEvent(new MouseEvent('pointermove', { clientX: 40, clientY: 12 }))
        expect(pointerAt()).toEqual({ x: 40, y: 12 })
        document.documentElement.dispatchEvent(new MouseEvent('pointerleave'))
        expect(pointerAt()).toBeNull()
    })
})

describe('isOver', () => {
    it('is true on the element and within its reach, and never for no element or no point', () => {
        const element = document.createElement('div')
        element.getBoundingClientRect = () => new DOMRect(10, 10, 100, 20)
        expect(isOver(element, { x: 50, y: 20 })).toBe(true)
        expect(isOver(element, { x: 114, y: 20 })).toBe(false)
        expect(isOver(element, { x: 114, y: 20 }, 8)).toBe(true)
        expect(isOver(null, { x: 50, y: 20 })).toBe(false)
        expect(isOver(element, null)).toBe(false)
    })
})
