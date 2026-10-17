import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { MemoryBand, MemoryText } from './memory'

afterEach(() => {
    cleanup()
})

// A note written to the journal by hand, past the bounds: a Markdown link, a bidi override, and a zero-width space.
const WRITTEN = 'See [the fix](https://evil.test) \u202Eeht and\u200Bthis.'

describe('MemoryText', () => {
    it('shows what a worker wrote as plain text, never a link, with each hidden character named', () => {
        const { container } = render(<MemoryText text={WRITTEN} />)
        expect(container.textContent).toBe('See [the fix](https://evil.test) <U+202E>eht and<U+200B>this.')
        expect(screen.queryByRole('link')).toBeNull()
        expect(container.textContent).not.toContain('\u202E')
        expect(screen.getAllByTitle('A character that hides text, which a model still reads')).toHaveLength(2)
    })
})

describe('MemoryBand', () => {
    it('says in words what reads a tier, so recording never reads as in use', () => {
        const { rerender } = render(
            <MemoryBand
                name="ticket notes"
                tier={{
                    mode: 'record',
                    words: 'recording',
                    band: 'Recording only. Workers write these notes; no run reads them.',
                }}
            />,
        )
        expect(screen.getByTestId('memory-band').textContent).toBe(
            'ticket notes: recordingRecording only. Workers write these notes; no run reads them.',
        )
        rerender(
            <MemoryBand
                name="ticket notes"
                tier={{ mode: 'use', words: 'in use', band: "In use. A ticket's later runs read its notes." }}
            />,
        )
        expect(screen.getByText('ticket notes: in use')).toBeTruthy()
        expect(screen.queryByText(/recording/u)).toBeNull()
    })
})
