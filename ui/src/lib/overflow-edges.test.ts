import { afterEach, describe, expect, it } from 'vitest'

import { markOverflowEdges } from '@/lib/overflow-edges'

const stops: (() => void)[] = []

// A box `width` wide holding `content`, scrolled `left`: happy-dom lays nothing out, so its sizes are set here.
function box(width: number, content: number): HTMLElement {
    const element = document.createElement('div')
    Object.defineProperty(element, 'clientWidth', { value: width })
    Object.defineProperty(element, 'scrollWidth', { value: content })
    document.body.append(element)
    stops.push(markOverflowEdges(element))
    return element
}

function scrollTo(element: HTMLElement, left: number): void {
    element.scrollLeft = left
    element.dispatchEvent(new Event('scroll'))
}

afterEach(() => {
    for (const stop of stops.splice(0)) {
        stop()
    }
    document.body.replaceChildren()
})

describe('the edges of a box that scrolls sideways', () => {
    it('are left alone while what it holds fits', () => {
        const element = box(600, 600)
        expect(element.hasAttribute('data-more-start')).toBe(false)
        expect(element.hasAttribute('data-more-end')).toBe(false)
    })

    it('mark the end at first, both while scrolled partway, and the start at the end', () => {
        const element = box(600, 1500)
        expect(element.hasAttribute('data-more-start')).toBe(false)
        expect(element.hasAttribute('data-more-end')).toBe(true)

        scrollTo(element, 400)
        expect(element.hasAttribute('data-more-start')).toBe(true)
        expect(element.hasAttribute('data-more-end')).toBe(true)

        scrollTo(element, 900)
        expect(element.hasAttribute('data-more-start')).toBe(true)
        expect(element.hasAttribute('data-more-end')).toBe(false)
    })

    it('stop changing once stopped', () => {
        const element = box(600, 1500)
        stops.pop()?.()
        scrollTo(element, 900)
        expect(element.hasAttribute('data-more-start')).toBe(false)
        expect(element.hasAttribute('data-more-end')).toBe(true)
    })
})
