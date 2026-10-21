import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { Transcript, TranscriptPrompt } from '@/api/types'

import { PromptPanel } from './prompt-panel'

const TEXT = 'Implement ABC-1: sign in with SSO.\nThe ticket: https://example.atlassian.net/browse/ABC-1\n'

afterEach(() => {
    cleanup()
})

// A transcript with no events, as a run that died before its first has: the prompt is still kept.
function transcript(prompt: TranscriptPrompt | null, removed: number | null = null): Transcript {
    return {
        session_id: null,
        status: 'no_log',
        entries: [],
        prompt,
        truncated: false,
        unreadable: 0,
        removed_after_days: removed,
    }
}

// What the panel shows of the prompt, once open.
function shown() {
    return screen.getByRole('region', { name: 'the prompt' }).textContent
}

describe('PromptPanel', () => {
    it('arrives folded to its length, and opens to the prompt from its start, its links live', () => {
        render(<PromptPanel transcript={transcript({ text: TEXT, truncated: false })} />)
        expect(screen.getByText('2 lines · 90 B')).toBeDefined()
        expect(screen.queryByRole('region', { name: 'the prompt' })).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Show prompt', expanded: false }))
        expect(shown()).toBe(TEXT)
        expect(screen.getByRole('link', { name: 'https://example.atlassian.net/browse/ABC-1' })).toBeDefined()
        expect(screen.queryByText(/^cut:/u)).toBeNull()
    })

    it('says a prompt past the read is cut, and shows its start', () => {
        render(<PromptPanel transcript={transcript({ text: 'one line', truncated: true })} />)
        expect(screen.getByText('1 line · 8 B, cut')).toBeDefined()

        fireEvent.click(screen.getByRole('button', { name: 'Show prompt' }))
        expect(screen.getByText('cut: the file holds more, and this is its start')).toBeDefined()
        expect(shown()).toBe('one line')
    })

    it('is its header alone, saying so, when canopy kept no prompt', () => {
        render(<PromptPanel transcript={transcript(null)} />)
        expect(screen.getByText('Prompt')).toBeDefined()
        expect(screen.getByText('none kept')).toBeDefined()
        expect(screen.queryByRole('button', { name: 'Show prompt' })).toBeNull()
    })

    it('says after how many days retention removed it, with its log', () => {
        render(<PromptPanel transcript={transcript(null, 7)} />)
        expect(screen.getByText('removed after 7 days').title).toBe(
            'your [retention] keeps a prompt as long as its log, once it ends',
        )
        expect(screen.queryByText('none kept')).toBeNull()
    })

    it('holds its header while the transcript is read', () => {
        render(<PromptPanel transcript={undefined} />)
        expect(screen.getByText('Prompt')).toBeDefined()
        expect(screen.queryByRole('button', { name: 'Show prompt' })).toBeNull()
    })
})
