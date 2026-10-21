import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { RunPersona } from '@/api/types'

import { PersonaPanel } from './persona-panel'

const DIGEST = '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b'
// Wrapped at a column, as a persona's file is: it reads as two paragraphs, their lines joined.
const TEXT = 'Name the input that breaks a claim\nbefore you accept it.\n\nPress hardest on failure paths.'
const SHOWN = 'Name the input that breaks a claim before you accept it.Press hardest on failure paths.'
const SKEPTIC: RunPersona = { name: 'skeptic', digest: DIGEST, text: TEXT, problem: null }

afterEach(() => {
    cleanup()
})

// What the panel shows of the persona's instructions, once open.
function shown() {
    return screen.getByRole('region', { name: "the persona's instructions" }).textContent
}

describe('PersonaPanel', () => {
    it('arrives folded to its name and digest, and opens to the instructions the run read', () => {
        render(<PersonaPanel persona={SKEPTIC} />)
        expect(screen.getByText('Persona')).toBeDefined()
        expect(screen.getByText('skeptic')).toBeDefined()
        expect(screen.getByTitle(DIGEST).textContent).toBe(' 1a2b3c4d5e6f')
        expect(screen.queryByRole('region', { name: "the persona's instructions" })).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Show instructions', expanded: false }))
        expect(shown()).toBe(SHOWN)
    })

    it('says why when canopy cannot tell what the run read', () => {
        const problem = 'canopy kept no text, and its file has been edited since the run read it'
        render(<PersonaPanel persona={{ ...SKEPTIC, text: null, problem }} />)

        fireEvent.click(screen.getByRole('button', { name: 'Show instructions' }))
        expect(screen.getByText(`no text: ${problem}`)).toBeDefined()
        expect(screen.queryByRole('region', { name: "the persona's instructions" })).toBeNull()
    })
})
