import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { tipOf } from '@/test-utils'

import { Chip, Word } from './status'

afterEach(() => {
    cleanup()
})

describe('Chip', () => {
    it("reads a journal word as words, with the CLI's spelling in its tip", () => {
        render(
            <>
                <Chip word="worker_failed" />
                <Chip word="attention:needs_reviewer" />
            </>,
        )
        expect(tipOf(screen.getByText('worker failed'))).toBe('worker_failed')
        expect(tipOf(screen.getByText('attention: needs reviewer'))).toBe('attention:needs_reviewer')
    })

    it('has no tip when the word already reads as the CLI spells it, or it holds its own text', () => {
        const { container } = render(
            <>
                <Chip word="wait" />
                <Chip>dry run</Chip>
            </>,
        )
        expect(container.textContent).toBe('waitdry run')
        expect(tipOf(screen.getByText('wait'))).toBeNull()
        expect(tipOf(screen.getByText('dry run'))).toBeNull()
    })

    it('says under its word what the word means, whenever it is given a meaning', () => {
        render(
            <>
                <Chip word="review_late" meaning="A late finding." />
                <Chip word="approved" meaning="Approved, not merged." />
            </>,
        )
        expect(tipOf(screen.getByText('review late'))).toBe('review_late\nA late finding.')
        expect(tipOf(screen.getByText('approved'))).toBe('approved\nApproved, not merged.')
    })

    it('holds its word whole in its tip when the word is cut to fit', () => {
        vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(120)
        vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(40)
        render(<Chip word="implement" className="min-w-0 shrink" />)
        expect(tipOf(screen.getByText('implement'))).toBe('implement')
    })
})

describe('Word', () => {
    it("reads a phase or a status as words, with the CLI's spelling in its tip only where they differ", () => {
        render(
            <>
                <Word word="ci_failing" />
                <Word word="ok" />
            </>,
        )
        expect(tipOf(screen.getByText('ci failing'))).toBe('ci_failing')
        expect(tipOf(screen.getByText('ok'))).toBeNull()
    })

    it('shows the readable text it is given in place of the word, keeping the word in its tip', () => {
        render(<Word word="needs_human" text="needs human (plan)" />)
        expect(tipOf(screen.getByText('needs human (plan)'))).toBe('needs_human')
    })

    it('says what the word means in its tip, under the word', () => {
        render(<Word word="merged" meaning="Its PR is merged." />)
        expect(tipOf(screen.getByText('merged'))).toBe('merged\nIts PR is merged.')
    })
})
