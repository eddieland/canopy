import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { SeasonDecoration } from '@/components/season'
import { SEASONS } from '@/lib/seasons'

afterEach(cleanup)

describe('SeasonDecoration', () => {
    it('hangs a web and flies a bat over Halloween where there is room above', () => {
        render(<SeasonDecoration id="halloween" aloft />)
        expect(screen.getByTestId('buddy-season').dataset['season']).toBe('halloween')
        expect(screen.getByTestId('buddy-season-air')).toBeDefined()
    })

    it('keeps to the floor where Sprig stands over the blocks above', () => {
        render(<SeasonDecoration id="halloween" aloft={false} />)
        expect(screen.getByTestId('buddy-season')).toBeDefined()
        expect(screen.queryByTestId('buddy-season-air')).toBeNull()
    })

    it('brings every season company on the floor and in the air', () => {
        for (const { id } of SEASONS) {
            render(<SeasonDecoration id={id} aloft />)
            expect(screen.getByTestId('buddy-season').dataset['season']).toBe(id)
            expect(screen.getByTestId('buddy-season-air')).toBeDefined()
            cleanup()
        }
    })
})
