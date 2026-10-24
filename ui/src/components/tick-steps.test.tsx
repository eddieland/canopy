import { cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderRouted } from '@/test-utils'

import { TickSteps } from './tick-steps'

afterEach(() => {
    cleanup()
})

describe('TickSteps', () => {
    it('links to the ticks either side, each named for the tick it opens', async () => {
        const { router } = await renderRouted(<TickSteps previous={40} next={42} />, { at: '/runs/ticks/41' })
        expect(screen.getByRole('link', { name: 'tick:40' }).getAttribute('href')).toBe('/runs/ticks/40')
        fireEvent.click(screen.getByRole('link', { name: 'tick:42' }))
        await expect.poll(() => router.state.location.pathname).toBe('/runs/ticks/42')
    })

    it('keeps a disabled button at the oldest end that says there is no older tick', async () => {
        await renderRouted(<TickSteps previous={null} next={2} />, { at: '/runs/ticks/1' })
        const older = screen.getByRole('button', { name: 'older' })
        expect(older).toHaveProperty('disabled', true)
        expect(older.getAttribute('title')).toBe('no older tick: this is the first')
        expect(screen.queryByRole('link', { name: /older/u })).toBeNull()
        expect(screen.getByRole('link', { name: 'tick:2' })).toBeDefined()
    })

    it('keeps a disabled button at the newest end until the next tick starts', async () => {
        await renderRouted(<TickSteps previous={1} next={null} />, { at: '/runs/ticks/2' })
        const newer = screen.getByRole('button', { name: 'newer' })
        expect(newer).toHaveProperty('disabled', true)
        expect(newer.getAttribute('title')).toBe('no newer tick yet: this is the latest')
        expect(screen.getByRole('link', { name: 'tick:1' })).toBeDefined()
    })
})
