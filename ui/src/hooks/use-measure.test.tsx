import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useMeasure } from './use-measure'
import type { MeasureOptions } from './use-measure'

// Stands in for ResizeObserver: measures once when it starts observing, as the browser does, and again when a test
// says what it watches changed size. It keeps what each one watches, so a test can tell what is observed.
class FakeResizeObserver implements ResizeObserver {
    static all: FakeResizeObserver[] = []
    readonly watched: Element[] = []
    disconnected = false
    readonly #callback: ResizeObserverCallback

    constructor(callback: ResizeObserverCallback) {
        this.#callback = callback
        FakeResizeObserver.all.push(this)
    }

    observe(target: Element): void {
        this.watched.push(target)
        this.#callback([], this)
    }

    unobserve(): void {}

    disconnect(): void {
        this.disconnected = true
    }

    resized(): void {
        this.#callback([], this)
    }
}

beforeEach(() => {
    FakeResizeObserver.all = []
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
})

afterEach(cleanup)

// A box that shows its width as `useMeasure` last read it with `width`.
function Box({ width, options }: { width: () => number; options?: MeasureOptions<number> }) {
    const [ref, measured] = useMeasure(width, -1, options)
    return (
        <div ref={ref}>
            <span>child</span>
            <output>{measured}</output>
        </div>
    )
}

function resize() {
    for (const observer of FakeResizeObserver.all) {
        observer.resized()
    }
}

describe('useMeasure', () => {
    it('measures before it is shown, and again when the element changes size', () => {
        let width = 100
        render(<Box width={() => width} />)
        expect(screen.getByRole('status').textContent).toBe('100')

        width = 240
        act(resize)
        expect(screen.getByRole('status').textContent).toBe('240')
    })

    it('watches the element alone, or its children too when asked', () => {
        const { unmount } = render(<Box width={() => 1} />)
        expect(FakeResizeObserver.all.at(-1)?.watched).toHaveLength(1)
        unmount()

        render(<Box width={() => 1} options={{ children: true }} />)
        expect(FakeResizeObserver.all.at(-1)?.watched).toHaveLength(3)
    })

    it('keeps the measure it has when a new one is the same', () => {
        let width = 100
        const same = vi.fn<(before: number, after: number) => boolean>((before, after) => Math.abs(before - after) < 10)
        render(<Box width={() => width} options={{ same }} />)
        expect(screen.getByRole('status').textContent).toBe('100')

        width = 105
        act(resize)
        expect(same).toHaveBeenLastCalledWith(100, 105)
        expect(screen.getByRole('status').textContent).toBe('100')

        width = 120
        act(resize)
        expect(screen.getByRole('status').textContent).toBe('120')
    })

    it('stops watching when the element goes', () => {
        const { unmount } = render(<Box width={() => 1} />)
        const observer = FakeResizeObserver.all.at(-1)
        unmount()
        expect(observer?.disconnected).toBe(true)
    })
})
