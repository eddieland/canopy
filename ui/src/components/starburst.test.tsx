import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { burstWord } from '@/lib/burst'

import { Starburst } from './starburst'

afterEach(cleanup)

const ID = 'awaiting_reply:ABC-102'

describe('Starburst', () => {
    it("letters its item's sound effect", () => {
        render(<Starburst id={ID} />)
        expect(screen.getByTestId('starburst').textContent).toBe(burstWord(ID))
    })

    it('is for the eye alone: a screen reader hears the count change instead', () => {
        render(<Starburst id={ID} />)
        expect(screen.getByTestId('starburst').getAttribute('aria-hidden')).toBe('true')
    })
})
