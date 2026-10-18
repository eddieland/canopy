import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ChoreLimitBanner } from './chore-limit'

afterEach(() => {
    cleanup()
})

describe('ChoreLimitBanner', () => {
    it('says a chore is over its finding limit, by how much, and what to do', () => {
        render(<ChoreLimitBanner chore={{ name: 'deps', max_findings: 5, more_findings: 12 }} />)
        const band = screen.getByRole('region', { name: 'Over its finding limit' })
        expect(band.textContent).toContain(
            'Over its finding limit: its latest ok run found 12 more than the 5 it may list.',
        )
        expect(band.textContent).toContain(
            'Raise max_findings in [chores.deps], or narrow what it reports with a note.',
        )
        expect(screen.getAllByRole('code').map((c) => c.textContent)).toEqual(['max_findings', '[chores.deps]'])
    })

    it('shows nothing for a chore within its limit', () => {
        const { container } = render(<ChoreLimitBanner chore={{ name: 'deps', max_findings: 5, more_findings: 0 }} />)
        expect(container.childElementCount).toBe(0)
    })
})
