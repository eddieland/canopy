import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { Chip, Word } from './status'

afterEach(() => {
    cleanup()
})

describe('Chip', () => {
    it("reads a journal word as words, with the CLI's spelling on hover", () => {
        render(
            <>
                <Chip word="worker_failed" />
                <Chip word="attention:needs_reviewer" />
            </>,
        )
        expect(screen.getByTitle('worker_failed').textContent).toBe('worker failed')
        expect(screen.getByTitle('attention:needs_reviewer').textContent).toBe('attention: needs reviewer')
    })

    it('has no hover when the word already reads as the CLI spells it, or it holds its own text', () => {
        const { container } = render(
            <>
                <Chip word="wait" />
                <Chip>dry run</Chip>
            </>,
        )
        expect(container.textContent).toBe('waitdry run')
        expect(screen.queryByTitle(/./u)).toBeNull()
    })
})

describe('Word', () => {
    it("reads a phase or a status as words, with the CLI's spelling on hover only where they differ", () => {
        render(
            <>
                <Word word="ci_failing" />
                <Word word="ok" />
            </>,
        )
        expect(screen.getByTitle('ci_failing').textContent).toBe('ci failing')
        expect(screen.getByText('ok').title).toBe('')
    })

    it('shows the readable text it is given in place of the word, keeping the word on hover', () => {
        render(<Word word="needs_human" text="needs human (plan)" />)
        expect(screen.getByTitle('needs_human').textContent).toBe('needs human (plan)')
    })
})
