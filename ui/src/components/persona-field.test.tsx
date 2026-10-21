import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { PersonaField } from './persona-field'

const DIGEST = '1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b'

afterEach(cleanup)

describe('PersonaField', () => {
    it('shows the persona a run had and the start of its digest, as canopy status does, the whole on hover', () => {
        render(
            <dl>
                <PersonaField persona="skeptic" digest={DIGEST} />
            </dl>,
        )
        expect(screen.getByRole('term').textContent).toBe('persona')
        expect(screen.getByRole('definition').textContent).toBe('skeptic 1a2b3c4d5e6f')
        expect(screen.getByTitle(DIGEST).textContent).toBe(' 1a2b3c4d5e6f')
    })

    it('shows nothing for a run no persona reached', () => {
        const { container } = render(
            <dl>
                <PersonaField persona={null} digest={null} />
            </dl>,
        )
        expect(container.querySelector('dl')?.childElementCount).toBe(0)
    })
})
