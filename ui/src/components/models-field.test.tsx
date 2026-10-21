import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ModelsServed } from '@/api/types'

import { Fields } from './fields'
import { ModelsField } from './models-field'

afterEach(cleanup)

function renderModels(models: ModelsServed) {
    return render(
        <Fields>
            <ModelsField models={models} />
        </Fields>,
    )
}

describe('ModelsField', () => {
    it('names the one model that served a run, its replies on hover, and leaves its cost to `spent`', () => {
        renderModels({
            status: 'found',
            models: [{ model: 'anthropic/claude-sonnet-4-5', replies: 1, cost_usd: 0.31 }],
            error: null,
        })
        expect(screen.getByText('model')).toBeTruthy()
        expect(screen.getByText('anthropic/claude-sonnet-4-5').getAttribute('title')).toBe('1 reply')
        expect(screen.queryByText('$0.31')).toBeNull()
    })

    it("splits a run's cost between the models it switched between, the most costly first", () => {
        renderModels({
            status: 'found',
            models: [
                { model: 'anthropic/claude-opus-4-1', replies: 23, cost_usd: 1.65 },
                { model: 'anthropic/claude-sonnet-4-5', replies: 41, cost_usd: 0.66 },
            ],
            error: null,
        })
        const opus = screen.getByText(/anthropic\/claude-opus-4-1/u)
        expect(opus.textContent).toBe('anthropic/claude-opus-4-1 $1.65')
        expect(opus.getAttribute('title')).toBe('23 replies')
        expect(screen.getByText(/anthropic\/claude-sonnet-4-5/u).textContent).toBe('anthropic/claude-sonnet-4-5 $0.66')
    })

    it.each([
        ['running', 'none: read from its session once it ends'],
        ['unread', "none: not read yet: a tick reads a few ended runs' sessions"],
        ['no_session', 'none: it reported no session to read'],
        ['missing', 'none: the runtime no longer keeps its session'],
    ] as const)('says why a run that is %s names no model', (status, said) => {
        renderModels({ status, models: [], error: null })
        expect(screen.getByText(said)).toBeTruthy()
    })

    it('says a session that made no call served no model', () => {
        renderModels({ status: 'found', models: [], error: null })
        expect(screen.getByText('none: its session made no model call')).toBeTruthy()
    })

    it('gives why a read failed on hover', () => {
        renderModels({ status: 'failed', models: [], error: 'the runtime timed out after 30s' })
        const said = screen.getByText('none: its session could not be read, tried again later')
        expect(said.getAttribute('title')).toBe('the runtime timed out after 30s')
    })
})
