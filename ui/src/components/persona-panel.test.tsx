import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { RunPersona } from '@/api/types'

import { PersonaPanel } from './persona-panel'

const DIGEST = '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b'
// Wrapped at a column, as a persona's file is: it reads as two paragraphs, their lines joined.
const TEXT = 'Name the input that breaks a claim\nbefore you accept it.\n\nPress hardest on failure paths.'
const SHOWN = 'Name the input that breaks a claim before you accept it.Press hardest on failure paths.'
const SKEPTIC: RunPersona = { name: 'skeptic', digest: DIGEST, text: TEXT, problem: null, changed: false }

afterEach(() => {
    cleanup()
})

// What the panel shows of the persona's instructions, once open.
function shown() {
    return screen.getByRole('region', { name: "the persona's instructions" }).textContent
}

describe('PersonaPanel', () => {
    it('arrives folded to its name and digest, and opens to the instructions the run read', () => {
        render(<PersonaPanel persona={SKEPTIC} runId={44} />)
        expect(screen.getByText('Persona')).toBeDefined()
        expect(screen.getByText('skeptic')).toBeDefined()
        expect(screen.getByTitle(DIGEST).textContent).toBe(' 1a2b3c4d5e6f')
        expect(screen.queryByRole('region', { name: "the persona's instructions" })).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Show instructions', expanded: false }))
        expect(shown()).toBe(SHOWN)
        expect(screen.queryByText(/^edited since/u)).toBeNull()
    })

    it('says a file edited since the run read it is its text now, not the run’s', () => {
        render(<PersonaPanel persona={{ ...SKEPTIC, changed: true }} runId={44} />)
        expect(screen.getByText(', edited since')).toBeDefined()

        fireEvent.click(screen.getByRole('button', { name: 'Show instructions' }))
        expect(
            screen.getByText('edited since run 44 read it: this is its text now, not the one that run read'),
        ).toBeDefined()
        expect(shown()).toBe(SHOWN)
    })

    it('says why when the file cannot be read', () => {
        const gone = { ...SKEPTIC, text: null, problem: 'persona skeptic has no file among canopy’s own' }
        render(<PersonaPanel persona={gone} runId={44} />)
        fireEvent.click(screen.getByRole('button', { name: 'Show instructions' }))
        expect(screen.getByText(/its file cannot be read: persona skeptic has no file/u)).toBeDefined()
    })
})
