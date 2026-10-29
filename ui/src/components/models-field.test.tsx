import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { ModelsServed } from '@/api/types'

import { Fields } from './fields'
import { ModelsField } from './models-field'

afterEach(cleanup)

function renderModels(models: ModelsServed, asked: string | null = null) {
    return render(
        <Fields>
            <ModelsField models={models} asked={asked} />
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

    it('names the model canopy asked for until its session is read, why none served yet on hover', () => {
        renderModels({ status: 'running', models: [], error: null }, 'anthropic/claude-opus-4-1')
        const asked = screen.getByText('asked anthropic/claude-opus-4-1')
        expect(asked.getAttribute('title')).toBe('none served: read from its session once it ends')
        cleanup()
        renderModels({ status: 'failed', models: [], error: 'the runtime timed out' }, 'anthropic/claude-opus-4-1')
        expect(screen.getByText('asked anthropic/claude-opus-4-1').getAttribute('title')).toBe(
            'none served: its session could not be read, tried again later (the runtime timed out)',
        )
    })

    it('names only what served once read, when it is what canopy asked for', () => {
        renderModels(
            {
                status: 'found',
                models: [{ model: 'anthropic/claude-opus-4-1@high', replies: 4, cost_usd: 0.5 }],
                error: null,
            },
            'anthropic/claude-opus-4-1@high',
        )
        const served = screen.getByText('anthropic/claude-opus-4-1@high')
        expect(served.closest('.text-status-blocked')).toBeNull()
        expect(screen.queryByText(/asked/u)).toBeNull()
    })

    it("says what canopy asked for and what served, in the field's color, when it served none of the replies", () => {
        renderModels(
            {
                status: 'found',
                models: [{ model: 'anthropic/claude-sonnet-4-5', replies: 41, cost_usd: 0.66 }],
                error: null,
            },
            'anthropic/claude-opus-4-1',
        )
        const said = screen.getByText(/^asked/u)
        expect(said.textContent).toBe('asked anthropic/claude-opus-4-1 ≠ served anthropic/claude-sonnet-4-5')
        // Worth knowing, not waiting on the operator.
        expect(said.closest('[class*="text-status-"]')).toBeNull()
        expect(screen.getByText('anthropic/claude-sonnet-4-5').getAttribute('title')).toBe('41 replies')
    })

    it('takes a model at its default variant, which its session names alone, as the one asked for', () => {
        renderModels(
            { status: 'found', models: [{ model: 'openai/gpt-5', replies: 9, cost_usd: 0.4 }], error: null },
            'openai/gpt-5@medium',
        )
        expect(screen.getByText('openai/gpt-5').getAttribute('title')).toBe('9 replies')
        expect(screen.queryByText(/asked|≠/u)).toBeNull()
    })

    it('marks only the other model of a run the model asked for served too', () => {
        renderModels(
            {
                status: 'found',
                models: [
                    { model: 'anthropic/claude-opus-4-1', replies: 23, cost_usd: 1.65 },
                    { model: 'anthropic/claude-haiku-4-5', replies: 2, cost_usd: 0.01 },
                ],
                error: null,
            },
            'anthropic/claude-opus-4-1',
        )
        expect(screen.getByText(/claude-opus-4-1/u).textContent).toBe('anthropic/claude-opus-4-1 $1.65')
        const other = screen.getByText(/claude-haiku-4-5/u)
        expect(other.textContent).toBe('≠ anthropic/claude-haiku-4-5 $0.01')
        expect(other.getAttribute('title')).toBe('2 replies, not the model asked for')
        expect(screen.queryByText(/asked anthropic/u)).toBeNull()
    })

    it('gives why a read failed on hover', () => {
        renderModels({ status: 'failed', models: [], error: 'the runtime timed out after 30s' })
        const said = screen.getByText('none: its session could not be read, tried again later')
        expect(said.getAttribute('title')).toBe('the runtime timed out after 30s')
    })
})
