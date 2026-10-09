import type { CSSProperties } from 'react'

import { rollCells } from '@/lib/roll'

/**
 * A readout whose digits roll to a new value, like an odometer, and roll up from zero when it first appears. The value
 * is in the text once, for screen readers and tests; the rolling glyphs are drawn by CSS (`roll-*` in index.css).
 */
export function RollingNumber({ value }: { value: string }) {
    return (
        <span className="inline-flex">
            <span className="sr-only">{value}</span>
            <span aria-hidden className="inline-flex">
                {rollCells(value).map((cell) =>
                    cell.kind === 'digit' ? (
                        <span key={cell.key} className="roll-window">
                            <span
                                className="roll-strip"
                                style={{ '--digit': cell.digit, '--place': cell.place } as CSSProperties}
                            />
                        </span>
                    ) : (
                        <span key={cell.key} className="roll-glyph" data-glyph={cell.glyph} />
                    ),
                )}
            </span>
        </span>
    )
}
