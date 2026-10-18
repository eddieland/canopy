import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'

import { Notice } from './notice'

afterEach(() => {
    cleanup()
})

describe('Notice', () => {
    it('names the guard of a refusal, as the CLI does', () => {
        const refusal = new ApiError(409, { guard: 'not_started', reason: 'ABC-1 was not started in canopy' })
        render(<Notice error={refusal}>ignored</Notice>)
        expect(screen.getByRole('alert').textContent).toBe('refused (not_started): ABC-1 was not started in canopy')
        expect(screen.queryByText('ignored')).toBeNull()
    })

    it("sets a refusal's code spans as code, as an attention item's detail is", () => {
        const refusal = new ApiError(409, { guard: 'bad_ref', reason: 'not a chore: try `canopy chores`' })
        render(<Notice error={refusal} />)
        expect(screen.getByRole('alert').textContent).toBe('refused (bad_ref): not a chore: try canopy chores')
        expect(screen.getByRole('code').textContent).toBe('canopy chores')
    })

    it('says any other failure in its own words, or that the request failed', () => {
        const { rerender } = render(<Notice error={new ApiError(503, 'the journal is busy')} />)
        expect(screen.getByRole('alert').textContent).toBe('the journal is busy')
        rerender(<Notice error="no network" />)
        expect(screen.getByRole('alert').textContent).toBe('no network')
        rerender(<Notice error={{ unexpected: true }} />)
        expect(screen.getByRole('alert').textContent).toBe('the request failed')
    })

    it('says a failure that is not a refusal in canopy’s words, never the browser’s', () => {
        const { rerender } = render(<Notice error={new TypeError('Failed to fetch')} />)
        expect(screen.getByRole('alert').textContent).toBe('canopy did not answer: is canopy loop running?')
        rerender(<Notice error={new ApiError(500, undefined)} />)
        expect(screen.getByRole('alert').textContent).toBe('canopy failed (500): it may not have been done')
    })

    it('says what an action did as a status, and nothing when it has nothing to say', () => {
        const { rerender, container } = render(<Notice>Recorded message 4 on ABC-1.</Notice>)
        expect(screen.getByRole('status').textContent).toBe('Recorded message 4 on ABC-1.')
        rerender(<Notice error={null}>{null}</Notice>)
        expect(container.childElementCount).toBe(0)
        const empty = ''
        rerender(<Notice>{empty}</Notice>)
        expect(container.childElementCount).toBe(0)
    })

    it('keeps its line while it has nothing to say, when asked to', () => {
        const { rerender } = render(<Notice reserve>{null}</Notice>)
        expect(screen.getByRole('status').textContent).toBe('')
        rerender(<Notice reserve>Recorded message 4 on ABC-1.</Notice>)
        expect(screen.getByRole('status').textContent).toBe('Recorded message 4 on ABC-1.')
    })
})
