import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { TranscriptEntry, TranscriptPrompt } from '@/api/types'
import { contextShape } from '@/lib/transcript'

import { ContextChart } from './context-chart'

afterEach(() => {
    cleanup()
})

function text(call: number, said: string): TranscriptEntry {
    return { kind: 'text', call, at: null, text: said, reasoning: false, cut: false }
}

function read(call: number, path: string, output: string): TranscriptEntry {
    return {
        kind: 'tool',
        call,
        at: null,
        tool: 'read',
        title: null,
        input: JSON.stringify({ filePath: path }),
        output,
        status: 'completed',
        duration_ms: null,
        cut: false,
    }
}

// A model call's end, `sent` tokens all uncached, or none counted for null.
function step(call: number, sent: number | null): TranscriptEntry {
    return {
        kind: 'step',
        call,
        at: null,
        reason: 'tool-calls',
        split: sent === null ? null : { input: sent, cache_read: 0, cache_write: 0, output: 0, reasoning: 0 },
        tokens: sent,
        cost_usd: null,
    }
}

// 400 characters: about 100 tokens.
const PROMPT: TranscriptPrompt = { text: 'p'.repeat(400), truncated: false }

// Call 1 reads a file and says a line; call 2 is sent 400 more tokens for them; the runtime counts nothing for call 3,
// so nothing says what grew call 4.
const SESSION: TranscriptEntry[] = [
    text(1, 'Reading the tests.'),
    read(1, 'a.ts', 'x'.repeat(300)),
    step(1, 1000),
    step(2, 1400),
    step(3, null),
    step(4, 1200),
]

function chart(
    entries: TranscriptEntry[],
    prompt: TranscriptPrompt | null = PROMPT,
    onShow: (i: number) => void = () => {},
) {
    return render(<ContextChart shape={contextShape(entries, prompt)} onShow={onShow} open onOpenChange={() => {}} />)
}

// Whether some element says `words` whole, however its pieces are split among elements.
function says(words: string): boolean {
    return screen.queryAllByText((_, element) => element?.textContent === words).length > 0
}

function pick(name: string) {
    fireEvent.click(screen.getByRole('radio', { name }))
}

describe('ContextChart', () => {
    it('draws nothing when the runtime counted no tokens for any call', () => {
        const { container } = chart([text(1, 'hello'), step(1, null)])
        expect(container.childElementCount).toBe(0)
    })

    it('has only its line for a session of one call, the call all prompt and overhead on its peak', () => {
        chart([text(1, 'Done.'), step(1, 500)], null)
        const peak = screen.getByText('peak 500 at call 1')
        expect(peak.title).toBe('500 tokens: canopy kept no prompt, so all of it reads as the runtime’s own')
        expect(screen.queryByRole('radio')).toBeNull()
        expect(screen.queryByRole('button', { name: /chart/u })).toBeNull()
        expect(screen.queryByText(/^call 1/u)).toBeNull()
    })

    it('has only its line when a second call printed but the runtime counted no tokens for it', () => {
        const error: TranscriptEntry = { kind: 'error', call: 2, at: null, name: 'ProviderError', message: 'down' }
        chart([text(1, 'Reading.'), step(1, 500), error])
        expect(screen.getByText('peak 500 at call 1')).toBeDefined()
        expect(screen.queryByRole('radiogroup')).toBeNull()
        expect(screen.queryByRole('button', { name: /chart/u })).toBeNull()
    })

    it('folds its bars under its line, the largest addition still shown from there', () => {
        const onShow = vi.fn<(i: number) => void>()
        const onOpenChange = vi.fn<(open: boolean) => void>()
        render(
            <ContextChart
                shape={contextShape(SESSION, PROMPT)}
                onShow={onShow}
                open={false}
                onOpenChange={onOpenChange}
            />,
        )
        expect(screen.queryByRole('radiogroup')).toBeNull()
        expect(screen.queryByTestId('context-grew')).toBeNull()
        fireEvent.click(within(screen.getByTestId('context-largest')).getByRole('button'))
        expect(onShow).toHaveBeenCalledWith(1)
        fireEvent.click(screen.getByRole('button', { name: 'Show chart' }))
        expect(onOpenChange).toHaveBeenCalledWith(true)
    })

    it('names each call by what it was sent, and picks the one the largest addition grew', () => {
        chart(SESSION)
        expect(screen.getByText('peak 1.4k at call 2')).toBeDefined()
        const largest = screen.getByTestId('context-largest')
        expect(within(largest).getByRole('button', { name: 'read filePath=a.ts' })).toBeDefined()
        expect(largest.textContent).toContain('≈379 into call 2')

        const calls = within(screen.getByRole('radiogroup', { name: 'Model calls' })).getAllByRole('radio')
        expect(calls.map((c) => [c.getAttribute('aria-label'), c.getAttribute('aria-checked')])).toEqual([
            ['call 1: 1.0k sent', 'false'],
            ['call 2: 1.4k sent, +400 on the call before', 'true'],
            ['call 3: the runtime counted no tokens', 'false'],
            ['call 4: 1.2k sent', 'false'],
        ])
        // What grew it, largest first, each by its share of the step.
        expect(says('call 2, 1.4k sent, +400 on call 1, from what call 1 printed, largest first:')).toBe(true)
        const grew = within(screen.getByTestId('context-grew'))
        expect(grew.getAllByRole('button').map((button) => button.textContent)).toEqual([
            'readfilePath=a.ts',
            'textReading the tests.',
        ])
        expect(grew.getByText('≈379')).toBeDefined()
        expect(grew.getByText('≈21')).toBeDefined()
    })

    it('says what grew the call picked, or why nothing can say', () => {
        chart(SESSION)
        pick('call 1: 1.0k sent')
        expect(
            says(
                'call 1, 1.0k sent: ≈100 canopy’s prompt, ≈900 the runtime’s own: the agent’s definition, its ' +
                    'system prompt, and its tools',
            ),
        ).toBe(true)
        pick('call 3: the runtime counted no tokens')
        expect(says('call 3: the runtime counted no tokens for it')).toBe(true)
        pick('call 4: 1.2k sent')
        expect(says('call 4, 1.2k sent: the runtime counted no tokens for call 3, so nothing says what grew it')).toBe(
            true,
        )
        // Pressing the picked call again leaves it picked: there is always one named.
        pick('call 4: 1.2k sent')
        expect(screen.getByRole('radio', { name: 'call 4: 1.2k sent' }).getAttribute('aria-checked')).toBe('true')
    })

    it('says when a call grew by nothing, or the runtime dropped some of what it carried', () => {
        chart([text(1, 'one'), step(1, 1000), text(2, 'two'), step(2, 1000), step(3, 800)])
        pick('call 2: 1.0k sent, +0 on the call before')
        expect(says('call 2, 1.0k sent, +0 on call 1: nothing grew it')).toBe(true)
        pick('call 3: 800 sent, -200 on the call before')
        expect(says('call 3, 800 sent, -200 on call 2: the runtime dropped part of what it carried')).toBe(true)
    })

    it('lists five additions, and counts the rest on one line', () => {
        const printed = Array.from({ length: 7 }, (_, i) => text(1, `line ${i} `.padEnd(10 * (7 - i), '.')))
        chart([...printed, step(1, 100), step(2, 800)])
        const grew = within(screen.getByTestId('context-grew'))
        expect(grew.getAllByRole('button')).toHaveLength(5)
        expect(grew.getByText('2 more entries')).toBeDefined()
    })

    it('shows an addition’s row in the transcript, by its place in the entries', () => {
        const onShow = vi.fn<(i: number) => void>()
        chart(SESSION, PROMPT, onShow)
        fireEvent.click(within(screen.getByTestId('context-grew')).getByRole('button', { name: /^text/u }))
        expect(onShow).toHaveBeenCalledWith(0)
    })
})
