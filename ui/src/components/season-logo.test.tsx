import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { LogoDecoration } from '@/components/season-logo'

afterEach(cleanup)

describe('LogoDecoration', () => {
    it('strings a web over the logo at Halloween, and lights in winter', () => {
        render(<LogoDecoration id="halloween" />)
        expect(screen.getByTestId('logo-season').dataset['season']).toBe('halloween')
        cleanup()
        render(<LogoDecoration id="winter" />)
        expect(screen.getByTestId('logo-season').dataset['season']).toBe('winter')
    })

    it('leaves the logo bare in a season that hangs nothing on it', () => {
        render(<LogoDecoration id="spring" />)
        expect(screen.queryByTestId('logo-season')).toBeNull()
    })
})
