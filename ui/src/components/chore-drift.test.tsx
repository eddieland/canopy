import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ChoreDriftBanner } from './chore-drift'

afterEach(() => {
    cleanup()
})

describe('ChoreDriftBanner', () => {
    it('names the newer version, the one it was installed from, and the command that shows the difference', () => {
        render(
            <ChoreDriftBanner
                name="build-health"
                drift={{ standing: 'changed', installed_by: '0.9.0', shipped_by: '1.2.0' }}
            />,
        )
        const band = screen.getByRole('region', { name: 'Canopy ships a newer version' })
        expect(band.textContent).toContain(
            'Canopy ships a newer version: canopy 1.2.0 ships its prompt or agent otherwise than canopy 0.9.0 ' +
                'that installed it.',
        )
        expect(screen.getAllByRole('code').map((c) => c.textContent)).toEqual(['canopy chore diff build-health'])
    })

    it('says a chore installed before canopy kept a record differs, without claiming whose edits they are', () => {
        render(
            <ChoreDriftBanner
                name="build-health"
                drift={{ standing: 'differs', installed_by: null, shipped_by: '1.2.0' }}
            />,
        )
        const band = screen.getByRole('region', { name: 'Differs from the version canopy ships' })
        expect(band.textContent).toContain('its copy differs from what canopy 1.2.0 ships.')
        expect(band.textContent).toContain('but not whose edits are whose.')
        expect(screen.getAllByRole('code').map((c) => c.textContent)).toEqual(['canopy chore diff build-health'])
    })

    it('shows nothing for a chore that has not moved apart from canopy', () => {
        render(<ChoreDriftBanner name="deps" drift={null} />)
        expect(screen.queryByRole('region')).toBeNull()
        render(<ChoreDriftBanner name="deps" drift={undefined} />)
        expect(screen.queryByRole('region')).toBeNull()
    })
})
