import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { loadText } from '@/lib/host'
import { trend } from '@/lib/trend'
import type { Trend } from '@/lib/trend'

import { TrendChart } from './trend-chart'

afterEach(cleanup)

// Three readings of the load, ten seconds apart, over a chart that keeps three.
function loads(): Trend {
    const found = trend(
        {
            every_seconds: 10,
            kept: 3,
            samples: [1.2, 3.4, 2.41].map((load, i) => ({
                at: new Date(Date.parse('2026-10-08T12:00:00Z') + i * 10_000).toISOString(),
                load,
                cpu_busy: null,
                memory_used: null,
                swap_used: null,
                memory_stalled: null,
                io_stalled: null,
                rss: null,
                disks: [],
            })),
        },
        (s) => s.load,
    )
    if (found === null) {
        throw new Error('no trend')
    }
    return found
}

describe('TrendChart', () => {
    it('says the latest value and the peak, and tells a screen reader what the plot shows', () => {
        render(<TrendChart label="Load" trend={loads()} top={5} format={loadText} />)
        expect(screen.getByTestId('trend-value').textContent).toBe('2.41 now · peak 3.40')
        expect(screen.getByText('Load over the last 0 minutes: 2.41 now, peak 3.40, low 1.20')).toBeTruthy()
    })

    it('draws its reference while it is under the top, and not past it', () => {
        const { rerender } = render(
            <TrendChart
                label="Load"
                trend={loads()}
                top={5}
                format={loadText}
                reference={{ value: 4, label: '4 cores' }}
            />,
        )
        expect(screen.queryByText('4 cores')).not.toBeNull()
        rerender(
            <TrendChart
                label="Load"
                trend={loads()}
                top={5}
                format={loadText}
                reference={{ value: 12, label: '12 cores' }}
            />,
        )
        expect(screen.queryByText('12 cores')).toBeNull()
    })

    it("says the reading under the pointer in the latest's place, and the latest again once it leaves", () => {
        render(<TrendChart label="Load" trend={loads()} top={5} format={loadText} />)
        const plot = screen.getByTestId('trend-plot')
        plot.getBoundingClientRect = () => DOMRect.fromRect({ x: 0, y: 0, width: 200, height: 80 })
        fireEvent.pointerMove(plot, { clientX: 100 })
        expect(screen.getByTestId('trend-value').textContent).toMatch(/^3\.40 at /u)
        fireEvent.pointerLeave(plot)
        expect(screen.getByTestId('trend-value').textContent).toBe('2.41 now · peak 3.40')
    })
})
